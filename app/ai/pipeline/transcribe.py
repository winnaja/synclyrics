"""faster-whisper (large-v3-turbo, word_timestamps) — ฟังเสียงร้องแล้วได้ "คำ + เวลา" (ข้อ 5.1 ขั้น 6, ข้อ 4.2 ข้อ 7)

2 หน้าที่: (ก) ได้ transcript ไปจับคู่กับเนื้อเพลงสำเร็จรูปเพื่อหาเวลาจริง (match.py)
          (ข) ไม่เจอเนื้อเพลงที่ไหนเลย -> ใช้ transcript เป็นเนื้อเพลง (ติดป้าย "ถอดเสียงโดย AI อาจมีคำผิด")
VRAM ไม่พอ: ลดเป็น int8_float16 อัตโนมัติ (`fallback_compute_type`)
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.ai.pipeline.match import TWord

# กรองคำที่ Whisper มั่วตอนไม่มีเสียงร้อง (ดนตรีล้วน): segment ที่มั่นใจต่ำมากๆ
MIN_AVG_LOGPROB = -1.4
MAX_NO_SPEECH = 0.85


# ข้อความที่ Whisper "มั่ว" ออกมาตอนไม่มีเสียงพูดชัด (เครดิตซับ/คำลงท้ายวิดีโอ จากข้อมูลที่ใช้ฝึก) — ไม่ใช่เนื้อเพลงแน่ๆ
HALLUCINATIONS = ("优独播剧场", "優獨播劇場", "优独播", "字幕志愿者", "字幕由", "請不吝點贊", "请不吝点赞", "订阅", "訂閱", "感谢观看", "感謝觀看", "谢谢观看",
                  "yoyotelevisionseries", "thankyouforwatching", "thanksforwatching", "subtitlesby", "amara.org", "mingpaocanada",
                  "ขอบคุณที่รับชม", "ขอบคุณที่ติดตาม", "ซับไทยโดย")


def is_hallucination(text: str) -> bool:
    import re

    t = re.sub(r"[\W_]+", "", text.casefold())
    return any(re.sub(r"[\W_]+", "", h.casefold()) in t for h in HALLUCINATIONS)


def load_model(config: dict[str, Any], device: str, download_root: str | None = None) -> Any:
    from faster_whisper import WhisperModel

    ctype = str(config.get("compute_type", "float16"))
    if device != "cuda":
        ctype = "int8"
    try:
        return WhisperModel(str(config.get("model", "large-v3-turbo")), device=device, compute_type=ctype, download_root=download_root)
    except Exception:  # noqa: BLE001 — VRAM ไม่พอ/ไม่รองรับ compute type -> ลดระดับ (ข้อ 5.3)
        fb = str(config.get("fallback_compute_type", "int8_float16"))
        if device != "cuda" or fb == ctype:
            raise
        return WhisperModel(str(config.get("model", "large-v3-turbo")), device=device, compute_type=fb, download_root=download_root)


def transcribe_window(model: Any, audio: np.ndarray, language: str | None, config: dict[str, Any], t_offset: float = 0.0,
                      prompt: str | None = None) -> tuple[list[TWord], str | None]:
    """audio = mono 16 kHz float32 · คืน (คำที่เวลาเป็นสัมบูรณ์ = เวลาในช่วง + t_offset, ภาษาที่ตรวจเจอ)"""
    if audio.size < 16000 * 0.5:
        return [], language
    segments, info = model.transcribe(
        audio, language=language, task="transcribe", word_timestamps=True, beam_size=int(config.get("beam_size", 5)),
        temperature=0.0, condition_on_previous_text=False, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350, "speech_pad_ms": 150},
        no_speech_threshold=0.6, compression_ratio_threshold=2.4, log_prob_threshold=-1.0,
        initial_prompt=prompt, without_timestamps=False,
    )
    words: list[TWord] = []
    for seg in segments:
        if seg.avg_logprob < MIN_AVG_LOGPROB or seg.no_speech_prob > MAX_NO_SPEECH or is_hallucination(seg.text):
            continue
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(TWord(text, float(w.start) + t_offset, float(w.end) + t_offset, float(w.probability)))
    return words, getattr(info, "language", language)


def transcribe_full(pipe: Any, audio: np.ndarray, language: str | None, config: dict[str, Any]) -> tuple[list[TWord], str | None]:
    """ถอดเสียงร้องทั้งเพลงครั้งเดียวแบบ batch (faster-whisper BatchedInferencePipeline) — วัดบนเพลง 194 วิ: 3.5 วิ เทียบ 12-16 วิของแบบทีละช่วง
    ตัดตามช่วงมีเสียง (VAD) แล้วถอดหลายช่วงพร้อมกัน · ไม่ต่อเนื่องกับข้อความก่อนหน้า (ไม่วนซ้ำ) · เวลาเป็นเวลาสัมบูรณ์ของเสียงที่ส่งเข้ามา"""
    if audio.size < 16000 * 0.5:
        return [], language
    segments, info = pipe.transcribe(
        audio, language=language, task="transcribe", word_timestamps=True, beam_size=int(config.get("batched_beam", 1)),
        batch_size=int(config.get("batch_size", 8)), temperature=0.0, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350, "speech_pad_ms": 150},
    )
    words: list[TWord] = []
    for seg in segments:
        if seg.avg_logprob < MIN_AVG_LOGPROB or seg.no_speech_prob > MAX_NO_SPEECH or is_hallucination(seg.text):
            continue
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(TWord(text, float(w.start), float(w.end), float(w.probability)))
    words.sort(key=lambda w: w.start)
    return words, getattr(info, "language", language)

