"""วัดความแม่นของ "เวลา" ที่ AI จัดให้ โดยเทียบกับเนื้อเพลงที่มีเวลารายคำจากต้นฉบับ (NetEase/QQ) เป็นเฉลย

รัน job จัดเวลาของ worker จริง (Demucs → Whisper → จับคู่ → MMS) แล้วเทียบเวลาเริ่มของแต่ละคำกับเฉลย
ใช้:  .venv\\Scripts\\python scripts\\ai_timing_eval.py <videoId>[,<videoId>...] [--db <สำเนา sqlite>] [--audio-dir <โฟลเดอร์>]
เสียงหาจาก <audio-dir>/<id>/<id>.* (ค่าเริ่มต้น: cache/analysis ของแอป)
ตัวชี้วัด: median |Δ| ของเวลาเริ่มคำ และสัดส่วนที่คลาดไม่เกิน 0.15 / 0.3 วินาที (เฉพาะคำที่ AI จัดได้)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_reference(db: str, vid: str):
    c = sqlite3.connect(db)
    best = None
    for (payload, score) in c.execute("select payload, score from lyrics where video_id=? and timing='word'", (vid,)):
        if best is None or score > best[1]:
            best = (json.loads(payload), score)
    return best[0] if best and best[1] >= 50 else None      # คะแนนต่ำ = น่าจะเป็นเนื้อเพลงคนละเพลง ใช้เป็นเฉลยไม่ได้


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids")
    ap.add_argument("--db", default="")
    ap.add_argument("--audio-dir", default="")
    ap.add_argument("--sweep", default="", help="ลองค่า SNAP_REL_DB หลายค่า เช่น 10,14,18,24")
    ap.add_argument("--dump", action="store_true", help="พิมพ์ความคลาดของทุกบรรทัด")
    args = ap.parse_args()

    import numpy as np

    from app.ai.env import setup_ai_environment
    from app.core.config import ModelsConfig, load_model
    from app.core.paths import get_paths

    paths = get_paths()
    db = args.db or str(paths.db_file)
    cfg, _ = load_model(paths, "models.yaml", ModelsConfig)
    setup_ai_environment(cfg.model_dump())
    import torch  # noqa: F401

    from app.ai.worker import Worker

    events: list[dict] = []
    import queue

    md = cfg.model_dump()
    md.setdefault("analysis", {})["snap_to_voice"] = False     # ทดลองปรับเองด้านล่าง
    w = Worker(queue.Queue(), None, {"models": md, "stems_dir": str(paths.stems_cache_dir)})
    w.emit = lambda t, p: events.append({"type": t, **p})  # type: ignore[assignment]
    w.setup()
    adir = Path(args.audio_dir) if args.audio_dir else Path(paths.cache_dir) / "analysis"

    allerr: list[float] = []
    for vid in args.ids.split(","):
        ref = load_reference(db, vid)
        files = list((adir / vid).glob(f"{vid}.*")) if (adir / vid).exists() else []
        if ref is None or not files:
            print(vid, "ไม่มีเฉลยรายคำ (คะแนนสูง) หรือไม่มีไฟล์เสียง")
            continue
        events.clear()
        lines = [{"words": [x["text"] for x in ln["words"]], "start": None, "end": None, "word_times": None} for ln in ref["lines"]]
        w.job_align_song({"job_id": "eval", "video_id": vid, "audio_path": str(files[0]), "lines": lines,
                          "language": ref.get("language"), "start_hint": 0.0})
        final = next((e for e in events if e.get("kind") == "align_final"), None)
        if final is None:
            print(vid, "ไม่มีผลสุดท้าย", [e for e in events if e["type"] == "failed"][:1])
            continue
        data = final["data"]
        print(f"{vid}: mode={data.get('mode')} coverage={data.get('coverage')}")
        import copy

        import app.ai.pipeline.vocal_activity as va

        voice = np.load(paths.stems_cache_dir / vid / "vocals16k.npy").astype("float32")
        base_lines = copy.deepcopy(data["lines"])

        def evaluate(rel: float | None) -> list[float]:
            if rel is not None:
                va.SNAP_REL_DB = rel
            lines_ = copy.deepcopy(base_lines)
            if rel is not None:
                va.ONSET_DIP_REL_DB, va.ONSET_ON_REL_DB = rel, rel - 2.0
                for ln in lines_:
                    if ln.get("words"):
                        ln["words"] = va.snap_words_to_voice(va.snap_line_onset(va.compact_line_outliers(ln["words"]), voice), voice)
            d2 = {**data, "lines": lines_}
            return pairs_error(d2)

        def pairs_error(data):
            err: list[float] = []
            if data.get("mode") == "match":
                pairs = [(ol["words"], rl["words"], ol["i"]) for rl, ol in zip(ref["lines"], sorted(data["lines"], key=lambda x: x["i"]))
                         if ol.get("resolved")]
            else:   # reconstruct: บรรทัดที่ใช้ข้อความจากเนื้อเพลง (src) เทียบกับคำของเฉลยบรรทัดเดียวกัน
                pairs = []
                for ol in data["lines"]:
                    src = ol.get("src")
                    if not src:
                        continue
                    # เนื้อเพลงที่ซ้ำ (ท่อนฮุก) : AI อาจอ้างบรรทัดแรกที่ข้อความเหมือนกัน แต่เวลาเป็นรอบหลัง -> เทียบกับบรรทัดเฉลยที่ข้อความเหมือนกันและอยู่ใกล้เวลาที่สุด
                    key = [x["text"] for k in src for x in ref["lines"][k]["words"]]
                    cands = [k for k, rl in enumerate(ref["lines"]) if [x["text"] for x in rl["words"]] == key[:len(rl["words"])]]
                    best = None
                    for k in range(len(ref["lines"])):
                        ks = [k + j for j in range(len(src)) if k + j < len(ref["lines"])]
                        ws = [x for kk in ks for x in ref["lines"][kk]["words"]]
                        if [x["text"] for x in ws] == key:
                            d_ = abs(float(ws[0]["start"]) - float(ol["words"][0][0]))
                            if best is None or d_ < best[0]:
                                best = (d_, ws)
                    if best:
                        pairs.append((ol["words"], best[1], ol["i"]))
            for ows, rws, idx in pairs:
                if len(ows) != len(rws):
                    continue
                e_line = [float(s_) - float(rw["start"]) for rw, (s_, e_, c_) in zip(rws, ows)]
                err += e_line
                if args.dump:
                    print(f"  line {idx:3d} ref={rws[0]['start']:7.2f} Δfirst={e_line[0]:+.2f} Δmed={np.median(e_line):+.2f}")
            return err

        for rel in ([None] + [float(x) for x in args.sweep.split(",")] if args.sweep else [None]):
            err = evaluate(rel)
            if args.sweep:
                aa = np.abs(np.array(err)) if err else np.array([9.0])
                print(f"  snap rel={rel}: median={np.median(aa):.3f}s <=0.15s:{(aa <= 0.15).mean():.0%} <=0.3s:{(aa <= 0.3).mean():.0%}")
        err = evaluate(float(args.sweep.split(",")[0]) if args.sweep else None) if False else err
        if not err:
            print("  จัดไม่ได้เลย")
            continue
        a = np.abs(np.array(err))
        allerr += list(a)
        print(f"  words={len(a)} median={np.median(a):.3f}s p90={np.percentile(a, 90):.3f}s "
              f"<=0.15s:{(a <= 0.15).mean():.0%} <=0.3s:{(a <= 0.3).mean():.0%} bias={np.median(err):+.3f}s")
    if allerr:
        a = np.array(allerr)
        print(f"รวม: median={np.median(a):.3f}s <=0.15s:{(a <= 0.15).mean():.0%} <=0.3s:{(a <= 0.3).mean():.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
