"""วัดความแม่นของตัวแยก "เสียงประสาน/คอรัส" (vocal_activity.classify_backing)

คำตอบที่ใช้วัด: เฉลยจากเว็บมักใส่วงเล็บกำกับเสียงประสาน/ad-lib เช่น บรรทัดที่อยู่ในวงเล็บทั้งบรรทัด
- บวก (น่าจะเป็นเสียงประสาน) = บรรทัดที่อยู่ในวงเล็บทั้งบรรทัด
- ลบ (น่าจะเป็นเสียงร้องหลัก)  = บรรทัดที่ไม่มีวงเล็บเลย **ในเพลงที่ใช้วงเล็บ** (เพลงที่ไม่เคยใช้ บอกอะไรไม่ได้)
ตัดบรรทัดกำกวมทิ้ง: (x2), ตัวเลขล้วน, วงเล็บยาวผิดปกติ (มักเป็นคำแปล)

ป้ายแบบนี้ไม่เป๊ะ — ผู้ถอดเนื้อแต่ละคนใส่วงเล็บไม่เหมือนกัน ใช้เทียบว่า "วิธีไหนดีกว่ากัน" บนชุดเดียวกันเท่านั้น
ห้ามอ้างเป็นความแม่นสัมบูรณ์

ใช้:  .venv\\Scripts\\python scripts\\eval_backing.py [--limit 150]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PAREN = re.compile(r"[(（]([^)）]{1,60})[)）]")
SKIP = re.compile(r"^\s*(x\s*\d+|\d+|[ivxlc]+)\s*$", re.I)      # (x2) / (3) / (ii) = คำกำกับ ไม่ใช่เสียงร้อง


def label_line(text: str) -> bool | None:
    """True = น่าจะเป็นเสียงประสาน · False = น่าจะเป็นเสียงร้องหลัก · None = ตัดสินไม่ได้ ไม่เอามาวัด"""
    t = text.strip()
    if not t:
        return None
    m = PAREN.fullmatch(t)
    if m:                                   # ทั้งบรรทัดอยู่ในวงเล็บ
        inner = m.group(1).strip()
        if SKIP.match(inner) or len(inner) > 40:
            return None
        return True
    if PAREN.search(t):                     # มีวงเล็บปนอยู่กลางบรรทัด -> กำกวม ไม่เอามาวัด
        return None
    return False


FEAT = ROOT / "dataset" / "backing_features.jsonl"


def dump_features(limit: int) -> int:
    """ดึงตัวเลขของแต่ละบรรทัดที่มีคำตอบ เก็บไว้กวาดหาเกณฑ์ได้เร็วโดยไม่ต้องอ่านเสียงซ้ำ

    เก็บเฉพาะตัวเลขกับป้าย ไม่เก็บข้อความเนื้อเพลง
    """
    import json

    import numpy as np

    from app.ai.pipeline import vocal_activity as va
    from app.ai.training.data import iter_songs

    rows = []
    songs = 0
    for s in iter_songs(None):
        ref = s.meta.get("ref") or []
        if len(ref) < 8:
            continue
        texts = ["".join(w[0] for w in ln["words"]) for ln in ref]
        labels = [label_line(t) for t in texts]
        if not any(x is True for x in labels):
            continue
        off = float(s.meta.get("ref_offset_s") or 0.0)
        try:
            v = np.asarray(s.vocals(), dtype=np.float32)
            db = va.frame_db(v, 16000, va.SNAP_FRAME_S)
        except Exception:  # noqa: BLE001
            continue
        if len(db) == 0:
            continue
        levels = []
        for ln in ref:
            i0 = int((ln["start"] + off) / va.SNAP_FRAME_S)
            i1 = int((ln["end"] + off) / va.SNAP_FRAME_S)
            seg = db[max(0, i0):min(len(db), i1)]
            seg = seg[seg > va.ABS_FLOOR_DB]
            levels.append(float(np.percentile(seg, 75)) if len(seg) >= 5 else None)
        known = [x for x in levels if x is not None]
        if len(known) < 8:
            continue
        gref = float(np.median(known))
        norm = [va._norm_text([w[0] for w in ln["words"]]) for ln in ref]
        for i, lab in enumerate(labels):
            if lab is None or levels[i] is None:
                continue
            # ค่ากลางเฉพาะแถวๆ นี้ (±8 บรรทัด) — ท่อนที่ร้องเบาทั้งท่อนจะได้ไม่ถูกตีเป็นประสานยกท่อน
            near = [levels[j] for j in range(max(0, i - 8), min(len(levels), i + 9))
                    if levels[j] is not None and j != i]
            lref = float(np.median(near)) if len(near) >= 4 else gref
            echo = False
            for j in (i - 1, i + 1):
                if 0 <= j < len(ref) and len(norm[i]) >= 3 and norm[i] and norm[i] in norm[j] and norm[i] != norm[j]:
                    gap = (ref[j]["start"] - ref[i]["end"]) if j > i else (ref[i]["start"] - ref[j]["end"])
                    if gap < 1.5:
                        echo = True
            rows.append({"label": bool(lab), "g": round(gref - levels[i], 2), "l": round(lref - levels[i], 2),
                         "echo": echo, "nw": len(ref[i]["words"]),
                         "dur": round(ref[i]["end"] - ref[i]["start"], 2)})
        songs += 1
        if songs >= limit:
            break
    FEAT.write_text(chr(10).join(json.dumps(r) for r in rows), encoding="utf-8")
    print(f"เก็บตัวเลขจาก {songs} เพลง · {len(rows)} บรรทัด -> {FEAT}")
    return 0


def tune() -> int:
    import json

    import numpy as np

    rows = [json.loads(x) for x in FEAT.read_text(encoding="utf-8").splitlines() if x]
    pos = [r for r in rows if r["label"]]
    neg = [r for r in rows if not r["label"]]
    print(f"บรรทัดที่มีคำตอบ: เสียงประสาน {len(pos)} · เสียงร้องหลัก {len(neg)}")
    if not pos or not neg:
        return 1
    for k, name in (("g", "เบากว่าค่ากลางทั้งเพลง"), ("l", "เบากว่าค่ากลางแถวนั้น"), ("nw", "จำนวนคำ"), ("dur", "ความยาวบรรทัด")):
        a, bb = np.array([r[k] for r in pos], float), np.array([r[k] for r in neg], float)
        auc = float((a[:, None] > bb[None, :]).mean() + 0.5 * (a[:, None] == bb[None, :]).mean())
        print(f"  {name:24s} AUC {auc:.3f} · ประสาน {np.median(a):6.2f} | หลัก {np.median(bb):6.2f}")

    def rate(pred):
        tpr = sum(pred(r) for r in pos) / len(pos)
        tnr = sum(not pred(r) for r in neg) / len(neg)
        return (tpr + tnr) / 2, tpr, tnr
    cur = rate(lambda r: r["nw"] <= 6 and (r["g"] >= 6.0 or (r["echo"] and r["g"] >= 3.0)))
    print(f"เกณฑ์ปัจจุบัน: เฉลี่ย {cur[0]:.0%} (จับได้ {cur[1]:.0%} · ไม่ตีผิด {cur[2]:.0%})")
    # เสียงร้องหลักถูกตีเป็นตัวเล็กผิดๆ เห็นชัดและกวนกว่าการพลาดเสียงประสาน จึงคุมฝั่งนั้นไว้ก่อน
    for floor in (0.98, 0.95, 0.93, 0.90, 0.85):
        best = None
        for thr in np.arange(0.0, 8.1, 0.25):
            for dur_max in (99.0, 4.0, 3.0, 2.5):
                for eb in (thr, thr - 1.0, thr - 2.0, thr - 3.0):
                    def pred(x, t=thr, d=dur_max, e=eb):
                        return x["dur"] <= d and (x["l"] >= t or (x["echo"] and x["l"] >= e))
                    r = rate(pred)
                    if r[2] >= floor and (best is None or r[1] > best[0][1]):
                        best = (r, float(thr), float(dur_max), float(eb))
        if best is None:
            print(f"  คุมไม่ตีผิด >= {floor:.0%}: หาเกณฑ์ไม่ได้")
            continue
        (bal, tpr, tnr), thr, dmax, eb = best
        dtxt = "ไม่จำกัด" if dmax > 50 else f"<= {dmax} วิ"
        print(f"  คุมไม่ตีผิด >= {floor:.0%}: เบากว่าแถวนั้น >= {thr} dB · ยาวบรรทัด {dtxt} · สะท้อน >= {eb} dB"
              f"  -> จับได้ {tpr:.0%} · ไม่ตีผิด {tnr:.0%} · เฉลี่ย {bal:.0%}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=150, help="จำนวนเพลงที่ใช้วัด")
    ap.add_argument("--skip", type=int, default=0, help="ข้ามเพลงที่เข้าเกณฑ์กี่เพลงแรก (ใช้วัดกับเพลงที่ไม่ได้ใช้ตั้งค่า)")
    ap.add_argument("--dump", action="store_true", help="ดึงตัวเลขเก็บไว้ก่อน")
    ap.add_argument("--tune", action="store_true", help="กวาดหาเกณฑ์ที่ดีที่สุดจากตัวเลขที่เก็บไว้")
    args = ap.parse_args()
    if args.dump:
        return dump_features(args.limit)
    if args.tune:
        return tune()

    import numpy as np

    from app.ai.pipeline.vocal_activity import classify_backing
    from app.ai.training.data import iter_songs

    tp = fp = tn = fn = 0
    songs = skipped = 0
    for s in iter_songs(None):
        ref = s.meta.get("ref") or []
        if len(ref) < 8:
            continue
        texts = ["".join(w[0] for w in ln["words"]) for ln in ref]
        labels = [label_line(t) for t in texts]
        if not any(l is True for l in labels):      # เพลงนี้ไม่ใช้วงเล็บ -> ไม่มีคำตอบให้วัด
            continue
        off = float(s.meta.get("ref_offset_s") or 0.0)
        lines = [{"start": ln["start"] + off, "end": ln["end"] + off,
                  "words": [w[0] for w in ln["words"]]} for ln in ref]
        try:
            v = np.asarray(s.vocals(), dtype=np.float32)
            pred = classify_backing(lines, v)
        except Exception as e:  # noqa: BLE001
            print(f"  {s.id}: ผิดพลาด {str(e)[:70]}")
            skipped += 1
            continue
        songs += 1
        if songs <= args.skip:
            continue
        for lab, p in zip(labels, pred):
            if lab is None:
                continue
            if lab and p:
                tp += 1
            elif lab and not p:
                fn += 1
            elif not lab and p:
                fp += 1
            else:
                tn += 1
        if songs >= args.limit + args.skip:
            break

    pos, neg = tp + fn, tn + fp
    print(f"เพลงที่ใช้วัด {songs} (ข้ามเพราะผิดพลาด {skipped})")
    print(f"บรรทัดที่มีคำตอบ: เสียงประสาน {pos} · เสียงร้องหลัก {neg}")
    if not pos or not neg:
        print("ข้อมูลไม่พอ")
        return 1
    recall = tp / pos
    spec = tn / neg
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    print(f"\nจับเสียงประสานได้        {recall:.0%}  ({tp}/{pos})")
    print(f"เสียงร้องหลักไม่ถูกตีผิด  {spec:.0%}  ({tn}/{neg})")
    print(f"ที่ทายว่าเป็นประสาน ถูกจริง {prec:.0%}  ({tp}/{tp + fp})")
    print(f"เฉลี่ยถ่วงให้สองฝั่งเท่ากัน {(recall + spec) / 2:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
