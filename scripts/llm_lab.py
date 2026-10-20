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

    from app.ai.llm import SYSTEM_PROMPT, LyricsLLM, build_user_prompt, parse_analysis

    model_dir = ROOT / "ai_runtime" / "models" / "llm" / "qwen3-4b-instruct-2507-ct2-int8"
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
        out = llm.chat(SYSTEM_PROMPT, build_user_prompt(lines, d.get("title") or "", "", row[1] or ""), max_new_tokens=900)
        dt = time.time() - t0
        ann = parse_analysis(out, len(lines))
        print(f"\n=== {vid}  {len(lines)} บรรทัด  {dt:.1f}s ===")
        print(out[:700])
        if ann:
            for s in ann["sections"]:
                print(f"  [{s['label'] or '-':9s}] {s['from'] + 1}-{s['to'] + 1}: {lines[s['from']][:34]} … {lines[s['to']][:30]}")
            print("  backing:", [f"{k + 1}:{lines[k][:20]}" for k in ann["backing"]])
            print("  emphasis:", [(e["line"] + 1, e["word"]) for e in ann["emphasis"]])
            print("  junk:", [f"{k + 1}:{lines[k][:20]}" for k in ann["junk"]])
        else:
            print("  (อ่านผลไม่ได้)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
