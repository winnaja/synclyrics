"""วัดความแม่นของตัวจัดเวลา (CTC ทั้งเพลง) กับเฉลยรายคำในชุดข้อมูล — เทียบ MMS เดิมกับที่ fine-tune แล้ว

ใช้:  .venv\\Scripts\\python scripts\\eval_aligner.py [--split val|train|all] [--model <ไฟล์ .pt>] [--limit N]
ไม่ใส่ --model = MMS_FA เดิม · พิมพ์ median / ≤0.15 วิ / ≤0.3 วิ ของคลาดเวลาเริ่มคำ รวมและรายเพลง
"""

from __future__ import annotations

import argparse
import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def evaluate(mms, songs, verbose: bool = True) -> dict:
    import numpy as np

    from app.ai.pipeline import align

    allerr: list[float] = []
    per: list[tuple[str, float, float, float]] = []
    for s in songs:
        ref = s.ref_lines()
        words = [[w[0] for w in ln["words"]] for ln in ref]
        v = np.asarray(s.vocals(), dtype=np.float32)
        try:
            out = align.align_global(mms, v, words, s.language)
        except Exception as e:  # noqa: BLE001
            print(f"  {s.id}: ผิดพลาด {e}")
            continue
        err = []
        for ln, o in zip(ref, out):
            if not o or len(o) != len(ln["words"]):
                continue
            err += [abs(float(sp[0]) - float(w[1])) for w, sp in zip(ln["words"], o)]
        if not err:
            continue
        a = np.array(err)
        allerr += list(a)
        per.append((s.id, float(np.median(a)), float((a <= 0.15).mean()), float((a <= 0.3).mean())))
        if verbose:
            print(f"  {s.id:16s} {str(s.meta.get('title'))[:28]:28s} words={len(a):4d} median={np.median(a):.3f} ≤0.15={(a <= 0.15).mean():.0%} ≤0.3={(a <= 0.3).mean():.0%}")
    if not allerr:
        return {"songs": 0}
    a = np.array(allerr)
    return {"songs": len(per), "words": len(a), "median": float(np.median(a)), "le015": float((a <= 0.15).mean()), "le03": float((a <= 0.3).mean()),
            "per_song_median": float(np.median([p[1] for p in per]))}


def load_aligner(model_path: str | None):
    from app.ai.env import setup_ai_environment
    from app.core.config import ModelsConfig, load_model
    from app.core.paths import get_paths

    paths = get_paths()
    cfg, _ = load_model(paths, "models.yaml", ModelsConfig)
    md = cfg.model_dump()
    if model_path:
        md.setdefault("align", {})["finetuned"] = model_path
    setup_ai_environment(md)
    import torch  # noqa: F401

    from app.ai.worker import Worker

    w = Worker(queue.Queue(), None, {"models": md, "stems_dir": str(paths.stems_cache_dir)})
    w.emit = lambda *a, **k: None  # type: ignore[assignment]
    w.setup()
    return w.mms()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="val", choices=["val", "train", "all"])
    ap.add_argument("--model", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    from app.ai.training.data import iter_songs

    songs = list(iter_songs(None if args.split == "all" else args.split))
    if args.limit:
        songs = songs[:args.limit]
    print(f"เพลงที่ใช้วัด: {len(songs)} ({args.split}) · โมเดล: {args.model or 'MMS_FA เดิม'}")
    if not songs:
        print("ไม่มีเพลงที่ใช้ได้ — รัน scripts/harvest.py ก่อน")
        return 1
    res = evaluate(load_aligner(args.model or None), songs)
    print("รวม:", res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
