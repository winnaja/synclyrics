"""Fine-tune ตัวจัดเวลา (MMS_FA / wav2vec2 CTC) ให้เก่งกับ "เสียงร้อง" — เทรนด้วยเสียงร้อง + ข้อความเนื้อเพลง (CTC loss ไม่ต้องใช้เวลารายคำ)
แล้ววัดกับเฉลยรายคำบนเพลง val ทุกๆ --val-every ก้าว เก็บชุดน้ำหนักที่ดีที่สุดไว้ใช้ (ตัวเลือก align.finetuned ใน models.yaml)

ใช้ (ปิดแอปก่อน — ใช้การ์ดจอ 8 GB):
  .venv\\Scripts\\python scripts\\train_ctc.py --epochs 3
ตัวเลือกสำคัญ: --freeze-layers 8 (ล็อก CNN + transformer ชั้นล่าง 8 จาก 24) · --batch 4 · --lr 2e-5 · --max-steps · --out ai_runtime/models/mms_singing.pt
ข้อมูล: dataset/songs/ (scripts/harvest.py) เฉพาะเพลงที่ไม่ติดธง suspect · แบ่ง train/val ตามแฮชรหัสเพลง
"""

from __future__ import annotations

import argparse
import json
import queue
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def build_examples(songs, mms, max_clip_s: float):
    """-> [(song, start_s, end_s, target_ids)] ข้ามคลิปที่แปลงเป็นอักษรละตินไม่ได้/สั้นเกิน"""
    from app.ai.pipeline import align
    from app.ai.training.data import make_clips

    d = mms["dict"]
    ex = []
    for s in songs:
        for c in make_clips(s, max_s=max_clip_s):
            ids = [d[ch] for w in c["words"] for ch in align.romanize_word(w, s.language, mms["uroman"]) if ch in d]
            frames = (c["end"] - c["start"]) * 50
            if c["end"] - c["start"] > max_clip_s + 1.0:        # บรรทัดเดียวยาวผิดปกติ (เฉลยระดับบรรทัด/ช่วงดนตรี) กิน VRAM เกินและเรียนรู้ไม่ได้
                continue
            if len(ids) < 6 or len(ids) > frames * 0.8:
                continue
            ex.append((s, c["start"], c["end"], ids))
    return ex


def batches(examples, batch: int, shuffle: bool):
    import numpy as np
    import torch

    order = list(range(len(examples)))
    if shuffle:
        random.shuffle(order)
    for b in range(0, len(order) - batch + 1, batch):
        items = [examples[i] for i in order[b:b + batch]]
        waves, lens, targets, tlens = [], [], [], []
        for s, t0, t1, ids in items:
            v = np.asarray(s.vocals()[int(t0 * 16000):int(t1 * 16000)], dtype=np.float32)
            if len(v) < 16000:
                break
            v = v / (np.abs(v).max() + 1e-6) * 0.9
            waves.append(torch.from_numpy(v))
            lens.append(len(v))
            targets.append(torch.tensor(ids, dtype=torch.long))
            tlens.append(len(ids))
        else:
            maxlen = max(lens)
            wav = torch.zeros(len(waves), maxlen)
            for i, w in enumerate(waves):
                wav[i, :len(w)] = w
            yield wav, torch.tensor(lens), torch.cat(targets), torch.tensor(tlens)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--freeze-layers", type=int, default=8)
    ap.add_argument("--max-clip-s", type=float, default=14.0)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--val-every", type=int, default=400)
    ap.add_argument("--val-songs", type=int, default=0, help="0 = ใช้เพลง val ทั้งหมด (วัดเวลาเริ่มบรรทัดทุกเพลง + เริ่มคำของเพลงเฉลยรายคำ)")
    ap.add_argument("--max-songs", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "ai_runtime" / "models" / "mms_singing.pt"))
    args = ap.parse_args()

    from app.ai.env import setup_ai_environment
    from app.core.config import ModelsConfig, load_model
    from app.core.dataset import DATASET_DIR
    from app.core.paths import get_paths

    paths = get_paths()
    cfg, _ = load_model(paths, "models.yaml", ModelsConfig)
    md = cfg.model_dump()
    setup_ai_environment(md)
    global torch
    import torch
    import torch.nn.functional as F

    from app.ai.pipeline import align
    from app.ai.training.data import iter_songs
    from eval_aligner import evaluate

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    mms = align.load_model({"finetuned": ""}, dev)          # เริ่มจาก MMS เดิมเสมอ
    model = mms["model"]
    train_songs = list(iter_songs("train"))
    val_songs = list(iter_songs("val"))
    if args.val_songs:
        val_songs = val_songs[:args.val_songs]
    if args.max_songs:
        train_songs = train_songs[:args.max_songs]
    if not val_songs and train_songs:
        print("(ยังไม่มีเพลง val — ใช้เพลงแรกของ train วัดแทน: ใช้ทดสอบการรันเท่านั้น)", flush=True)
        val_songs = train_songs[:1]
    examples = build_examples(train_songs, mms, args.max_clip_s)
    print(f"train: {len(train_songs)} เพลง {len(examples)} คลิป · val: {len(val_songs)} เพลง · อุปกรณ์ {dev}", flush=True)
    if not examples:
        print("ไม่มีข้อมูลสอน — รัน scripts/harvest.py ก่อน")
        return 1

    # ล็อกส่วนล่าง: CNN ตัวดึงฟีเจอร์ + transformer ชั้นแรก N ชั้น · เทรนชั้นบน + หัว CTC
    for p in model.parameters():
        p.requires_grad = False
    net = model.model                    # _Wav2Vec2Model ห่อ Wav2Vec2Model จริงไว้ที่ .model
    layers = net.encoder.transformer.layers
    for layer in list(layers)[args.freeze_layers:]:
        for p in layer.parameters():
            p.requires_grad = True
    for p in net.aux.parameters():
        p.requires_grad = True
    params = [p for p in model.parameters() if p.requires_grad]
    print(f"พารามิเตอร์ที่เทรน: {sum(p.numel() for p in params) / 1e6:.0f}M จาก {sum(p.numel() for p in model.parameters()) / 1e6:.0f}M", flush=True)
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.01)
    total_steps = args.max_steps or args.epochs * (len(examples) // args.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 150) * max(0.05, 1.0 - s / max(1, total_steps)))

    def val() -> dict:
        model.eval()
        torch.cuda.empty_cache()
        try:
            with torch.inference_mode():
                return evaluate(mms, val_songs, verbose=False) if val_songs else {"songs": 0}
        except torch.OutOfMemoryError:
            torch.cuda.empty_cache()
            print("  (วัดผลรอบนี้ VRAM ไม่พอ — ข้าม)", flush=True)
            return {"songs": 0}

    base = val()
    print("ก่อนเทรน (val):", base, flush=True)
    best = (base.get("median", 9.0), base.get("le03", 0.0)) if base.get("songs") else (9.0, 0.0)
    log = DATASET_DIR / "train_log.jsonl"
    step = 0
    t0 = time.time()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for ep in range(args.epochs):
        for wav, lens, targets, tlens in batches(examples, args.batch, True):
            model.train()
            try:
                wav = wav.to(dev)
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=dev == "cuda"):
                    logits, olens = net(wav, lens.to(dev))
                lp = F.log_softmax(logits.float(), dim=-1).transpose(0, 1)
                loss = F.ctc_loss(lp, targets.to(dev), olens, tlens.to(dev), blank=0, zero_infinity=True)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 5.0)
                opt.step()
            except torch.OutOfMemoryError:       # ก้อนเดียวใหญ่เกิน VRAM: ข้ามก้อนนั้น ไม่ให้ทั้งการเทรนล้ม
                opt.zero_grad(set_to_none=True)
                logits = lp = loss = None
                torch.cuda.empty_cache()
                print(f"  (ข้ามก้อนที่ VRAM ไม่พอ: {tuple(wav.shape)})", flush=True)
                continue
            sched.step()
            step += 1
            if step % 20 == 0:
                print(f"  ep{ep} step {step}/{total_steps} loss={loss.item():.3f} lr={sched.get_last_lr()[0]:.2e} {time.time() - t0:.0f}s", flush=True)
            if step % args.val_every == 0 or (args.max_steps and step >= args.max_steps):
                r = val()
                rec = {"step": step, "loss": float(loss.item()), **r}
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
                print("  val:", r, flush=True)
                if r.get("songs") and (r["median"], -r["le03"]) < (best[0], -best[1]):
                    best = (r["median"], r["le03"])
                    torch.save(model.state_dict(), out)
                    print(f"  ★ ดีขึ้น → บันทึก {out}", flush=True)
            if args.max_steps and step >= args.max_steps:
                break
        if args.max_steps and step >= args.max_steps:
            break
    print(f"จบ: {step} ก้าว {time.time() - t0:.0f} วิ · ดีที่สุด median={best[0]:.3f} ≤0.3วิ={best[1]:.0%} · น้ำหนัก: {out if out.exists() else '(ไม่ดีกว่าของเดิม ไม่ได้บันทึก)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
