"""Fine-tune ตัวจัดเวลา (MMS_FA / wav2vec2 CTC) ให้เก่งกับ "เสียงร้อง" — เทรนด้วยเสียงร้อง + ข้อความเนื้อเพลง (CTC loss ไม่ต้องใช้เวลารายคำ)
แล้ววัดกับเฉลยรายคำบนเพลง val ทุกๆ --val-every ก้าว เก็บชุดน้ำหนักที่ดีที่สุดไว้ใช้ (ตัวเลือก align.finetuned ใน models.yaml)

ใช้ (ปิดแอปก่อน — ใช้การ์ดจอ 8 GB):
  .venv\\Scripts\\python scripts\\train_ctc.py --epochs 3
ตัวเลือกสำคัญ: --freeze-layers 8 (ล็อก CNN + transformer ชั้นล่าง 8 จาก 24) · --batch 4 · --lr 2e-5 · --max-steps · --out ai_runtime/models/mms_singing.pt
ข้อมูล: dataset/songs/ (scripts/harvest.py) เฉพาะเพลงที่ไม่ติดธง suspect · แบ่ง train/val ตามแฮชรหัสเพลง
"""

from __future__ import annotations

import argparse
import gc
import json
import queue
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


FPS = 50.0      # เฟรมผลลัพธ์ของ wav2vec2 ต่อวินาที (stride 320 ตัวอย่างที่ 16 kHz)


def build_examples(songs, mms, max_clip_s: float):
    """-> [(song, start_s, end_s, target_ids, words)] · words = [(ตัวอักษรของคำ, เริ่ม, จบ) เทียบต้นคลิป] หรือ None

    words มีเฉพาะเพลงที่เฉลยเป็น "เวลารายคำจริง" (ref_timing == word) เท่านั้น — เพลงเฉลยระดับบรรทัดมีเวลาคำแบบประมาณ
    ถ้าเอามาสอนจะสอนเวลาที่ผิดให้โมเดล
    """
    from app.ai.pipeline import align
    from app.ai.training.data import make_clips

    d = mms["dict"]
    ex = []
    for s in songs:
        word_time = s.meta.get("ref_timing", "word") == "word"
        for c in make_clips(s, max_s=max_clip_s):
            if c["end"] - c["start"] > max_clip_s + 1.0:        # บรรทัดเดียวยาวผิดปกติ (เฉลยระดับบรรทัด/ช่วงดนตรี) กิน VRAM เกินและเรียนรู้ไม่ได้
                continue
            wl = []
            for txt, ws, we in c["ref_words"]:
                wid = [d[ch] for ch in align.romanize_word(txt, s.language, mms["uroman"]) if ch in d]
                if wid:
                    wl.append((wid, ws - c["start"], we - c["start"]))
            ids = [i for wid, _s, _e in wl for i in wid]
            frames = (c["end"] - c["start"]) * FPS
            if len(ids) < 6 or len(ids) > frames * 0.8:
                continue
            ex.append((s, c["start"], c["end"], ids, wl if word_time else None))
    return ex


def batches(examples, batch: int, shuffle: bool):
    import numpy as np
    import torch

    order = list(range(len(examples)))
    if shuffle:
        random.shuffle(order)
    for b in range(0, len(order) - batch + 1, batch):
        items = [examples[i] for i in order[b:b + batch]]
        waves, lens, targets, tlens, words = [], [], [], [], []
        for s, t0, t1, ids, wl in items:
            v = np.asarray(s.vocals()[int(t0 * 16000):int(t1 * 16000)], dtype=np.float32)
            if len(v) < 16000:
                break
            v = v / (np.abs(v).max() + 1e-6) * 0.9
            bi = len(waves)
            waves.append(torch.from_numpy(v))
            lens.append(len(v))
            targets.append(torch.tensor(ids, dtype=torch.long))
            tlens.append(len(ids))
            for wid, ws, we in (wl or []):
                words.append((bi, int(ws * FPS), int(we * FPS + 0.999), wid))      # (รายการในก้อน, เฟรมเริ่ม, เฟรมจบ, ตัวอักษร)
        else:
            maxlen = max(lens)
            wav = torch.zeros(len(waves), maxlen)
            for i, w in enumerate(waves):
                wav[i, :len(w)] = w
            yield wav, torch.tensor(lens), torch.cat(targets), torch.tensor(tlens), words


def word_loss(lpb, olens, words, dev):
    """สอน "เวลาทีละคำ" ตรงๆ: บังคับให้ตัวอักษรของแต่ละคำออกมาภายในช่วงเฟรมของคำนั้นตามเฉลยมนุษย์

    CTC ของทั้งคลิปบอกแค่ว่า "มีคำพวกนี้เรียงกัน" โมเดลเดาตำแหน่งเอง · ตัวนี้ตัดเฉพาะเฟรมของคำแล้วคิด CTC ต่อคำ
    วางผิดช่วง = ตัวอักษรไม่อยู่ในหน้าต่างที่ตัดมา ค่าเสียหายจึงสูง -> โมเดลถูกลงโทษเมื่อวางเวลาผิด
    """
    import torch
    import torch.nn.functional as F

    segs, tgts, ilens, tlens = [], [], [], []
    for bi, f0, f1, wid in words:
        f0 = max(0, f0)
        f1 = min(int(olens[bi].item()), f1)
        if f1 - f0 < len(wid) + 1:      # เฟรมน้อยกว่าจำนวนตัวอักษร CTC คิดไม่ได้ (คำสั้น/ร้องเร็ว)
            continue
        segs.append(lpb[bi, f0:f1])
        tgts.append(torch.tensor(wid, dtype=torch.long))
        ilens.append(f1 - f0)
        tlens.append(len(wid))
    if not segs:
        return None
    x = lpb.new_zeros((len(segs), max(ilens), lpb.size(-1)))
    for i, s in enumerate(segs):
        x[i, :s.size(0)] = s
    return F.ctc_loss(x.transpose(0, 1), torch.cat(tgts).to(dev), torch.tensor(ilens, device=dev),
                      torch.tensor(tlens, device=dev), blank=0, zero_infinity=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--word-loss", type=float, default=1.0, help="น้ำหนักของการสอนเวลาทีละคำ (0 = ปิด ใช้ CTC ทั้งคลิปอย่างเดียวแบบเดิม)")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--freeze-layers", type=int, default=8)
    ap.add_argument("--max-clip-s", type=float, default=14.0)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--vram-frac", type=float, default=0.88, help="เพดาน VRAM ที่ PyTorch ใช้ได้ (ส่วนที่เหลือไว้ให้ Windows) — เกินแล้ว Windows ล้นไปใช้แรมเครื่อง ช้าลง 10 เท่า")
    ap.add_argument("--val-every", type=int, default=800)
    ap.add_argument("--init", default="", help="เริ่มต่อจากไฟล์น้ำหนักที่เทรนไว้ (เช่น mms_singing.pt) แทนที่จะเริ่มจาก MMS เดิม")
    ap.add_argument("--val-list", default=str(ROOT / "dataset" / "val_songs.txt"), help="ไฟล์รายชื่อเพลงวัดผลที่ตรึงไว้ (สร้างอัตโนมัติครั้งแรก) — ลบไฟล์นี้เพื่อสุ่มชุดใหม่")
    ap.add_argument("--val-songs", type=int, default=100, help="จำนวนเพลง val ที่ใช้วัด (เรียงเพลงเฉลยรายคำก่อน) · 0 = ทั้งหมด")
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
    if dev == "cuda":
        torch.cuda.set_per_process_memory_fraction(args.vram_frac)
    mms = align.load_model({"finetuned": ""}, dev)          # เริ่มจาก MMS เดิมเสมอ
    model = mms["model"]
    if args.init and Path(args.init).exists():
        model.load_state_dict(torch.load(args.init, map_location=dev))
        print(f"เริ่มต่อจาก {args.init}", flush=True)
    train_songs = list(iter_songs("train"))
    # เพลงเฉลยรายคำมาก่อน: คะแนนเลือกน้ำหนักใช้ตัวเลขรายคำ และ val โตขึ้นเรื่อยๆ จนต้องจำกัดจำนวน (วัดครั้งละ ~1.5 วิ/เพลง)
    val_songs = sorted(iter_songs("val"), key=lambda s: s.meta.get("ref_timing", "word") != "word")
    if args.val_songs:
        # ตรึงรายชื่อเพลงวัดผลไว้ในไฟล์: เก็บเพลงเพิ่มทุกรอบทำให้ชุดวัดเปลี่ยนไปเรื่อยๆ ตัวเลขข้ามรอบจึงเทียบกันไม่ได้
        pin = Path(args.val_list)
        if pin.exists():
            want = [x for x in pin.read_text(encoding="utf-8").split() if x]
            have = {s.id: s for s in val_songs}
            val_songs = [have[i] for i in want if i in have]
            print(f"ใช้ชุดวัดผลที่ตรึงไว้ {len(val_songs)}/{len(want)} เพลง ({pin})", flush=True)
        else:
            val_songs = val_songs[:args.val_songs]
            pin.parent.mkdir(parents=True, exist_ok=True)
            pin.write_text("\n".join(s.id for s in val_songs), encoding="utf-8")
            print(f"ตรึงชุดวัดผล {len(val_songs)} เพลงไว้ที่ {pin}", flush=True)
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
        finally:
            gc.collect()
            torch.cuda.empty_cache()       # คืน VRAM ที่ค้างจากการวัดผล — ไม่งั้นเหลือไม่พอตอนเทรนแล้วล้นไปใช้แรมเครื่อง ช้าลง 5-10 เท่า

    def score(r: dict) -> float:
        """คะแนนรวมสำหรับเลือกน้ำหนักที่ดีที่สุด — เน้น "รายคำ" (เริ่มคำ + จบคำ/ลากคำ) ตามที่ใช้จริงในแอป
        ไม่มีเพลงเฉลยรายคำใน val ค่อยใช้เวลาเริ่มบรรทัดแทน"""
        if not r.get("songs"):
            return -1.0
        if r.get("words"):
            return 2 * r["word_le015"] + r["word_le03"] + r["end_le015"] + r["dur_le015"]
        return 2 * r["le015"] + r["le03"]

    base = val()
    print("ก่อนเทรน (val):", base, flush=True)
    best = score(base)
    log = DATASET_DIR / "train_log.jsonl"
    step = 0
    t0 = time.time()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for ep in range(args.epochs):
        for wav, lens, targets, tlens, words in batches(examples, args.batch, True):
            model.train()
            try:
                wav = wav.to(dev)
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=dev == "cuda"):
                    logits, olens = net(wav, lens.to(dev))
                lpb = F.log_softmax(logits.float(), dim=-1)          # (ก้อน, เฟรม, คลาส)
                lp = lpb.transpose(0, 1)
                loss = F.ctc_loss(lp, targets.to(dev), olens, tlens.to(dev), blank=0, zero_infinity=True)
                wloss = word_loss(lpb, olens, words, dev) if args.word_loss > 0 else None
                if wloss is not None:
                    loss = loss + args.word_loss * wloss
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
            if dev == "cuda" and step % 100 == 0:
                torch.cuda.empty_cache()       # กันแคชบวมจนชนเพดาน (ความยาวคลิปไม่เท่ากัน ทำให้เศษหน่วยความจำสะสม)
            if step % 20 == 0:
                print(f"  ep{ep} step {step}/{total_steps} loss={loss.item():.3f} lr={sched.get_last_lr()[0]:.2e} {time.time() - t0:.0f}s", flush=True)
            if step % args.val_every == 0 or (args.max_steps and step >= args.max_steps):
                r = val()
                rec = {"step": step, "loss": float(loss.item()), **r}
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
                print("  val:", r, flush=True)
                if score(r) > best:
                    best = score(r)
                    torch.save(model.state_dict(), out)
                    print(f"  ★ ดีขึ้น (คะแนน {best:.4f}) → บันทึก {out}", flush=True)
            if args.max_steps and step >= args.max_steps:
                break
        if args.max_steps and step >= args.max_steps:
            break
    print(f"จบ: {step} ก้าว {time.time() - t0:.0f} วิ · คะแนนดีที่สุด {best:.4f} · น้ำหนัก: {out if out.exists() else '(ไม่ดีกว่าของเดิม ไม่ได้บันทึก)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
