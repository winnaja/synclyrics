"""วนโหลดเพลงเพิ่ม + เทรนตัวจัดเวลา สลับกันไปเรื่อยๆ จนกว่าจะสั่งหยุด (เน้นความแม่น "รายคำ")

ใช้:  .venv\\Scripts\\python scripts\\train_forever.py
หยุด: สร้างไฟล์ dataset\\STOP  (จบรอบที่ทำอยู่แล้วหยุดเอง) หรือปิดโปรเซสทิ้ง

แต่ละรอบ: โหลดเพลงที่ "เฉลยรายคำ" เพิ่ม --songs-per-round เพลง -> เทรนต่อจากน้ำหนักที่ดีที่สุด --steps-per-round ก้าว
น้ำหนักที่ดีที่สุด (ตัดสินด้วยคะแนนรายคำบน val) ถูกบันทึกทับ ai_runtime/models/mms_singing.pt ทุกครั้งที่ดีขึ้น
สรุปแต่ละรอบต่อท้าย dataset/train_forever.jsonl · การ์ดจอทำได้ทีละอย่าง จึงสลับกัน ไม่รันพร้อมกัน
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
STOP = ROOT / "dataset" / "STOP"
STATE = ROOT / "dataset" / "train_forever.jsonl"
BEST = ROOT / "ai_runtime" / "models" / "mms_singing.pt"


def log(msg: str) -> None:
    print(f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def stopped() -> bool:
    return STOP.exists()


def free_gb() -> float:
    return shutil.disk_usage(ROOT).free / 1e9


def counts() -> dict:
    """จำนวนเพลงที่ใช้ได้ตอนนี้ (รวม/รายคำ) — อ่านใหม่ทุกครั้งเพราะ harvest เพิ่มเพลงระหว่างทาง"""
    from app.ai.training.data import iter_songs

    out = {}
    for name, kw in (("usable", {}), ("word", {"need_word": True})):
        out[name + "_train"] = sum(1 for _ in iter_songs("train", **kw))
        out[name + "_val"] = sum(1 for _ in iter_songs("val", **kw))
    return out


def run(args: list[str], logfile: Path, timeout_s: float) -> int:
    """รันคำสั่งลูก เขียน log ต่อท้ายไฟล์ · คืน returncode (124 = เกินเวลา)"""
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with logfile.open("a", encoding="utf-8") as f:
        f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args[1:])} =====\n")
        f.flush()
        p = subprocess.Popen(args, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                  "PYTORCH_CUDA_ALLOC_CONF": "garbage_collection_threshold:0.7,max_split_size_mb:256"})
        try:
            return p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            return 124


def last_val(logfile: Path) -> dict:
    """ผลวัดครั้งสุดท้ายจาก log ของ train_ctc"""
    best: dict = {}
    try:
        for line in logfile.read_text(encoding="utf-8", errors="replace").splitlines():
            i = line.find("{")
            if i > 0 and ("val" in line[:i]):
                try:
                    d = json.loads(line[i:].replace("'", '"'))
                except ValueError:
                    continue
                if d.get("songs"):
                    best = d
    except OSError:
        pass
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs-per-round", type=int, default=175)
    ap.add_argument("--steps-per-round", type=int, default=3000)
    ap.add_argument("--pool", type=int, default=6000, help="ขนาดกองเพลงที่จะสุ่มเลือก (--plan ของ harvest)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=4.0)
    ap.add_argument("--min-free-gb", type=float, default=12.0, help="เหลือน้อยกว่านี้ = เลิกโหลดเพลงเพิ่ม (เทรนต่อได้)")
    ap.add_argument("--max-rounds", type=int, default=0, help="0 = ไม่จำกัด")
    args = ap.parse_args()

    STOP.unlink(missing_ok=True)
    hlog, tlog = ROOT / "dataset" / "forever_harvest.log", ROOT / "dataset" / "forever_train.log"
    log(f"เริ่มวนเทรน · หยุดด้วยการสร้างไฟล์ {STOP}")
    log(f"เพลงตอนนี้: {counts()} · ดิสก์ว่าง {free_gb():.0f} GB")
    rnd = 0
    harvest_dead = False       # ไม่มีเพลงเฉลยรายคำให้โหลดเพิ่มแล้ว -> เทรนอย่างเดียว
    while not stopped() and (not args.max_rounds or rnd < args.max_rounds):
        rnd += 1
        rec: dict = {"round": rnd, "at": time.strftime("%Y-%m-%d %H:%M:%S")}

        # 1) โหลดเพลงที่เฉลยเป็นเวลารายคำเพิ่ม (เฉลยรายคำ = สอนและวัด "ทีละคำ" ได้จริง)
        before = counts()
        if not harvest_dead and free_gb() > args.min_free_gb:
            log(f"รอบ {rnd}: โหลดเพลงเฉลยรายคำอีก {args.songs_per_round} เพลง ...")
            rc = run([PY, "-u", "scripts/harvest.py", "--plan", str(args.pool), "--word-only",
                      "--max-new", str(args.songs_per_round), "--batch", str(args.songs_per_round),
                      "--cookies-dir", "dataset/_cookies", "--workers", str(args.workers),
                      "--sleep", str(args.sleep)], hlog, timeout_s=4 * 3600)
            after = counts()
            got = after["word_train"] + after["word_val"] - before["word_train"] - before["word_val"]
            rec.update({"harvest_rc": rc, "new_word_songs": got})
            log(f"รอบ {rnd}: ได้เพลงรายคำเพิ่ม {got} เพลง (rc={rc}) · รวม {after['word_train'] + after['word_val']}")
            if got == 0 and rc == 0:
                harvest_dead = True       # กองเพลงหมด: รอบต่อไปข้ามการโหลด
                log("ไม่มีเพลงเฉลยรายคำใหม่ให้โหลดแล้ว — จากนี้เทรนอย่างเดียว")
        else:
            rec["harvest_skipped"] = "ดิสก์เหลือน้อย" if free_gb() <= args.min_free_gb else "กองเพลงหมด"
        if stopped():
            break

        # 2) เทรนต่อจากน้ำหนักที่ดีที่สุด (บันทึกทับเมื่อคะแนนรายคำดีขึ้นเท่านั้น)
        log(f"รอบ {rnd}: เทรน {args.steps_per_round} ก้าว ...")
        cmd = [PY, "-u", "scripts/train_ctc.py", "--epochs", "99", "--max-steps", str(args.steps_per_round)]
        if BEST.exists():
            cmd += ["--init", str(BEST)]
        rc = run(cmd, tlog, timeout_s=6 * 3600)
        v = last_val(tlog)
        rec.update({"train_rc": rc, "val": v, "songs": counts(), "free_gb": round(free_gb(), 1)})
        with STATE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if v:
            log(f"รอบ {rnd} จบ: เริ่มคำ ≤0.15 วิ {v.get('word_le015', 0):.1%} · จบคำ ≤0.15 วิ {v.get('end_le015', 0):.1%} "
                f"· เริ่มบรรทัด ≤0.3 วิ {v.get('le03', 0):.1%} (rc={rc})")
        else:
            log(f"รอบ {rnd} จบ: ไม่มีผลวัด (rc={rc}) — ดู {tlog}")
        if rc not in (0, 124):
            log("เทรนจบด้วยข้อผิดพลาด — พัก 60 วิแล้วลองรอบถัดไป")
            time.sleep(60)
    log(f"หยุดแล้วที่รอบ {rnd} ({'สั่งหยุด' if stopped() else 'ครบจำนวนรอบ'})")
    STOP.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
