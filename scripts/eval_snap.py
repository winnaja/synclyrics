"""วัดว่าขั้นปรับเวลาให้ตรงเสียง (compact → snap_line_onset → snap_words_to_voice) ทำให้เวลาเริ่ม/จบคำใกล้เฉลยขึ้นหรือแย่ลง
เทียบ: ผล CTC ดิบ · ของเดิม (MID_WORD_KEEP_IF_VOICED=False) · ของใหม่ — เฉพาะเพลงที่เฉลยรายคำจริง
ใช้:  .venv\Scripts\python scripts\eval_snap.py [--limit 40]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--model", default="ai_runtime/models/mms_singing.pt")
    args = ap.parse_args()
    import numpy as np

    from app.ai.pipeline import align
    from app.ai.pipeline import vocal_activity as va
    from app.ai.training.data import iter_songs
    from eval_aligner import load_aligner

    mms = load_aligner(args.model)
    songs = [s for s in iter_songs("val") if s.meta.get("ref_timing", "word") == "word"][:args.limit]
    stages = ["ดิบ", "compact", "+onset(เดิม)", "+onset(ใหม่)", "+snap_words(ใหม่)", "ครบ(เดิม)"]
    pos = ("แรก", "กลาง", "ท้าย")
    res = {st: {p: [] for p in pos} for st in stages}
    for s in songs:
        ref = s.ref_lines()
        words = [[w[0] for w in ln["words"]] for ln in ref]
        v = np.asarray(s.vocals(), dtype=np.float32)
        try:
            out = align.align_global(mms, v, words, s.language)
        except Exception as e:  # noqa: BLE001
            print("ข้าม", s.id, str(e)[:60])
            continue
        for ln, o in zip(ref, out):
            if not o or len(o) != len(ln["words"]) or len(o) < 3:
                continue
            raw = [[float(x[0]), float(x[1]), float(x[2])] for x in o]
            comp = va.compact_line_outliers(raw)
            va.MID_WORD_KEEP_IF_VOICED = False
            on_old = va.snap_line_onset(comp, v)
            full_old = va.snap_words_to_voice(on_old, v)
            va.MID_WORD_KEEP_IF_VOICED = True
            on_new = va.snap_line_onset(comp, v)
            full_new = va.snap_words_to_voice(on_new, v)
            for st, w in zip(stages, (raw, comp, on_old, on_new, full_new, full_old)):
                for k, (a, b) in enumerate(zip(ln["words"], w)):
                    res[st]["แรก" if k == 0 else ("ท้าย" if k == len(w) - 1 else "กลาง")].append(abs(b[0] - float(a[1])))
        print("เสร็จ", s.id, flush=True)
    for st in stages:
        print(f"{st:18s}", " | ".join(f"{p}: ≤0.15 {np.mean(np.array(res[st][p]) <= .15):.1%} ≤0.3 {np.mean(np.array(res[st][p]) <= .3):.1%}" for p in pos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
