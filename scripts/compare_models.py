"""เทียบน้ำหนักหลายตัวบน "ชุดวัดผลเดียวกัน" ที่ตรึงไว้ — ใช้ตัดสินว่าตัวไหนดีที่สุดจริง

ใช้:  .venv\\Scripts\\python scripts\\compare_models.py [ไฟล์.pt ...]
ไม่ใส่ไฟล์ = เทียบ MMS เดิม + mms_singing*.pt ทุกตัวใน ai_runtime/models
ชุดวัดผลอ่านจาก dataset/val_songs.txt (ไม่มี = สร้างจากเพลง val เฉลยรายคำ 100 เพลงแรก แล้วตรึงไว้)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PIN = ROOT / "dataset" / "val_songs.txt"


def val_set(limit: int = 100):
    from app.ai.training.data import iter_songs

    songs = sorted(iter_songs("val"), key=lambda s: s.meta.get("ref_timing", "word") != "word")
    if PIN.exists():
        want = [x for x in PIN.read_text(encoding="utf-8").split() if x]
        have = {s.id: s for s in songs}
        return [have[i] for i in want if i in have]
    songs = songs[:limit]
    PIN.write_text("\n".join(s.id for s in songs), encoding="utf-8")
    print(f"ตรึงชุดวัดผล {len(songs)} เพลงไว้ที่ {PIN}", flush=True)
    return songs


def main() -> int:
    from eval_aligner import evaluate, load_aligner

    cands: list[str] = sys.argv[1:]
    if not cands:
        cands = [""] + [str(p) for p in sorted((ROOT / "ai_runtime" / "models").glob("mms_singing*.pt"))]
    songs = val_set()
    print(f"ชุดวัดผล {len(songs)} เพลง (เฉลยรายคำ {sum(1 for s in songs if s.meta.get('ref_timing') == 'word')})\n", flush=True)
    rows = []
    for c in cands:
        name = Path(c).name if c else "MMS เดิม (ไม่ fine-tune)"
        try:
            r = evaluate(load_aligner(c or None), songs, verbose=False)
        except Exception as e:  # noqa: BLE001
            print(f"{name}: ผิดพลาด {str(e)[:100]}", flush=True)
            continue
        rows.append((name, r))
        print(f"{name:28s} เริ่มคำ ≤0.15 {r.get('word_le015', 0):.1%} · จบคำ ≤0.15 {r.get('end_le015', 0):.1%} "
              f"· ยาวคำ ≤0.15 {r.get('dur_le015', 0):.1%} · เริ่มบรรทัด ≤0.3 {r.get('le03', 0):.1%}", flush=True)
    if rows:
        def score(r):
            return 2 * r.get("word_le015", 0) + r.get("word_le03", 0) + r.get("end_le015", 0) + r.get("dur_le015", 0)
        best = max(rows, key=lambda x: score(x[1]))
        print(f"\nดีที่สุด: {best[0]} (คะแนนรวม {score(best[1]):.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
