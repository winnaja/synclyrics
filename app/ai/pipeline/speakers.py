"""นับ/แยกนักร้องจากเสียงร้อง (ผู้ใช้สั่ง 2026-10-21: ≥2 คน → นักร้องนำที่ร้องมากสุดชิดซ้าย คนรองชิดขวา)

ใช้ ECAPA-TDNN (speechbrain/spkrec-ecapa-voxceleb 83 MB) หา "ลายเสียง" (192 มิติ) ของแต่ละบรรทัดจาก stem เสียงร้อง แล้วจัดกลุ่มตามความคล้าย
ไม่ใช้ API ดาวน์โหลดของ speechbrain (เข้ากับ huggingface_hub/torchaudio รุ่นใหม่ไม่ได้) — ประกอบโมเดลเองจาก embedding_model.ckpt
รันใน AI worker เท่านั้น · speechbrain ติดตั้งแบบ --no-deps ใน ai_runtime/site จึงมี stub เล็กๆ สำหรับ scipy/torchaudio ที่ไม่ได้ใช้จริง
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np

REPO = "speechbrain/spkrec-ecapa-voxceleb"
MIN_LINE_S = 1.0           # บรรทัดสั้นกว่านี้ลายเสียงไม่เสถียร (ไม่ตัดสิน)
MAX_CLIP_S = 8.0
MIN_LINES = 8
# เกณฑ์ "มีนักร้องคนที่สองจริง": ลายเสียงของสองกลุ่มต่างกันพอ และกลุ่มรองมีบรรทัดมากพอ
SPLIT_SIM = 0.50           # ความคล้าย (cosine) ระหว่างศูนย์กลางสองกลุ่ม ต่ำกว่านี้ถือว่าเป็นคนละคน (ตั้งเข้ม: เพลงร้องคนเดียวที่เสียงเปลี่ยนโทนวัดได้ 0.59-0.71 ห้ามถูกตีเป็นดูเอ็ต)
MIN_MINOR_FRAC = 0.12


def _stub_unused_modules() -> None:
    """speechbrain ต้องการ scipy/torchaudio บางส่วนตอน import แต่ ECAPA ที่ใช้ไม่เรียกจริง"""
    import torchaudio

    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: []     # type: ignore[attr-defined]
    try:
        import scipy  # noqa: F401
    except ImportError:
        for name in ("scipy", "scipy.stats", "scipy.signal", "scipy.special", "scipy.io", "scipy.io.wavfile", "scipy.ndimage",
                     "scipy.optimize", "scipy.fft", "scipy.linalg", "scipy.spatial", "scipy.spatial.distance"):
            mod = types.ModuleType(name)
            mod.__getattr__ = lambda k, n=name: (lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(f"{n}.{k} ไม่มี (stub)")))  # type: ignore[attr-defined]
            sys.modules[name] = mod


def model_dir(models_dir: str | Path) -> Path:
    return Path(models_dir) / "spk"


def ensure_files(models_dir: str | Path) -> Path:
    d = model_dir(models_dir)
    if not (d / "embedding_model.ckpt").exists():
        from huggingface_hub import hf_hub_download

        for f in ("embedding_model.ckpt",):
            hf_hub_download(REPO, f, local_dir=str(d))
    return d


def load_encoder(models_dir: str | Path, device: str = "cpu") -> dict[str, Any]:
    import torch

    _stub_unused_modules()
    d = ensure_files(models_dir)
    from speechbrain.lobes.features import Fbank
    from speechbrain.lobes.models.ECAPA_TDNN import ECAPA_TDNN
    from speechbrain.processing.features import InputNormalization

    fbank = Fbank(n_mels=80)
    norm = InputNormalization(norm_type="sentence", std_norm=False)
    model = ECAPA_TDNN(input_size=80, channels=[1024, 1024, 1024, 1024, 3072], kernel_sizes=[5, 3, 3, 3, 1], dilations=[1, 2, 3, 4, 1],
                       attention_channels=128, lin_neurons=192)
    model.load_state_dict(torch.load(d / "embedding_model.ckpt", map_location="cpu"))
    model.eval().to(device)
    fbank.eval().to(device)
    norm.eval().to(device)
    return {"fbank": fbank, "norm": norm, "model": model, "device": device}


def embed(enc: dict[str, Any], wav16: np.ndarray) -> np.ndarray:
    """เสียงมอโน 16 kHz -> ลายเสียงหน่วยความยาว 1 (192)"""
    import torch

    dev = enc["device"]
    x = torch.from_numpy(np.ascontiguousarray(wav16, dtype=np.float32))[None].to(dev)
    with torch.inference_mode():
        feats = enc["fbank"](x)
        lens = torch.ones(1, device=dev)
        feats = enc["norm"](feats, lens)
        e = enc["model"](feats, lens)
    v = e.squeeze().float().cpu().numpy()
    return v / (np.linalg.norm(v) + 1e-9)


def line_embeddings(enc: dict[str, Any], vocals16: np.ndarray, spans: list[tuple[float, float]]) -> list[np.ndarray | None]:
    out: list[np.ndarray | None] = []
    for s, e in spans:
        if e - s < MIN_LINE_S:
            out.append(None)
            continue
        mid = (s + e) / 2.0
        half = min(MAX_CLIP_S, e - s) / 2.0
        a, b = int((mid - half) * 16000), int((mid + half) * 16000)
        out.append(embed(enc, vocals16[max(0, a):min(len(vocals16), b)]))
    return out


def cluster_two(embs: np.ndarray, iters: int = 20) -> tuple[np.ndarray, float]:
    """k-means (k=2, cosine) คืน (ป้ายกลุ่มต่อแถว, ความคล้ายของศูนย์กลางสองกลุ่ม)"""
    n = len(embs)
    sim = embs @ embs.T
    i, j = np.unravel_index(np.argmin(sim), sim.shape)       # เริ่มจากคู่ที่ต่างกันที่สุด
    cents = np.stack([embs[i], embs[j]])
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        labels = np.argmax(embs @ cents.T, axis=1)
        new = np.stack([embs[labels == k].mean(axis=0) if np.any(labels == k) else cents[k] for k in range(2)])
        new /= np.linalg.norm(new, axis=1, keepdims=True) + 1e-9
        if np.allclose(new, cents, atol=1e-5):
            break
        cents = new
    return labels, float(cents[0] @ cents[1])


def assign_singers(embs: list[np.ndarray | None], durations: list[float]) -> tuple[list[int | None], dict[str, Any]]:
    """ลายเสียงรายบรรทัด -> ผู้ร้อง 0 = นักร้องนำ (ร้องรวมนานสุด) · 1 = คนรอง · None = ไม่ตัดสิน/ร้องคนเดียว
    คืน (ผู้ร้องต่อบรรทัด, สถิติ) · ร้องคนเดียว/ข้อมูลน้อย = ทุกบรรทัด 0"""
    idx = [k for k, e in enumerate(embs) if e is not None]
    stats: dict[str, Any] = {"lines": len(idx), "multi": False}
    singers: list[int | None] = [0 if embs[k] is not None else None for k in range(len(embs))]
    if len(idx) < MIN_LINES:
        return singers, stats
    mat = np.stack([embs[k] for k in idx])           # type: ignore[misc]
    labels, csim = cluster_two(mat)
    stats["centroid_sim"] = round(csim, 3)
    minor = min(np.sum(labels == 0), np.sum(labels == 1))
    stats["minor_frac"] = round(float(minor) / len(idx), 3)
    if csim >= SPLIT_SIM or minor / len(idx) < MIN_MINOR_FRAC:
        return singers, stats
    dur = [sum(durations[k] for k, lb in zip(idx, labels) if lb == c) for c in (0, 1)]
    lead = 0 if dur[0] >= dur[1] else 1
    stats["multi"] = True
    stats["lead_share"] = round(dur[lead] / max(1e-9, dur[0] + dur[1]), 3)
    for k, lb in zip(idx, labels):
        singers[k] = 0 if lb == lead else 1
    # บรรทัดที่ไม่ตัดสิน (สั้น) ใช้ผู้ร้องของบรรทัดที่ใกล้ที่สุดข้างหน้า/หลัง
    last: int | None = None
    for k in range(len(singers)):
        if singers[k] is None:
            singers[k] = last
        else:
            last = singers[k]
    nxt: int | None = None
    for k in range(len(singers) - 1, -1, -1):
        if singers[k] is None:
            singers[k] = nxt if nxt is not None else 0
        else:
            nxt = singers[k]
    return singers, stats
