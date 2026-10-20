"""เทรนโมเดลเล็กสองตัวจากชุดข้อมูล (CPU ไม่กี่นาที):
  1) จุดตัดบรรทัด: ระหว่างคำ i กับ i+1 "ควรขึ้นบรรทัดใหม่ไหม" (เฉลย = การตัดบรรทัดของมนุษย์ใน NetEase) — ฟีเจอร์: ช่องว่างเวลา วรรคตอน รอยเว้นในเสียงร้อง ข้อความซ้ำ ...
  2) เสียงประสาน/คอรัส: บรรทัดนี้เป็นเสียงประสานไหม (ป้ายอ่อนจากวงเล็บ) — ฟีเจอร์: ความดังเทียบทั้งเพลง ซ้อนกับบรรทัดก่อน ข้อความสะท้อนบรรทัดข้างเคียง ...
ใช้:  .venv\\Scripts\\python scripts\\train_lines.py [--epochs 200]
วัดกับเพลง val เทียบ baseline ง่ายๆ (ช่องว่าง > 0.5 วิ = ตัด) · เก็บ ai_runtime/models/linebreak.pt และ backing.pt (พร้อมค่า mean/std ของฟีเจอร์)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def f1(pred, y):
    import numpy as np

    tp = float(np.sum((pred == 1) & (y == 1)))
    fp = float(np.sum((pred == 1) & (y == 0)))
    fn = float(np.sum((pred == 0) & (y == 1)))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def fit(x, y, epochs: int, hidden: int = 32):
    import numpy as np
    import torch

    mean, std = x.mean(0), x.std(0) + 1e-6
    xt = torch.from_numpy((x - mean) / std).float()
    yt = torch.from_numpy(y).float()
    model = torch.nn.Sequential(torch.nn.Linear(x.shape[1], hidden), torch.nn.ReLU(), torch.nn.Linear(hidden, hidden), torch.nn.ReLU(),
                                torch.nn.Linear(hidden, 1))
    pos = float(max(1.0, yt.sum()))
    w = torch.tensor(float(len(yt) - pos) / pos).clamp(1.0, 20.0)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-3)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=w)
    for _ in range(epochs):
        opt.zero_grad()
        loss = loss_fn(model(xt).squeeze(-1), yt)
        loss.backward()
        opt.step()
    model.eval()
    return model, mean.astype(np.float32), std.astype(np.float32)


def predict(model, mean, std, x, thr: float = 0.5):
    import numpy as np
    import torch

    with torch.no_grad():
        p = torch.sigmoid(model(torch.from_numpy((x - mean) / std).float()).squeeze(-1)).numpy()
    return (p >= thr).astype(np.float32), p


def best_threshold(model, mean, std, x, y):
    import numpy as np

    _, p = predict(model, mean, std, x)
    best = (0.5, -1.0)
    for thr in np.linspace(0.2, 0.9, 15):
        _p, _r, f = f1((p >= thr).astype(np.float32), y)
        if f > best[1]:
            best = (float(thr), f)
    return best[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=250)
    ap.add_argument("--out-dir", default=str(ROOT / "ai_runtime" / "models"))
    args = ap.parse_args()

    from app.ai.env import setup_ai_environment
    from app.core.config import ModelsConfig, load_model
    from app.core.paths import get_paths

    setup_ai_environment(load_model(get_paths(), "models.yaml", ModelsConfig)[0].model_dump())   # torch อยู่ใน ai_runtime/site
    import numpy as np
    import torch

    from app.ai.training.data import iter_songs
    from app.ai.training.linefeat import (BOUNDARY_DIM, LINE_DIM, backing_labels, boundary_features, envelope, line_break_labels,
                                          line_features)

    def build(split: str):
        bx, by, lx, ly = [], [], [], []
        base_gap = []
        for s in iter_songs(split):
            ref = s.ref_lines()
            db, r = envelope(np.asarray(s.vocals(), dtype=np.float32))
            words, labels = line_break_labels(ref)
            if len(labels) < 10:
                continue
            bx.append(boundary_features(words, db, r))
            by.append(labels)
            base_gap.append(np.array([max(0.0, words[i + 1][1] - words[i][2]) for i in range(len(words) - 1)]))
            lines = [{"start": ln["start"], "end": ln["end"], "words": [w[0] for w in ln["words"]]} for ln in ref]
            lx.append(line_features(lines, db, r))
            ly.append(backing_labels(ref))
        cat = lambda a, d: np.concatenate(a) if a else np.zeros((0, d), dtype=np.float32)    # noqa: E731
        return (cat(bx, BOUNDARY_DIM), np.concatenate(by) if by else np.zeros(0, dtype=np.float32),
                cat(lx, LINE_DIM), np.concatenate(ly) if ly else np.zeros(0, dtype=np.float32),
                np.concatenate(base_gap) if base_gap else np.zeros(0))

    tr = build("train")
    va = build("val")
    print(f"train: จุดตัด {len(tr[1])} (ตัดจริง {int(tr[1].sum())}) · บรรทัด {len(tr[3])} (เสียงประสาน {int(tr[3].sum())})")
    print(f"val:   จุดตัด {len(va[1])} · บรรทัด {len(va[3])} (เสียงประสาน {int(va[3].sum())})")
    if len(tr[1]) < 200:
        print("ข้อมูลน้อยเกินไป (ต้องการหลายสิบเพลงขึ้นไป) — รัน scripts/harvest.py ให้ได้เพลงมากกว่านี้ก่อน")
        return 1
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ev = va if len(va[1]) >= 50 else tr
    if ev is tr:
        print("(เพลง val น้อยไป — วัดบนชุด train: ใช้ดูว่าโมเดลเรียนรู้ได้เท่านั้น)")
    # 1) จุดตัดบรรทัด
    model, mean, std = fit(tr[0], tr[1], args.epochs)
    thr = best_threshold(model, mean, std, tr[0], tr[1])
    pred, _ = predict(model, mean, std, ev[0], thr)
    p, r, f = f1(pred, ev[1])
    bp, br, bf = f1((ev[4] > 0.5).astype(np.float32), ev[1])
    print(f"จุดตัดบรรทัด  โมเดล: P={p:.2f} R={r:.2f} F1={f:.2f} (เกณฑ์ {thr:.2f}) · baseline ช่องว่าง>0.5วิ: P={bp:.2f} R={br:.2f} F1={bf:.2f}")
    torch.save({"state": model.state_dict(), "mean": mean, "std": std, "thr": thr, "dim": BOUNDARY_DIM}, out / "linebreak.pt")
    # 2) เสียงประสาน
    if tr[3].sum() >= 20:
        model2, m2, s2 = fit(tr[2], tr[3], args.epochs)
        thr2 = best_threshold(model2, m2, s2, tr[2], tr[3])
        ev2 = ev if ev[3].sum() >= 5 else tr
        pred2, _ = predict(model2, m2, s2, ev2[2], thr2)
        p, r, f = f1(pred2, ev2[3])
        print(f"เสียงประสาน   โมเดล: P={p:.2f} R={r:.2f} F1={f:.2f} (เกณฑ์ {thr2:.2f}) · ตัวอย่างบวก {int(ev2[3].sum())}")
        torch.save({"state": model2.state_dict(), "mean": m2, "std": s2, "thr": thr2, "dim": LINE_DIM}, out / "backing.pt")
    else:
        print("ตัวอย่างเสียงประสานน้อยเกินไป (<20) ข้ามการเทรนตัวตรวจเสียงประสาน")
    print("บันทึกใน", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
