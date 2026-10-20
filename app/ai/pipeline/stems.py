"""แยกเสียงร้องด้วย Demucs htdemucs (fp16 ผ่าน autocast) ทีละช่วงของเพลง — รันใน AI worker เท่านั้น

ผลคือเสียงร้องสะอาดสำหรับ Whisper/alignment (เสียงร้องในเพลงที่มีดนตรีเต็มวงฟังยากมาก)
ทำทีละช่วง (ช่วงละ ~30 วิ + บริบทหัวท้าย) เพื่อให้ผลทยอยออกและใช้ VRAM คงที่ ไม่ขึ้นกับความยาวเพลง
"""

from __future__ import annotations

from typing import Any

import numpy as np


def load_model(config: dict[str, Any], device: str) -> Any:
    """โหลด htdemucs ค้างไว้ใน VRAM (ครั้งแรกต้องออกเน็ตโหลดน้ำหนักราว 80 MB ไป TORCH_HOME)"""
    from demucs.pretrained import get_model

    model = get_model(str(config.get("model", "htdemucs")))
    model.eval()
    model.to(device)
    return model


def separate_vocals(model: Any, stereo: np.ndarray, device: str, config: dict[str, Any]) -> np.ndarray:
    """stereo (n,2) float32 ที่ sample rate ของโมเดล (44.1k) -> เสียงร้อง (n,2)"""
    import torch
    from demucs.apply import apply_model

    wav = torch.from_numpy(np.ascontiguousarray(stereo.T))     # (2, n)
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    wav = (wav - mean) / std                                    # demucs ต้อง normalize ก่อน (เหมือน demucs.separate)
    segment = min(float(config.get("segment_s", 7.0)), float(getattr(model, "segment", 7.8)))
    use_amp = device == "cuda" and bool(config.get("fp16", True))
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
        out = apply_model(model, wav[None].to(device), device=device, shifts=int(config.get("shifts", 0)), split=True,
                          overlap=float(config.get("overlap", 0.25)), progress=False, segment=segment)[0]
    vocals = out[list(model.sources).index("vocals")].float() * std.to(out.device) + mean.to(out.device)
    return vocals.cpu().numpy().T.astype(np.float32)


def to_mono_16k(x: np.ndarray, sample_rate: int, device: str = "cpu") -> np.ndarray:
    """(n,2) หรือ (n,) -> mono 16 kHz (Whisper/MMS ต้องการ) ด้วย torchaudio"""
    import torch
    import torchaudio

    mono = x.mean(axis=1) if x.ndim == 2 else x
    if sample_rate == 16000:
        return mono.astype(np.float32)
    t = torch.from_numpy(np.ascontiguousarray(mono, dtype=np.float32))[None]
    out = torchaudio.functional.resample(t.to(device), sample_rate, 16000)
    return out[0].cpu().numpy()
