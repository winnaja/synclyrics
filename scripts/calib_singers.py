"""ปรับเกณฑ์ "มีนักร้องกี่คน" (speakers.SPLIT_SIM / MIN_MINOR_FRAC) ด้วยข้อมูลที่มีอยู่

ป้ายคำตอบมาจากชื่อศิลปินของ NetEase: ศิลปินคนเดียว = ร้องเดี่ยว · หลายคน/มี feat. = หลายคน
ป้ายแบบนี้ไม่เป๊ะ (แขกรับเชิญอาจร้องแค่ท่อนเดียว, เพลงเดี่ยวอาจมีเสียงประสาน) — ใช้หาเกณฑ์ที่แยกได้ดีที่สุดเท่านั้น ไม่ใช่ความจริงรายบรรทัด

ใช้:  .venv\\Scripts\\python scripts\\calib_singers.py [--limit 400] [--device cpu]
ทำทีละเพลงแล้วบันทึกต่อท้าย dataset/singers_calib.jsonl (รันซ้ำทำต่อจากเดิม) · --report อย่างเดียว = ไม่คำนวณใหม่ แค่สรุปผล
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "dataset" / "singers_calib.jsonl"
FEAT = re.compile(r"\b(feat\.?|ft\.?|with)\b|&|,|、|\+|\bduet\b|/", re.I)


def label_of(meta: dict) -> str | None:
    """-> "multi" | "solo" | None (ไม่ชัด)  จากชื่อศิลปิน/ชื่อเพลง"""
    artist = (meta.get("artist") or "").strip()
    title = (meta.get("title") or "").strip()
    if not artist:
        return None
    if FEAT.search(artist) or FEAT.search(title):
        return "multi"
    return "solo"


def done_ids() -> set[str]:
    out: set[str] = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.add(json.loads(line)["id"])
            except (ValueError, KeyError):
                continue
    return out


def report() -> None:
    """กวาดหาเกณฑ์ที่ทายถูกมากที่สุด (ถ่วงให้สองฝั่งมีน้ำหนักเท่ากัน เพราะจำนวนไม่เท่ากัน)"""
    import numpy as np

    rows = []
    for line in OUT.read_text(encoding="utf-8", errors="replace").splitlines() if OUT.exists() else []:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "csim" in d:
            rows.append(d)
    if not rows:
        print("ยังไม่มีข้อมูล — รันโดยไม่ใส่ --report ก่อน")
        return
    solo = [r for r in rows if r["label"] == "solo"]
    multi = [r for r in rows if r["label"] == "multi"]
    print(f"เพลงที่วัดแล้ว {len(rows)} (เดี่ยว {len(solo)} · หลายคน {len(multi)})")
    for name, g in (("เดี่ยว", solo), ("หลายคน", multi)):
        if g:
            c = np.array([r["csim"] for r in g])
            print(f"  {name}: ความคล้ายสองกลุ่ม (csim) มัธยฐาน {np.median(c):.3f} · ช่วง 10-90% {np.percentile(c, 10):.3f}-{np.percentile(c, 90):.3f}")
    if not solo or not multi:
        print("ยังมีฝั่งเดียว — เก็บเพิ่มก่อนจึงจะหาเกณฑ์ได้")
        return
    best = None
    for sim in np.arange(0.30, 0.86, 0.01):
        for frac in (0.08, 0.10, 0.12, 0.15, 0.20, 0.25):
            def pred(r, sim=sim, frac=frac):
                return r["csim"] < sim and r["minor_frac"] >= frac
            tpr = sum(pred(r) for r in multi) / len(multi)          # จับดูเอ็ตได้
            tnr = sum(not pred(r) for r in solo) / len(solo)        # ไม่ตีเพลงเดี่ยวเป็นดูเอ็ต
            bal = (tpr + tnr) / 2
            if best is None or bal > best[0]:
                best = (bal, float(sim), frac, tpr, tnr)
    bal, sim, frac, tpr, tnr = best
    cur_t = sum(r["csim"] < 0.50 and r["minor_frac"] >= 0.12 for r in multi) / len(multi)
    cur_n = sum(not (r["csim"] < 0.50 and r["minor_frac"] >= 0.12) for r in solo) / len(solo)
    print(f"\nเกณฑ์ปัจจุบัน  SPLIT_SIM 0.50 · MIN_MINOR_FRAC 0.12 -> จับหลายคนได้ {cur_t:.0%} · เพลงเดี่ยวไม่ถูกตีผิด {cur_n:.0%} (เฉลี่ย {(cur_t + cur_n) / 2:.0%})")
    print(f"เกณฑ์ที่ดีที่สุด SPLIT_SIM {sim:.2f} · MIN_MINOR_FRAC {frac} -> จับหลายคนได้ {tpr:.0%} · เพลงเดี่ยวไม่ถูกตีผิด {tnr:.0%} (เฉลี่ย {bal:.0%})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--device", default="cpu", help="cpu = ไม่แย่งการ์ดจอกับการเทรน (ช้ากว่าแต่รันพร้อมกันได้)")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.report:
        report()
        return 0

    from app.ai.env import setup_ai_environment
    from app.core.config import ModelsConfig, load_model
    from app.core.paths import get_paths

    paths = get_paths()
    cfg, _ = load_model(paths, "models.yaml", ModelsConfig)
    setup_ai_environment(cfg.model_dump())
    import numpy as np

    from app.ai.pipeline import speakers
    from app.ai.training.data import iter_songs

    enc = speakers.load_encoder(paths.models_dir, args.device)
    skip = done_ids()
    todo = []
    for s in iter_songs(None):
        if s.id in skip:
            continue
        lab = label_of(s.meta)
        if lab:
            todo.append((s, lab))
    # สลับฝั่งให้ได้ทั้งเดี่ยวและหลายคนตั้งแต่ต้น (หยุดกลางทางก็ยังสรุปผลได้)
    solo = [x for x in todo if x[1] == "solo"]
    multi = [x for x in todo if x[1] == "multi"]
    todo = [x for pair in zip(solo, multi) for x in pair][:args.limit] or (solo + multi)[:args.limit]
    print(f"จะวัด {len(todo)} เพลง (ทำไปแล้ว {len(skip)}) · อุปกรณ์ {args.device}", flush=True)
    for n, (s, lab) in enumerate(todo, 1):
        try:
            ref = s.ref_lines()
            spans = [(ln["start"], ln["end"]) for ln in ref if ln["end"] > ln["start"]]
            if len(spans) < speakers.MIN_LINES:
                continue
            v = np.asarray(s.vocals(), dtype=np.float32)
            embs = speakers.line_embeddings(enc, v, spans)
            idx = [k for k, e in enumerate(embs) if e is not None]
            if len(idx) < speakers.MIN_LINES:
                continue
            mat = np.stack([embs[k] for k in idx])
            labels, csim = speakers.cluster_two(mat)
            minor = int(min(np.sum(labels == 0), np.sum(labels == 1)))
            rec = {"id": s.id, "label": lab, "artist": s.meta.get("artist"), "title": s.meta.get("title"),
                   "csim": round(float(csim), 4), "minor_frac": round(minor / len(idx), 4), "lines": len(idx)}
        except Exception as e:  # noqa: BLE001
            rec = {"id": s.id, "label": lab, "error": str(e)[:120]}
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if n % 10 == 0:
            print(f"  {n}/{len(todo)} เพลง", flush=True)
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
