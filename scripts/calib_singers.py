"""ปรับ/ตรวจตัวนับจำนวนนักร้อง (speakers.py) ด้วยข้อมูลที่มีอยู่

ป้ายคำตอบมาจากชื่อศิลปินของ NetEase: ศิลปินคนเดียว = ร้องเดี่ยว · หลายคน/มี feat. = หลายคน
ป้ายแบบนี้ไม่เป๊ะ (แขกรับเชิญอาจร้องแค่ท่อนเดียว, เพลงเดี่ยวอาจมีเสียงประสาน) — ใช้เทียบว่าวิธีไหนแยกได้ดีกว่ากันเท่านั้น

  --embed   คำนวณ "ลายเสียงรายบรรทัด" (ECAPA) เก็บเป็น dataset/songs/<id>/spk192.npy (มีไฟล์แล้วข้าม -> รันซ้ำทำต่อได้)
  --report  อ่านลายเสียงที่เก็บไว้ คำนวณคุณสมบัติหลายแบบ แล้วบอกว่าอันไหนแยกเดี่ยว/หลายคนได้จริง (AUC) + เกณฑ์ที่ดีที่สุด

เก็บ "ลายเสียง" แทนผลสรุป เพราะคิดคุณสมบัติใหม่ได้โดยไม่ต้องรัน ECAPA ซ้ำ (ECAPA บน CPU ช้าราว 20-40 วิ/เพลง)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FEAT = re.compile(r"\b(feat\.?|ft\.?|with)\b|&|,|、|\+|\bduet\b|/", re.I)
EMB_NAME = "spk192.npy"          # (บรรทัด, 192) ลายเสียงต่อบรรทัด
DUR_NAME = "spk_dur.npy"         # (บรรทัด,) ความยาวบรรทัดเป็นวินาที


def label_of(meta: dict) -> str | None:
    """-> "multi" | "solo" | None (ไม่ชัด)  จากชื่อศิลปิน/ชื่อเพลง"""
    artist = (meta.get("artist") or "").strip()
    title = (meta.get("title") or "").strip()
    if not artist:
        return None
    return "multi" if (FEAT.search(artist) or FEAT.search(title)) else "solo"


def embed_all(limit: int, device: str) -> int:
    from app.ai.env import setup_ai_environment
    from app.core.config import ModelsConfig, load_model
    from app.core.paths import get_paths

    paths = get_paths()
    cfg, _ = load_model(paths, "models.yaml", ModelsConfig)
    setup_ai_environment(cfg.model_dump())
    import numpy as np

    from app.ai.pipeline import speakers
    from app.ai.training.data import iter_songs

    enc = speakers.load_encoder(paths.models_dir, device)
    todo = []
    for s in iter_songs(None):
        if (s.dir / EMB_NAME).exists() or not label_of(s.meta):
            continue
        todo.append((s, label_of(s.meta)))
    solo = [x for x in todo if x[1] == "solo"]
    multi = [x for x in todo if x[1] == "multi"]
    todo = [x for pair in zip(solo, multi) for x in pair][:limit] or (solo + multi)[:limit]
    print(f"จะคำนวณลายเสียง {len(todo)} เพลง · อุปกรณ์ {device}", flush=True)
    n_ok = 0
    for n, (s, _lab) in enumerate(todo, 1):
        try:
            spans = [(ln["start"], ln["end"]) for ln in s.ref_lines() if ln["end"] > ln["start"]]
            if len(spans) < speakers.MIN_LINES:
                continue
            v = np.asarray(s.vocals(), dtype=np.float32)
            embs = speakers.line_embeddings(enc, v, spans)
            keep = [(e, spans[k][1] - spans[k][0]) for k, e in enumerate(embs) if e is not None]
            if len(keep) < speakers.MIN_LINES:
                continue
            np.save(s.dir / EMB_NAME, np.stack([e for e, _ in keep]).astype(np.float32))
            np.save(s.dir / DUR_NAME, np.array([d for _, d in keep], dtype=np.float32))
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  {s.id}: ผิดพลาด {str(e)[:90]}", flush=True)
        if n % 10 == 0:
            print(f"  {n}/{len(todo)} เพลง (สำเร็จ {n_ok})", flush=True)
    print(f"เสร็จ: เก็บลายเสียงได้ {n_ok} เพลง", flush=True)
    return 0


def features(embs, durs) -> dict:
    """คุณสมบัติของเพลงหนึ่งเพลงจากลายเสียงรายบรรทัด

    แนวคิดสำคัญ: เพลงคู่จริงจะ "สลับกันเป็นท่อน" (ท่อนหนึ่งคนนี้ อีกท่อนอีกคน) ส่วนเพลงเดี่ยวที่ถูกจัดกลุ่มผิด
    (เพราะเสียงสูง/ต่ำต่างกัน) จะสลับไปมาถี่ๆ ไม่เป็นท่อน — ความต่อเนื่องของกลุ่มจึงน่าจะแยกได้ดีกว่าความคล้ายเฉยๆ
    """
    import numpy as np

    from app.ai.pipeline import speakers

    labels, csim = speakers.cluster_two(embs)
    n = len(labels)
    minor = int(min((labels == 0).sum(), (labels == 1).sum()))
    runs, cur = [], 1
    for i in range(1, n):
        if labels[i] == labels[i - 1]:
            cur += 1
        else:
            runs.append(cur)
            cur = 1
    runs.append(cur)
    sim = embs @ embs.T
    same = np.array([[labels[i] == labels[j] for j in range(n)] for i in range(n)])
    off = ~np.eye(n, dtype=bool)
    intra = float(sim[same & off].mean()) if (same & off).any() else 1.0
    inter = float(sim[~same].mean()) if (~same).any() else 1.0
    return {"lines": n, "csim": round(float(csim), 4), "minor_frac": round(minor / n, 4),
            "switch_rate": round((len(runs) - 1) / max(1, n - 1), 4),      # ต่ำ = เป็นท่อนๆ (ดูเอ็ต) · สูง = สลับถี่ (น่าจะเดี่ยว)
            "max_run_frac": round(max(runs) / n, 4), "mean_run": round(float(np.mean(runs)), 3),
            "sep": round(intra - inter, 4),                                # กลุ่มแน่นแค่ไหนเทียบกับข้ามกลุ่ม
            "minor_dur_frac": round(float(durs[labels == (0 if (labels == 0).sum() < (labels == 1).sum() else 1)].sum() / max(1e-9, durs.sum())), 4)}


def auc(pos, neg) -> float:
    """พื้นที่ใต้กราฟ ROC — 0.5 = แยกไม่ได้เลย, 1.0 = แยกขาด (ใช้ดูว่าคุณสมบัติไหนมีประโยชน์)"""
    import numpy as np

    p, q = np.asarray(pos), np.asarray(neg)
    if not len(p) or not len(q):
        return 0.5
    return float((p[:, None] > q[None, :]).mean() + 0.5 * (p[:, None] == q[None, :]).mean())


def report(min_lines: int) -> None:
    import numpy as np

    from app.ai.training.data import iter_songs

    rows = []
    for s in iter_songs(None):
        f = s.dir / EMB_NAME
        if not f.exists():
            continue
        lab = label_of(s.meta)
        if not lab:
            continue
        embs = np.load(f)
        durs = np.load(s.dir / DUR_NAME)
        if len(embs) < min_lines:
            continue
        rows.append({"id": s.id, "label": lab, "artist": s.meta.get("artist"), **features(embs, durs)})
    if not rows:
        print("ยังไม่มีลายเสียงที่เก็บไว้ — รัน --embed ก่อน")
        return
    (ROOT / "dataset" / "singers_features.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    solo = [r for r in rows if r["label"] == "solo"]
    multi = [r for r in rows if r["label"] == "multi"]
    print(f"เพลงที่วัดแล้ว {len(rows)} (เดี่ยว {len(solo)} · หลายคน {len(multi)}) · อย่างน้อย {min_lines} บรรทัด")
    if not solo or not multi:
        print("ยังมีฝั่งเดียว — เก็บเพิ่มก่อน")
        return
    print("\nคุณสมบัติไหนแยก เดี่ยว/หลายคน ได้จริง (AUC 0.5 = แยกไม่ได้เลย):")
    keys = ["csim", "minor_frac", "switch_rate", "max_run_frac", "mean_run", "sep", "minor_dur_frac"]
    scored = []
    for k in keys:
        a = auc([r[k] for r in multi], [r[k] for r in solo])
        scored.append((max(a, 1 - a), k, a))
        print(f"  {k:15s} AUC {a:.3f}{'  (ยิ่งน้อยยิ่งเป็นหลายคน)' if a < 0.5 else ''}"
              f"   เดี่ยว {np.median([r[k] for r in solo]):.3f} | หลายคน {np.median([r[k] for r in multi]):.3f}")
    scored.sort(reverse=True)
    print(f"\nดีที่สุด: {scored[0][1]} (AUC {scored[0][2]:.3f})")

    def bal(pred) -> tuple[float, float, float]:
        tpr = sum(pred(r) for r in multi) / len(multi)
        tnr = sum(not pred(r) for r in solo) / len(solo)
        return (tpr + tnr) / 2, tpr, tnr
    cur = bal(lambda r: r["csim"] < 0.50 and r["minor_frac"] >= 0.12)
    print(f"\nเกณฑ์ปัจจุบัน (csim<0.50 และ minor_frac>=0.12): เฉลี่ย {cur[0]:.0%} (จับหลายคนได้ {cur[1]:.0%} · เพลงเดี่ยวไม่ถูกตีผิด {cur[2]:.0%})")
    best = None
    for sim in np.arange(0.30, 0.90, 0.02):
        for sw in (1.1, 0.8, 0.7, 0.6, 0.5, 0.4):
            for frac in (0.08, 0.12, 0.18, 0.25):
                r3 = bal(lambda r, s=sim, w=sw, f=frac: r["csim"] < s and r["switch_rate"] <= w and r["minor_frac"] >= f)
                if best is None or r3[0] > best[0][0]:
                    best = (r3, float(sim), sw, frac)
    (b, tpr, tnr), sim, sw, frac = best
    print(f"เกณฑ์ที่ดีที่สุด (csim<{sim:.2f} และ switch_rate<={sw} และ minor_frac>={frac}): เฉลี่ย {b:.0%} (จับหลายคนได้ {tpr:.0%} · เพลงเดี่ยวไม่ถูกตีผิด {tnr:.0%})")
    if b < 0.62:
        print("\n>> สรุป: วิธีนี้ (ลายเสียง ECAPA + จัดกลุ่ม 2 กลุ่ม) แยกเดี่ยว/หลายคนแทบไม่ได้ ปรับเกณฑ์ช่วยไม่ได้")
        print("   ECAPA ถูกเทรนกับ 'เสียงพูด' ไม่ใช่ 'เสียงร้อง' — คนเดียวร้องเสียงสูง/ต่ำวัดได้ต่างกันมาก")
        print("   ทางที่เหลือ: ปิดการแยกซ้าย/ขวาอัตโนมัติ หรือหาป้ายจริง (ผู้ใช้ระบุเพลงคู่/เดี่ยว) แล้วเทรนตัวแยกเอง")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--min-lines", type=int, default=12)
    ap.add_argument("--device", default="cpu", help="cpu = ไม่แย่งการ์ดจอกับการเทรน")
    args = ap.parse_args()
    if args.embed:
        return embed_all(args.limit, args.device)
    report(args.min_lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
