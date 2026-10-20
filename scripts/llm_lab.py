"""ทดลองให้โมเดลภาษาในเครื่องวิเคราะห์เนื้อเพลง (ท่อน/เสียงประสาน/คำเน้น/ขยะ) — ดูผลและความเร็ว

ใช้:  .venv\\Scripts\\python scripts\\llm_lab.py <สำเนา sqlite> <videoId>[,<videoId>...]
(เนื้อเพลงอ่านจากตาราง lyrics ของสำเนา — ห้ามชี้ไปฐานข้อมูลจริงของแอป)
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    db, ids = sys.argv[1], sys.argv[2].split(",")
    from app.ai.env import setup_ai_environment
    from app.core.config import ModelsConfig, load_model
    from app.core.paths import get_paths

    cfg, _ = load_model(get_paths(), "models.yaml", ModelsConfig)
    setup_ai_environment(cfg.model_dump())
    import torch  # noqa: F401  (ให้ DLL CUDA พร้อมก่อน ctranslate2)

    from app.ai.llm import COMPACT_SYSTEM, LyricsLLM, build_user_prompt, parse_compact

    name = sys.argv[3] if len(sys.argv) > 3 else "qwen2.5-3b-instruct-ct2-int8"
    model_dir = ROOT / "ai_runtime" / "models" / "llm" / name
    t0 = time.time()
    llm = LyricsLLM(model_dir, "cuda")
    print(f"โหลดโมเดล {time.time() - t0:.1f}s")
    con = sqlite3.connect(db)
    for vid in ids:
        row = con.execute("select payload, language from lyrics where video_id=? order by score desc", (vid,)).fetchone()
        if not row:
            print(vid, "ไม่มีเนื้อเพลง")
            continue
        d = json.loads(row[0])
        lines = ["".join(w["text"] + (" " if w.get("trailing_space") else "") for w in ln["words"]).strip() or "" for ln in d["lines"]]
        lines = [t for t in lines if t]
        t0 = time.time()
        out = llm.chat(COMPACT_SYSTEM, build_user_prompt(lines, d.get("title") or "", "", row[1] or ""), max_new_tokens=160, no_think="qwen3" in name and "2507" not in name)
        dt = time.time() - t0
        ann = parse_compact(out, lines)
        print(f"\n=== {vid}  {len(lines)} บรรทัด  {dt:.1f}s ===")
        print(out[:400])
        if ann:
            print("  backing:", [f"{k + 1}:{lines[k][:24]}" for k in ann["backing"]])
            print("  emphasis:", [(e["line"] + 1, e["word"], lines[e["line"]][:30]) for e in ann["emphasis"]])
            print("  junk:", [f"{k + 1}:{lines[k][:24]}" for k in ann["junk"]])
        else:
            print("  (อ่านผลไม่ได้)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
