"""ทดลองขั้นหลัง Whisper แบบออฟไลน์ (ใช้ transcript/vocals ที่ cache ไว้ ไม่ต้องใช้ GPU) — ดูผลบรรทัดสุดท้ายที่แอปจะแสดง

ใช้:  .venv\\Scripts\\python scripts\\ai_offline.py <videoId> [--from 140 --to 180]
พิมพ์บรรทัดที่จะแสดง (เวลา · ข้อความ) และเตือนบรรทัดซ้ำ/เวลาทับกัน
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
    ap.add_argument("video_id")
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", dest="t1", type=float, default=1e9)
    args = ap.parse_args()

    import json
    import os

    if os.environ.get("SYNC_DB"):    # ฐานข้อมูลของแอปเสียหายอยู่/ถูกล็อก: ใช้สำเนาแทน
        from app.core import paths as _paths

        _orig = _paths.get_paths

        def _patched():
            p = _orig()
            return type("P", (), {**{k: getattr(p, k) for k in dir(p) if not k.startswith("_")}, "db_file": Path(os.environ["SYNC_DB"])})()

        _paths.get_paths = _patched

    from app.ai.pipeline.match import (NOSPACE_LANGS, InLine, TWord, clean_transcript, fill_missing_lines, match_lines,
                                       norm_chars, reconstruct_by_transcript)
    from app.core.paths import get_paths
    from asr_lab import lyrics_input_for

    paths = get_paths()
    d = json.loads((paths.stems_cache_dir / args.video_id / "transcript.json").read_text(encoding="utf-8"))
    words = [TWord(*w) for w in d["words"]]
    vsegs = [tuple(x) for x in d["vocal_segments"]]
    data = lyrics_input_for(args.video_id)
    lines = [InLine(words=ln["words"], start=ln["start"], end=ln["end"]) for ln in data["lines"]]
    lang = data["language"]
    clean = clean_transcript(words)
    print(f"transcript={len(words)} clean={len(clean)} lyric_lines={len(lines)} lang={lang}")
    rr = reconstruct_by_transcript(lines, clean, nospace=lang in NOSPACE_LANGS, web_only=True)
    print(f"reconstruct lines={len(rr.lines)} coverage={rr.coverage:.0%}")
    rr = fill_missing_lines(rr, lines, vsegs, float(d["duration"]))
    prev = None
    for ln in rr.lines:
        if ln.end < args.t0 or ln.start > args.t1:
            prev = ln
            continue
        text = " ".join(ln.text_words)
        flag = ""
        if prev is not None:
            a, b = norm_chars("".join(prev.text_words)), norm_chars("".join(ln.text_words))
            if a and b and (a in b or b in a) and min(len(a), len(b)) >= 6:
                flag += " [ซ้ำกับบรรทัดก่อน]"
            if ln.start < prev.end - 0.05:
                flag += " [เวลาทับ]"
        print(f"{ln.start:7.2f}-{ln.end:7.2f} src={ln.src}  {text}{flag}")
        prev = ln
    return 0


if __name__ == "__main__":
    sys.exit(main())
