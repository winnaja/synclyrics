"""วิเคราะห์ว่า "ความผิดพลาดของเวลาคำ" กระจุกอยู่ตรงไหน — ทำก่อนตัดสินใจเทรนเพิ่ม

แยกตาม: ภาษา · คำที่ลากเสียงยาว/สั้น · ท่อนที่ร้องเร็ว (แร็ป) · จำนวนตัวอักษร (คำหลายพยางค์) · ตำแหน่งในบรรทัด
เกณฑ์ที่รายงาน: ≤50 / ≤100 / ≤200 มิลลิวินาที ทั้งเวลาเริ่มคำและจบคำ

ใช้:  .venv\\Scripts\\python scripts\\error_report.py [--model ไฟล์.pt] [--limit N] [--raw-audio]
--raw-audio = ใช้เสียงรวม (ยังไม่แยกเสียงร้อง) เพื่อทดสอบว่า Demucs ช่วยหรือทำให้แย่ลง
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PIN = ROOT / "dataset" / "val_songs.txt"


def buckets(word, dur, rate, pos, n_words, lang):
    """-> ชื่อกลุ่มที่คำนี้สังกัด (คำหนึ่งอยู่ได้หลายกลุ่ม)"""
    out = [f"ภาษา {lang}"]
    out.append("ลากยาว (>0.6 วิ)" if dur > 0.6 else "สั้นมาก (<0.2 วิ)" if dur < 0.2 else "ปกติ (0.2-0.6 วิ)")
    out.append("ร้องเร็ว (>4 คำ/วิ)" if rate > 4 else "ร้องช้า (<2 คำ/วิ)" if rate < 2 else "ความเร็วปกติ")
    out.append("ตัวอักษรเยอะ (>6)" if len(word) > 6 else "ตัวอักษรน้อย (<=3)" if len(word) <= 3 else "ตัวอักษรปานกลาง")
    if pos == 0:
        out.append("คำแรกของบรรทัด")
    elif pos == n_words - 1:
        out.append("คำสุดท้ายของบรรทัด")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(ROOT / "ai_runtime" / "models" / "mms_singing.pt"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--raw-audio", action="store_true")
    args = ap.parse_args()

    import numpy as np

    from eval_aligner import load_aligner

    from app.ai.training.data import iter_songs

    songs = sorted(iter_songs("val"), key=lambda s: s.meta.get("ref_timing", "word") != "word")
    if PIN.exists():
        want = [x for x in PIN.read_text(encoding="utf-8").split() if x]
        have = {s.id: s for s in songs}
        songs = [have[i] for i in want if i in have]
    songs = [s for s in songs if s.meta.get("ref_timing") == "word"]
    if args.limit:
        songs = songs[:args.limit]
    mms = load_aligner(args.model or None)
    from app.ai.pipeline import align

    start_e: dict[str, list[float]] = collections.defaultdict(list)
    end_e: dict[str, list[float]] = collections.defaultdict(list)
    print(f"วิเคราะห์ {len(songs)} เพลง · โมเดล {Path(args.model).name if args.model else 'MMS เดิม'}"
          f"{' · เสียงรวม (ไม่แยกเสียงร้อง)' if args.raw_audio else ''}", flush=True)
    for n, s in enumerate(songs, 1):
        ref = s.ref_lines()
        v = np.asarray(s.vocals(), dtype=np.float32)
        try:
            out = align.align_global(mms, v, [[w[0] for w in ln["words"]] for ln in ref], s.language)
        except Exception as e:  # noqa: BLE001
            print(f"  {s.id}: ผิดพลาด {str(e)[:80]}")
            continue
        lang = (s.meta.get("language") or "?")[:2]
        for ln, o in zip(ref, out):
            if not o or len(o) != len(ln["words"]):
                continue
            span = max(1e-6, ln["end"] - ln["start"])
            rate = len(ln["words"]) / span
            for i, (w, sp) in enumerate(zip(ln["words"], o)):
                dur = float(w[2]) - float(w[1])
                se = abs(float(sp[0]) - float(w[1]))
                ee = abs(float(sp[1]) - float(w[2]))
                for b in buckets(w[0], dur, rate, i, len(ln["words"]), lang) + ["รวมทั้งหมด"]:
                    start_e[b].append(se)
                    end_e[b].append(ee)
        if n % 20 == 0:
            print(f"  {n}/{len(songs)}", flush=True)

    print(f"\n{'กลุ่ม':26s} {'คำ':>7s} | {'เริ่ม≤50ms':>9s} {'≤100':>6s} {'≤200':>6s} | {'จบ≤50ms':>8s} {'≤100':>6s} {'≤200':>6s}")
    order = sorted(start_e, key=lambda k: (k != "รวมทั้งหมด", k))
    for b in order:
        a, c = np.array(start_e[b]), np.array(end_e[b])
        if len(a) < 50:
            continue
        print(f"{b:26s} {len(a):7d} | {(a <= .05).mean():9.0%} {(a <= .1).mean():6.0%} {(a <= .2).mean():6.0%} "
              f"| {(c <= .05).mean():8.0%} {(c <= .1).mean():6.0%} {(c <= .2).mean():6.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
