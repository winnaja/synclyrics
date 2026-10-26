"""วัดว่า "เนื้อเพลงนี้เป็นของเพลงนี้ไหม" แยกได้ด้วยความเข้ากันกับเสียง (CTC) จริงไหม

ถูก = เสียงเพลง A + เนื้อเพลง A · ผิด = เสียงเพลง A + เนื้อเพลง B (ภาษาเดียวกัน เพื่อให้ยากเหมือนของจริง)
ตัวชี้วัด: ctc_score (ความมั่นใจเฉลี่ยของ CTC) และ ctc_to_result (ผ่านเกณฑ์ตรวจเวลาไหม)
ใช้ตั้งเกณฑ์ "เนื้อน่าจะเป็นคนละเพลง" จากข้อมูลจริงแทนการเดา

ใช้:  .venv\Scripts\python scripts\eval_wrong_song.py [--songs 60]
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", type=int, default=60)
    args = ap.parse_args()

    import numpy as np

    from app.ai.pipeline import align
    from app.ai.pipeline.match import InLine, ctc_score, ctc_to_result
    from app.ai.training.data import iter_songs
    from eval_aligner import load_aligner

    pool = [s for s in iter_songs("val")]
    random.seed(0)
    random.shuffle(pool)
    pool = pool[:args.songs]
    by_lang: dict[str, list] = {}
    for s in iter_songs(None):
        by_lang.setdefault((s.language or "?")[:2], []).append(s)
    mms = load_aligner(None)

    def lines_of(s):
        return [InLine(words=[w[0] for w in ln["words"]], start=ln["start"], end=ln["end"]) for ln in s.ref_lines() if ln["words"]]

    right, wrong = [], []
    for s in pool:
        lang = (s.language or "?")[:2]
        mates = [x for x in by_lang.get(lang, []) if x.id != s.id]
        if not mates:
            continue
        other = random.choice(mates)
        v = np.asarray(s.vocals(), dtype=np.float32)
        for tag, src, dest in (("right", s, right), ("wrong", other, wrong)):
            ln = lines_of(src)
            if len(ln) < 8:
                continue
            try:
                g = align.align_global(mms, v, [x.words for x in ln], s.language)
            except Exception:  # noqa: BLE001
                continue
            res = ctc_to_result(g, ln)
            dest.append({"score": ctc_score(g, ln), "passed": res is not None,
                         "cov": float(res.coverage) if res is not None else 0.0})
    print(f"ถูกเพลง {len(right)} · ผิดเพลง {len(wrong)}")
    for name, d in (("ถูกเพลง", right), ("ผิดเพลง", wrong)):
        if not d:
            continue
        sc = np.array([x["score"] for x in d])
        print(f"  {name}: ctc_score มัธยฐาน {np.median(sc):.3f} (25-75%: {np.percentile(sc, 25):.3f}-{np.percentile(sc, 75):.3f}) "
              f"· ผ่านการตรวจเวลา {np.mean([x['passed'] for x in d]):.0%} · coverage มัธยฐาน {np.median([x['cov'] for x in d]):.2f}")
    if right and wrong:
        a = np.array([x["score"] for x in right]); b = np.array([x["score"] for x in wrong])
        auc = float((a[:, None] > b[None, :]).mean() + 0.5 * (a[:, None] == b[None, :]).mean())
        print(f"\nctc_score แยกถูก/ผิดเพลง: AUC {auc:.3f} (0.5 = แยกไม่ได้เลย)")
        for thr in (0.05, 0.08, 0.10, 0.12, 0.15, 0.20):
            tpr = float((a >= thr).mean()); fpr = float((b >= thr).mean())
            print(f"  เกณฑ์ {thr:.2f}: เนื้อถูกที่ผ่าน {tpr:.0%} · เนื้อผิดที่หลุดผ่าน {fpr:.0%}")
        pr = np.mean([x["passed"] for x in right]); pw = np.mean([x["passed"] for x in wrong])
        print(f"ผ่านการตรวจเวลา (ctc_to_result): ถูก {pr:.0%} · ผิด {pw:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
