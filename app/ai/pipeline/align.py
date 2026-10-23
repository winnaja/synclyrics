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


class Span(tuple):
    """(start, end, confidence) ที่พก .curve ไปด้วย (เส้นโค้งการร้องในคำ) — unpack/index เป็น tuple สามตัวตามเดิม"""

    curve: list[float] | None = None

    def __new__(cls, start: float, end: float, conf: float, curve: list[float] | None = None) -> "Span":
        obj = super().__new__(cls, (start, end, conf))
        obj.curve = curve
        return obj


def _needs_uroman(word: str) -> bool:
    """มีตัวอักษรนอกชุดละติน (ไทย/ญี่ปุ่น/เกาหลี/จีน/ซีริลลิก ...) ที่ต้องแปลงก่อน align"""
    return any(ord(c) > 0x24F and c.isalpha() and not (0x1E00 <= ord(c) <= 0x1EFF) for c in word)


def load_model(config: dict[str, Any], device: str) -> dict[str, Any]:
    """โหลด MMS_FA bundle (ครั้งแรกต้องออกเน็ตโหลดน้ำหนักราว 1.2 GB ไป TORCH_HOME)"""
    import torchaudio

    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False)
    ft = config.get("finetuned") or ""
    if ft:   # น้ำหนักที่ fine-tune กับเสียงร้อง (scripts/train_ctc.py) — ไม่มีไฟล์ = ใช้ MMS เดิม
        import logging
        from pathlib import Path

        import torch

        # เส้นทางสัมพัทธ์ = เทียบกับโฟลเดอร์โปรเจกต์ (ไม่ผูกกับโฟลเดอร์ที่สั่งรัน ไม่งั้นแอปเปิดจากที่อื่นแล้วเงียบ ๆ ไปใช้ MMS เดิม)
        root = Path(__file__).resolve().parents[3]
        path = next((c for c in (Path(ft), root / ft) if c.is_file()), None)
        if path is not None:
            model.load_state_dict(torch.load(path, map_location="cpu"))
            logging.getLogger(__name__).info("ใช้น้ำหนัก MMS ที่ fine-tune: %s", path)
        else:
            logging.getLogger(__name__).warning("ไม่พบไฟล์น้ำหนัก fine-tune %s — ใช้ MMS เดิม", ft)
    model = model.to(device)
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


_kakasi: Any = None
# uroman ทิ้งสระอะที่ภาษาไทยไม่เขียน (ขนม -> khnm ไม่มีสระเลย) · royin ของ pythainlp เติมให้ (khanom)
# แต่ royin ก็พลาดบางคำ (หัวใจ -> uachai หาย h) จึงต้องวัดก่อนว่าตัวไหนดีกว่าจริง: ตั้งค่าได้ด้วย SYNCLYRICS_TH_ROMAN
_TH_ROMAN = __import__("os").environ.get("SYNCLYRICS_TH_ROMAN", "uroman")
# วิธีหาเวลาจบของคำท้ายบรรทัด: continue = ต่อถึงบรรทัดถัดไป · hold = ต่อจาก CTC อีก HOLD_TAIL_S (ของเดิม)
_LINE_END = __import__("os").environ.get("SYNCLYRICS_LINE_END", "continue")


def _thai_reading(word: str) -> str | None:
    try:
        from pythainlp.transliterate import romanize

        return romanize(word, engine="royin") or None
    except Exception:  # noqa: BLE001 — pythainlp มีปัญหา = ใช้ uroman ต่อ
        return None


def _japanese_reading(word: str) -> str | None:
    """คันจิ -> คำอ่านญี่ปุ่นเป็นอักษรละติน · uroman อ่านคันจิเป็นเสียงจีนเสมอ (東京 -> dongjing ไม่ใช่ toukyou)
    แม้ส่ง lcode=jpn ไปแล้ว ทำให้เพลงญี่ปุ่นถูกจับคู่กับเสียงที่ออกเสียงผิดทั้งเพลง
    หมายเหตุ: pykakasi เลือกคำอ่านจากพจนานุกรม ไม่ได้วิเคราะห์ไวยากรณ์ คันจิที่มีหลายคำอ่านจึงยังพลาดได้บ้าง"""
    global _kakasi
    if _kakasi is None:
        try:
            import pykakasi

            _kakasi = pykakasi.kakasi()
        except Exception:  # noqa: BLE001 — ไม่มี pykakasi = ใช้ uroman ต่อ (ญี่ปุ่นจะแม่นน้อยลง)
            _kakasi = False
    if not _kakasi:
        return None
    try:
        return "".join(part["hepburn"] for part in _kakasi.convert(word))
    except Exception:  # noqa: BLE001
        return None


def romanize_line(words: list[str], language: str | None, uroman: Any) -> list[str]:
    """คำทั้งบรรทัด -> คำอ่านละตินของแต่ละคำ

    ญี่ปุ่นต้องอ่านทั้งบรรทัดพร้อมกัน: เฉลยจาก NetEase แยกเป็นตัวอักษรทีละตัว แต่คำอ่านคันจิขึ้นกับคำประสมทั้งคำ
    (世界 = sekai แต่แยกเป็น 世 + 界 ทีละตัวจะได้คำอ่านอื่น) · ภาษาอื่นแปลงทีละคำเหมือนเดิม
    """
    if language == "ja" and any(_needs_uroman(w) for w in words):
        out = _japanese_line_reading(words)
        if out is not None:
            return out
    return [romanize_word(w, language, uroman) for w in words]


def _japanese_line_reading(words: list[str]) -> list[str] | None:
    """อ่านทั้งบรรทัดแล้วกระจายคำอ่านกลับไปแต่ละคำ · คำอ่านที่คร่อมหลายคำแบ่งตามสัดส่วนจำนวนตัวอักษร"""
    if _japanese_reading("あ") is None:      # ไม่มี pykakasi
        return None
    owner: list[int] = []
    for wi, w in enumerate(words):
        owner.extend([wi] * len(w))
    try:
        segs = _kakasi.convert("".join(words))
    except Exception:  # noqa: BLE001
        return None
    out = [""] * len(words)
    pos = 0
    for seg in segs:
        src, read = seg.get("orig") or "", seg.get("hepburn") or ""
        if not src:
            continue
        span = owner[pos:pos + len(src)]
        pos += len(src)
        if not span:
            continue
        uniq = sorted(set(span))
        if len(uniq) == 1:
            out[uniq[0]] += read
        else:       # คำอ่านเดียวคร่อมหลายคำ -> ตัดตามสัดส่วนจำนวนตัวอักษรต้นฉบับของแต่ละคำ
            k = 0
            for wi in uniq:
                n = span.count(wi)
                take = max(1, round(len(read) * n / len(span))) if wi != uniq[-1] else len(read) - k
                out[wi] += read[k:k + max(0, take)]
                k += max(0, take)
    return [clean_latin(r) for r in out]


def romanize_word(word: str, language: str | None, uroman: Any) -> str:
    """คำ -> ตัวอักษรละติน (a-z ') ที่ใช้ align ได้ · แปลงไม่ได้/ไม่มีตัวอักษรเลย = "" """
    if not word.strip():
        return ""
    if language == "ja":
        jp = _japanese_reading(word)
        if jp:
            return clean_latin(jp)
    if language == "th" and _TH_ROMAN == "royin":
        th = _thai_reading(word)
        if th:
            return clean_latin(th)
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

    roman = romanize_line(words, language, bundle["uroman"])
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
        e = max(e, s + 0.04)
        out.append(Span(s, e, conf, _curve(group, t0, sec_per_frame, s, e)))
    return _fill_gaps(out, line_start, line_end)


CURVE_STEP_S = 0.05      # ระยะห่างจุดบนเส้นโค้งที่ส่งให้ UI
CURVE_SIGMA_S = 0.09     # ความนุ่มของเส้นโค้ง (gaussian) — ยิ่งมากยิ่งไหลลื่น ยิ่งน้อยยิ่งตามพยางค์เป๊ะแต่กระตุก
CURVE_MIX = 0.65         # สัดส่วนที่ตามเสียงจริง (ที่เหลือคือเส้นตรง) — กันการเติมสีกระโดดเร็ว/ค้างเมื่อ alignment รายตัวอักษรหยาบ


def _curve(group: list[Any], t0: float, sec_per_frame: float, word_start: float, word_end: float) -> list[float] | None:
    """token ของคำหนึ่ง -> [t0, f0, t1, f1, ...] ความคืบหน้า (สัดส่วนตัวอักษร) ตามเวลา · ตัวอักษรสั้นเกินไป = None (ไล่เส้นตรง)
    ผ่านจุดกึ่งกลางของแต่ละตัวอักษร (ไม่ใช่ขอบ — ไม่มีช่วงค้าง/กระโดด) แล้วทำให้นุ่มด้วย gaussian และผสมกับเส้นตรง → เติมสีไหลลื่นแบบคลิปอ้างอิง
    ต่อเนื่อง/เพิ่มขึ้นเสมอ (monotone) และปลายโค้งตรงกับเวลาเริ่ม/จบคำ"""
    n = len(group)
    dur = word_end - word_start
    if n < 3 or dur < 0.25:
        return None
    ts = [word_start]
    fs = [0.0]
    for j, sp in enumerate(group):
        mid = t0 + (sp.start + sp.end) / 2.0 * sec_per_frame
        mid = min(max(mid, ts[-1] + 1e-3), word_end - 1e-3)
        if mid <= ts[-1]:
            continue
        ts.append(mid)
        fs.append((j + 0.5) / n)
    ts.append(word_end)
    fs.append(1.0)
    k = max(4, int(round(dur / CURVE_STEP_S)) + 1)
    grid = np.linspace(word_start, word_end, k)
    raw = np.interp(grid, ts, fs)
    sig = max(1.0, CURVE_SIGMA_S / (dur / (k - 1)))
    half = int(sig * 3) + 1
    kernel = np.exp(-0.5 * (np.arange(-half, half + 1) / sig) ** 2)
    kernel /= kernel.sum()
    padded = np.concatenate([np.full(half, raw[0]), raw, np.full(half, raw[-1])])
    smooth = np.convolve(padded, kernel, mode="valid")
    lin = (grid - word_start) / dur
    mixed = CURVE_MIX * smooth + (1.0 - CURVE_MIX) * lin
    mixed = np.maximum.accumulate(mixed)
    mixed = (mixed - mixed[0]) / max(1e-9, mixed[-1] - mixed[0])
    out: list[float] = []
    for t, f in zip(grid, mixed):
        out += [round(float(t), 3), round(float(f), 4)]
    return out


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
        for wi, rom in enumerate(romanize_line(ws, language, bundle["uroman"])):
            ids = [d[c] for c in rom if c in d]
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
    raw: list[list[tuple[list[Any], float, float] | None]] = []      # ต่อบรรทัด: (token ของคำ, เริ่ม, จบ)
    for wl in words_tok:
        line: list[tuple[list[Any], float, float] | None] = []
        for ids in wl:
            if not ids:
                line.append(None)
                continue
            grp = spans[k:k + len(ids)]
            k += len(ids)
            line.append((grp, grp[0].start * sec, max(grp[-1].end * sec, grp[0].start * sec + 0.04)))
        raw.append(line)
    fills = _hold_notes(raw, vocals16)
    for li, line in enumerate(raw):
        res: list[tuple[float, float, float] | None] = [
            None if w is None else Span(w[1], w[2], float(sum(sp.score for sp in w[0]) / len(w[0])),
                                        _word_curve(w[0], sec, w[1], w[2], fills.get((li, wi))))
            for wi, w in enumerate(line)]
        if any(r is not None for r in res):
            out[li] = _fill_gaps(res, next(r[0] for r in res if r), next(r[1] for r in reversed(res) if r))
    return out


HOLD_TAIL_S = 0.14      # ลากต่อขั้นต่ำเมื่อดูพลังเสียงไม่ได้ (ค่าที่วัดได้ว่า CTC ตัดจบคำเร็วไปโดยเฉลี่ย)
HOLD_MAX_S = 2.0        # เพดานความยาวคำท้ายบรรทัด (วัดแล้ว 2 วิ ให้ผลเกือบเท่าไม่จำกัด แต่กันช่วงดนตรียาว)
HOLD_FILL_SLACK_S = 0.25  # คำท้ายบรรทัด: "เติมสีเต็ม" ช้ากว่าที่ CTC บอกจบได้อีกไม่เกิน HOLD_TAIL_S + ค่านี้ (ชดเชย CTC ตัดจบเร็ว) แม้ end ของคำจะถูกต่อไปถึงบรรทัดถัดไป


def _word_curve(group: list[Any], sec: float, start: float, end: float, fill_end: float | None) -> list[float] | None:
    """เส้นโค้งเติมสีของคำ · คำท้ายบรรทัดที่ end ถูกต่อไปไกล (fill_end < end): เติมสีเต็มที่ fill_end แล้วค้างเต็มจนถึง end
    ไม่งั้นคำสั้นๆ ที่ร้องจบใน 0.3 วิ จะถูกไล่สีช้าๆ ข้ามช่องว่างทั้ง 2 วิ ดูเหมือนยังไม่ได้ร้อง/ค้างก่อนขึ้นบรรทัดถัดไป"""
    if fill_end is None or fill_end >= end - 1e-6:
        return _curve(group, 0.0, sec, start, end)
    fill_end = max(fill_end, start + 0.04)
    cur = _curve(group, 0.0, sec, start, fill_end)
    if cur is None:
        cur = [round(start, 3), 0.0, round(fill_end, 3), 1.0]
    return cur + [round(end, 3), 1.0]


def _hold_notes(raw: list[list[tuple[list[Any], float, float] | None]], vocals16: np.ndarray | None = None) -> dict[tuple[int, int], float]:
    """ยืด "เวลาจบคำ" ให้ต่อเนื่องถึงคำถัดไป (แก้ในที่)

    CTC พุ่งขึ้นตอนเจอตัวอักษรแล้วดับทันที จบคำจึงเร็วกว่าที่ร้องจริงราว 0.14 วิ ขณะที่คำหนึ่งยาวเฉลี่ย 0.30 วิ
    เฉลยของมนุษย์ (NetEase YRC) 99% ให้คำจบตรงที่คำถัดไปเริ่มพอดี — เสียงร้องลากค้างถึงคำต่อไป ไม่ได้เงียบ
    """
    fills: dict[tuple[int, int], float] = {}   # (บรรทัด, คำ) ของคำท้ายบรรทัดที่ end ถูกต่อไกล -> เวลาที่ควรเติมสีเต็ม
    flat = [(li, wi) for li, line in enumerate(raw) for wi, w in enumerate(line) if w is not None]
    for n, (li, wi) in enumerate(flat):
        grp, gs, ge = raw[li][wi]       # type: ignore[misc]
        raw_ge = ge
        if n + 1 < len(flat):
            nli, nwi = flat[n + 1]
            nxt = raw[nli][nwi][1]      # type: ignore[index]
            # ต่อเนื่องถึงคำถัดไปทั้งในบรรทัดและข้ามบรรทัด — วัดกับเฉลยมนุษย์ 2,770 คำท้ายบรรทัดแล้วกติกานี้ตรงที่สุด
            # (≤50ms 40% เทียบวิธีรอให้พลังเสียงเบาลงซึ่งได้ 21%) · คำท้ายบรรทัดจำกัดไว้ HOLD_MAX_S กันช่วงดนตรียาว
            if nli == li:
                ge = max(gs + 0.04, nxt)
            elif _LINE_END == "hold":      # แบบเดิม: ต่อจากที่ CTC บอกอีกนิดเดียว
                ge = max(gs + 0.04, min(ge + HOLD_TAIL_S, nxt))
            else:
                ge = max(gs + 0.04, min(nxt, gs + HOLD_MAX_S))
                fill = max(gs + 0.04, raw_ge + HOLD_TAIL_S + HOLD_FILL_SLACK_S)
                if fill < ge - 1e-6:
                    fills[(li, wi)] = fill
        else:
            ge = ge + HOLD_TAIL_S
        raw[li][wi] = (grp, gs, ge)
    return fills
