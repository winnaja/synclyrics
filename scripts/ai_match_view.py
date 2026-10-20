"""ดูผลจัดเวลาโหมดจับคู่ (เนื้อเพลงเว็บ + transcript ที่ cache ไว้) แบบออฟไลน์ — เทียบเวลาเดิมของเว็บกับเวลาที่ AI จัด

ใช้:  SYNC_DB=<สำเนา sqlite> .venv\Scripts\python scripts\ai_match_view.py <videoId>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    vid = sys.argv[1]
    if os.environ.get("SYNC_DB"):
        from app.core import paths as _paths

        _orig = _paths.get_paths

        def _patched():
            p = _orig()
            return type("P", (), {**{k: getattr(p, k) for k in dir(p) if not k.startswith("_")}, "db_file": Path(os.environ["SYNC_DB"])})()

        _paths.get_paths = _patched
    from app.ai.pipeline.match import InLine, TWord, clean_transcript, match_lines
    from app.core.paths import get_paths
    from asr_lab import lyrics_input_for

    paths = get_paths()
    d = json.loads((paths.stems_cache_dir / vid / "transcript.json").read_text(encoding="utf-8"))
    tw = clean_transcript([TWord(*w) for w in d["words"]])
    data = lyrics_input_for(vid)
    lines = [InLine(words=ln["words"], start=ln["start"], end=ln["end"],
                    word_times=[tuple(x) for x in ln["word_times"]] if ln.get("word_times") else None) for ln in data["lines"]]
    res = match_lines(lines, tw)
    import numpy as np

    from app.ai.pipeline.vocal_activity import compact_line_outliers, snap_line_onset, snap_words_to_voice

    voice = np.load(paths.stems_cache_dir / vid / "vocals16k.npy").astype("float32")
    if os.environ.get("NOSNAP") != "1":
        for ol in res.lines:
            if ol.resolved and ol.words:
                ol.words = [tuple(w) for w in snap_words_to_voice(snap_line_onset(compact_line_outliers([list(w) for w in ol.words]), voice), voice)]
                ol.start = ol.words[0][0]
    if os.environ.get("SUMMARY") == "1":
        ds = [ol.start - s["start"] for s, ol in zip(data["lines"], res.lines) if ol.resolved and s["start"] is not None]
        if ds:
            med = float(np.median(ds))
            tight = float(np.mean([abs(d - med) <= 0.5 for d in ds]))
            print(f"{vid}: lines={len(lines)} resolved={len(ds)} coverage={res.coverage:.0%} medianΔ={med:+.2f}s  ภายใน ±0.5s ของค่ากลาง={tight:.0%}  สูงสุดคลาด={max(abs(d - med) for d in ds):.1f}s")
        return 0
    print(f"lines={len(lines)} coverage={res.coverage:.0%} offset={res.offset_s} scale={res.scale} notes={res.notes}")
    for i, (src, ol) in enumerate(zip(data["lines"], res.lines)):
        s0 = src["start"]
        flag = "OK " if ol.resolved else "-- "
        d_ = f"{ol.start - s0:+6.2f}" if s0 is not None else "   n/a"
        print(f"{i:3d} {flag} web={s0 if s0 is None else round(s0, 2)!s:>7}  ai={ol.start:7.2f}  Δ={d_}  q={ol.quality:.2f}  {' '.join(src['words'])[:50]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
