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
KIDS = ROOT / "dataset" / ".children.json"       # pid ของโปรเซสลูก เอาไว้เก็บกวาดถ้ารอบก่อนถูกฆ่าแบบไม่ทันลา
BEST = ROOT / "ai_runtime" / "models" / "mms_singing.pt"


def kill_strays() -> None:
    """ฆ่าโปรเซสลูกที่ค้างจากรอบก่อน — ปิดลูปด้วย Stop-Process ลูกไม่ตายตาม แล้วจะมาแย่งการ์ดจอ/แรม
    (เคยเจอ: ตัวเทรนค้างทำให้เทรนช้าลง 20 เท่าและดิสก์หายไป 10 GB)"""
    for pid in _load(KIDS) or []:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=20)
        except Exception:  # noqa: BLE001
            pass
    _save(KIDS, [])


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(path: Path, obj) -> None:
    try:
        path.write_text(json.dumps(obj), encoding="utf-8")
    except OSError:
        pass


def improved(logfile: Path) -> bool:
    """รอบล่าสุดได้น้ำหนักที่ดีกว่าเดิมไหม — train_ctc พิมพ์ ★ ทุกครั้งที่บันทึกทับ"""
    try:
        text = logfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "★" in text.rsplit("=====", 1)[-1]


def _write(rec: dict) -> None:
    with STATE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))


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
        p = subprocess.Popen(args, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,  # noqa: S603
                             env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                  "PYTORCH_CUDA_ALLOC_CONF": "garbage_collection_threshold:0.7,max_split_size_mb:256"})
        _save(KIDS, [p.pid])
        try:
            return p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=20)
            p.wait()
            return 124
        finally:
            _save(KIDS, [])


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
    ap.add_argument("--weak-cats", default="thai,korean", help="หมวดที่ข้อมูลยังน้อย เก็บสลับรอบเว้นรอบ ("" = ปิด)")
    ap.add_argument("--min-free-gb", type=float, default=12.0, help="เหลือน้อยกว่านี้ = เลิกโหลดเพลงเพิ่ม (เทรนต่อได้)")
    ap.add_argument("--max-rounds", type=int, default=0, help="0 = ไม่จำกัด")
    args = ap.parse_args()

    STOP.unlink(missing_ok=True)
    kill_strays()
    hlog, tlog = ROOT / "dataset" / "forever_harvest.log", ROOT / "dataset" / "forever_train.log"
    log(f"เริ่มวนเทรน · หยุดด้วยการสร้างไฟล์ {STOP}")
    log(f"เพลงตอนนี้: {counts()} · ดิสก์ว่าง {free_gb():.0f} GB")
    rnd = 0
    harvest_dead = False       # ไม่มีเพลงเฉลยรายคำให้โหลดเพิ่มแล้ว -> เทรนอย่างเดียว
    while not stopped() and (not args.max_rounds or rnd < args.max_rounds):
        rnd += 1
        rec: dict = {"round": rnd, "at": time.strftime("%Y-%m-%d %H:%M:%S")}

        # 1) เทรนก่อนเสมอ — ต่อจากน้ำหนักที่ดีที่สุด (บันทึกทับเมื่อคะแนนรายคำดีขึ้นเท่านั้น)
        log(f"รอบ {rnd}: เทรน {args.steps_per_round} ก้าว ...")
        cmd = [PY, "-u", "scripts/train_ctc.py", "--epochs", "99", "--max-steps", str(args.steps_per_round)]
        if BEST.exists():
            cmd += ["--init", str(BEST)]
        rc = run(cmd, tlog, timeout_s=6 * 3600)
        v = last_val(tlog)
        gained = improved(tlog)
        rec.update({"train_rc": rc, "val": v, "improved": gained})
        if v:
            log(f"รอบ {rnd} จบ: เริ่มคำ ≤0.15 วิ {v.get('word_le015', 0):.1%} · จบคำ ≤0.15 วิ {v.get('end_le015', 0):.1%} "
                f"· เริ่มบรรทัด ≤0.3 วิ {v.get('le03', 0):.1%} · {'ดีขึ้น' if gained else 'ไม่ดีขึ้น'} (rc={rc})")
        else:
            log(f"รอบ {rnd} จบ: ไม่มีผลวัด (rc={rc}) — ดู {tlog}")
        if rc not in (0, 124):
            log("เทรนจบด้วยข้อผิดพลาด — พัก 60 วิแล้วลองรอบถัดไป")
            time.sleep(60)
        if stopped():
            _write(rec)
            break

        # 2) โหลดเพลงเพิ่ม "เฉพาะเมื่อเทรนแล้วไม่ดีขึ้น" = ข้อมูลที่มีถูกใช้จนหมดประโยชน์แล้ว จึงค่อยเติมของใหม่
        if gained:
            rec["harvest_skipped"] = "ยังดีขึ้นอยู่ ใช้ข้อมูลเดิมต่อ"
        elif harvest_dead:
            rec["harvest_skipped"] = "กองเพลงหมด"
        elif free_gb() <= args.min_free_gb:
            rec["harvest_skipped"] = f"ดิสก์เหลือ {free_gb():.0f} GB"
            log(f"รอบ {rnd}: ดิสก์เหลือน้อย ({free_gb():.0f} GB) — ไม่โหลดเพลงเพิ่ม เทรนต่ออย่างเดียว")
        else:
            before = counts()
            # สลับ: ครั้งนี้เก็บภาษาที่ข้อมูลน้อย (ไทย/เกาหลี ไม่บังคับเฉลยรายคำ เพราะหายาก) ครั้งหน้าเก็บเฉลยรายคำทั่วไป
            focus = bool(args.weak_cats) and (rec.get("round", 0) % 2 == 1)
            log(f"รอบ {rnd}: เทรนไม่ดีขึ้นแล้ว -> โหลดเพลงเพิ่ม {args.songs_per_round} เพลง "
                f"({'เน้น ' + args.weak_cats if focus else 'เฉลยรายคำทั่วไป'}) ...")
            hcmd = [PY, "-u", "scripts/harvest.py", "--plan", str(args.pool),
                    "--max-new", str(args.songs_per_round), "--batch", str(args.songs_per_round),
                    "--cookies-dir", "dataset/_cookies", "--workers", str(args.workers), "--sleep", str(args.sleep)]
            hcmd += ["--cats", args.weak_cats] if focus else ["--word-only"]
            hrc = run(hcmd, hlog, timeout_s=4 * 3600)
            after = counts()
            got = after["word_train"] + after["word_val"] - before["word_train"] - before["word_val"]
            rec.update({"harvest_rc": hrc, "new_word_songs": got})
            log(f"รอบ {rnd}: ได้เพลงรายคำเพิ่ม {got} เพลง (rc={hrc}) · รวม {after['word_train'] + after['word_val']}")
            if got == 0 and hrc == 0 and not focus:
                harvest_dead = True
                log("ไม่มีเพลงเฉลยรายคำใหม่ให้โหลดแล้ว — จากนี้เทรนอย่างเดียว")
        rec["songs"] = counts()
        rec["free_gb"] = round(free_gb(), 1)
        _write(rec)
    log(f"หยุดแล้วที่รอบ {rnd} ({'สั่งหยุด' if stopped() else 'ครบจำนวนรอบ'})")
    STOP.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
