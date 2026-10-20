"""forced alignment ระดับคำด้วย torchaudio MMS_FA (ข้อ 5.1 ขั้น 6) — ใช้ "เกลา" เวลาคำหลังจับคู่ด้วย Whisper แล้ว

Whisper บอกว่าบรรทัดไหนอยู่ช่วงไหน (หยาบ ±0.3 วิ) · MMS_FA (CTC) ให้เวลาคำที่ละเอียดกว่ามาก (หลักสิบมิลลิวินาที)
ขั้นตอนต่อบรรทัด:
  1. normalize ข้อความ: ไทย/ญี่ปุ่น/เกาหลี/จีน -> uroman เป็นตัวอักษรละติน (เก็บ map กลับคำเดิม) · ละติน -> a-z กับ '
  2. ตัดเสียงร้อง 16 kHz ตามช่วงบรรทัด (+ขอบ) แล้ว forced_align ทั้งบรรทัดทีเดียว
  3. token spans -> รวมเป็นคำ -> เวลาคำ + confidence (ค่าเฉลี่ย prob ของ token)
  confidence ต่ำกว่า min_confidence = ไม่เชื่อผล ใช้เวลาจาก Whisper/ประมาณแทน (ข้อ 5.1 ขั้น 8)
torchaudio ต้องเป็น 2.11 (ดู requirements-ai.txt) · รันใน AI worker เท่านั้น
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

SAMPLE_RATE = 16000
EDGE_S = 0.35            # ขยายช่วงบรรทัดออกหัวท้ายเท่านี้ ให้ CTC หาขอบคำเจอ
_LATIN_RE = re.compile(r"[^a-z']")
_UROMAN_LANG = {"th": "tha", "ja": "jpn", "ko": "kor", "zh": "zho", "yue": "yue", "ru": "rus", "hi": "hin", "ar": "ara"}


def _needs_uroman(word: str) -> bool:
    """มีตัวอักษรนอกชุดละติน (ไทย/ญี่ปุ่น/เกาหลี/จีน/ซีริลลิก ...) ที่ต้องแปลงก่อน align"""
    return any(ord(c) > 0x24F and c.isalpha() and not (0x1E00 <= ord(c) <= 0x1EFF) for c in word)


def load_model(config: dict[str, Any], device: str) -> dict[str, Any]:
    """โหลด MMS_FA bundle (ครั้งแรกต้องออกเน็ตโหลดน้ำหนักราว 1.2 GB ไป TORCH_HOME)"""
    import torchaudio

    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False).to(device)
    model.eval()
    uroman = None
    try:
        import uroman as ur

        uroman = ur.Uroman()
    except Exception:  # noqa: BLE001 — ไม่มี uroman = ทำได้เฉพาะภาษาละติน
        uroman = None
    return {"bundle": bundle, "model": model, "dict": bundle.get_dict(star=None), "device": device, "uroman": uroman,
            "min_confidence": float(config.get("min_confidence", 0.45)), "fp16": bool(config.get("fp16", True))}


def clean_latin(text: str) -> str:
    """เหลือเฉพาะ a-z กับ ' (ชุดตัวอักษรที่ MMS_FA รู้จัก)"""
    return _LATIN_RE.sub("", text.lower())


def romanize_word(word: str, language: str | None, uroman: Any) -> str:
    """คำ -> ตัวอักษรละติน (a-z ') ที่ใช้ align ได้ · แปลงไม่ได้/ไม่มีตัวอักษรเลย = "" """
    if not word.strip():
        return ""
    if uroman is not None and (language in _UROMAN_LANG or _needs_uroman(word)):
        try:
            text = uroman.romanize_string(word, lcode=_UROMAN_LANG.get(language or "", None))
        except Exception:  # noqa: BLE001
            text = word
    else:
        text = word
    import unicodedata

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return clean_latin(text)


def align_line(bundle: dict[str, Any], vocals16: np.ndarray, line_start: float, line_end: float, words: list[str],
               language: str | None) -> list[tuple[float, float, float]] | None:
    """เวลาทีละคำ [(start, end, confidence)] ของ words (เวลาสัมบูรณ์) หรือ None ถ้าทำไม่ได้/ไม่น่าเชื่อ"""
    import torch
    import torchaudio.functional as F

    roman = [romanize_word(w, language, bundle["uroman"]) for w in words]
    if sum(len(r) for r in roman) < 2:
        return None
    t0 = max(0.0, line_start - EDGE_S)
    t1 = line_end + EDGE_S
    i0, i1 = int(t0 * SAMPLE_RATE), min(len(vocals16), int(t1 * SAMPLE_RATE))
    if i1 - i0 < SAMPLE_RATE * 0.3:
        return None
    dev = bundle["device"]
    wav = torch.from_numpy(np.ascontiguousarray(vocals16[i0:i1], dtype=np.float32))[None].to(dev)
    wav = wav / (wav.abs().max() + 1e-6) * 0.9                   # ระดับเสียงคงที่ (ช่วยโมเดลเมื่อเสียงร้องเบา)
    d = bundle["dict"]
    tokens = [[d[c] for c in r if c in d] for r in roman]
    flat = [t for ts in tokens for t in ts]
    if len(flat) < 1:
        return None
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=dev == "cuda" and bundle["fp16"]):
        emission, _ = bundle["model"](wav)
    emission = torch.log_softmax(emission.float(), dim=-1)
    n_frames = emission.size(1)
    if n_frames < len(flat):         # ช่วงสั้นเกินกว่าจะใส่ทุกตัวอักษร
        return None
    targets = torch.tensor([flat], dtype=torch.int32, device=emission.device)
    alignment, scores = F.forced_align(emission, targets, blank=0)
    spans = F.merge_tokens(alignment[0], scores[0].exp())
    if len(spans) != len(flat):
        return None
    sec_per_frame = (i1 - i0) / SAMPLE_RATE / n_frames
    out: list[tuple[float, float, float] | None] = []
    k = 0
    for ts in tokens:
        if not ts:
            out.append(None)
            continue
        group = spans[k:k + len(ts)]
        k += len(ts)
        s = t0 + group[0].start * sec_per_frame
        e = t0 + group[-1].end * sec_per_frame
        conf = float(sum(sp.score for sp in group) / len(group))
        out.append((s, max(e, s + 0.04), conf))
    return _fill_gaps(out, line_start, line_end)


def _fill_gaps(spans: list[tuple[float, float, float] | None], line_start: float, line_end: float) -> list[tuple[float, float, float]] | None:
    """คำที่ไม่มีตัวอักษรให้ align (เครื่องหมาย/แปลงไม่ได้) ได้เวลาระหว่างคำข้างเคียง (confidence ต่ำ)"""
    if all(s is None for s in spans):
        return None
    res: list[tuple[float, float, float]] = []
    for i, s in enumerate(spans):
        if s is not None:
            res.append(s)
            continue
        prev_end = res[-1][1] if res else line_start
        nxt = next((x for x in spans[i + 1:] if x is not None), None)
        nxt_start = nxt[0] if nxt else line_end
        t = min(prev_end, nxt_start)
        res.append((t, max(t, min(nxt_start, t + 0.05)), 0.2))
    return res


def line_confidence(spans: list[tuple[float, float, float]]) -> float:
    return float(sum(c for _s, _e, c in spans) / len(spans)) if spans else 0.0


# ---------------------------------------------------------------------------
# จัดเวลาทั้งเพลงทีเดียว (global CTC forced alignment) — ไม่พึ่งข้อความที่ Whisper ฟังได้
# ---------------------------------------------------------------------------
FRAME_SAMPLES = 320          # wav2vec2: 1 frame = 320 ตัวอย่าง = 20 มิลลิวินาที (16 kHz)


def emission_full(bundle: dict[str, Any], vocals16: np.ndarray, chunk_s: float = 30.0, ctx_s: float = 1.0) -> Any:
    """emission (log-prob) ของเสียงร้องทั้งเพลง (T, C) — ประมวลผลทีละช่วง 30 วิ + บริบท 1 วิ แล้วต่อกัน (VRAM คงที่ไม่ขึ้นกับความยาวเพลง)"""
    import torch

    dev = bundle["device"]
    chunk, ctx = int(chunk_s * SAMPLE_RATE), int(ctx_s * SAMPLE_RATE)
    chunk -= chunk % FRAME_SAMPLES
    ctx -= ctx % FRAME_SAMPLES
    parts = []
    n = len(vocals16)
    for start in range(0, n, chunk):
        a, b = max(0, start - ctx), min(n, start + chunk + ctx)
        wav = torch.from_numpy(np.ascontiguousarray(vocals16[a:b], dtype=np.float32))[None].to(dev)
        wav = wav / (wav.abs().max() + 1e-6) * 0.9
        with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.float16, enabled=dev == "cuda" and bundle["fp16"]):
            em, _ = bundle["model"](wav)
        em = torch.log_softmax(em.float(), dim=-1)[0]
        lead = (start - a) // FRAME_SAMPLES
        take = min(chunk, n - start) // FRAME_SAMPLES
        parts.append(em[lead:lead + take])
    return torch.cat(parts, dim=0)


def align_global(bundle: dict[str, Any], vocals16: np.ndarray, line_words: list[list[str]], language: str | None) -> list[list[tuple[float, float, float]] | None]:
    """จัดเวลาคำของ "ทุกบรรทัด" พร้อมกันตลอดเพลงด้วย CTC Viterbi (เรียงตามลำดับเนื้อเพลง) คืนรายการต่อบรรทัด [(start,end,conf)] หรือ None (บรรทัดไม่มีตัวอักษรให้จัด)
    ข้อดีเทียบการจับคู่ข้อความ Whisper: ไม่พึ่งว่า Whisper ฟังถูก — ใช้เสียงกับข้อความเนื้อเพลงตรงๆ · ข้อเสีย: บังคับให้ทุกคำมีที่อยู่ จึงต้องดู conf ต่อบรรทัดเสมอ"""
    import torch
    import torchaudio.functional as F

    d = bundle["dict"]
    tokens: list[int] = []
    owner: list[tuple[int, int]] = []     # (บรรทัด, คำ) ของแต่ละ token
    words_tok: list[list[list[int]]] = []
    for li, ws in enumerate(line_words):
        wl = []
        for wi, w in enumerate(ws):
            ids = [d[c] for c in romanize_word(w, language, bundle["uroman"]) if c in d]
            wl.append(ids)
            tokens.extend(ids)
            owner.extend([(li, wi)] * len(ids))
        words_tok.append(wl)
    out: list[list[tuple[float, float, float]] | None] = [None] * len(line_words)
    if not tokens:
        return out
    emission = emission_full(bundle, vocals16)
    if emission.size(0) < len(tokens) + 2:
        return out
    targets = torch.tensor([tokens], dtype=torch.int32, device=emission.device)
    alignment, scores = F.forced_align(emission[None], targets, blank=0)
    spans = F.merge_tokens(alignment[0], scores[0].exp())
    if len(spans) != len(tokens):
        return out
    sec = FRAME_SAMPLES / SAMPLE_RATE
    k = 0
    for li, wl in enumerate(words_tok):
        res: list[tuple[float, float, float] | None] = []
        for ids in wl:
            if not ids:
                res.append(None)
                continue
            grp = spans[k:k + len(ids)]
            k += len(ids)
            res.append((grp[0].start * sec, max(grp[-1].end * sec, grp[0].start * sec + 0.04), float(sum(sp.score for sp in grp) / len(grp))))
        if any(r is not None for r in res):
            out[li] = _fill_gaps(res, next(r[0] for r in res if r), next(r[1] for r in reversed(res) if r))
    return out
