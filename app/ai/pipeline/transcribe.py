"""faster-whisper large-v3-turbo (word_timestamps=True) — ข้อ 5.1 ขั้น 6, ข้อ 4.2 ข้อ 7

ใช้ 2 กรณี: (ก) ไม่เจอเนื้อเพลงที่ไหนเลย -> ถอดทั้งเพลง (ข) เนื้อเพลงไม่มีเวลา -> หาเวลาบรรทัดก่อน align
VRAM ไม่พอ: int8_float16 หรือโหลดเฉพาะตอนใช้แล้ว unload (models.yaml)
"""

from __future__ import annotations

from typing import Any


def transcribe(pcm: Any, sample_rate: int, language: str | None, config: dict[str, Any]) -> Any:
    """คืนบรรทัด + คำ + เวลา — เฟส 4"""
    raise NotImplementedError("เฟส 4")

def match_lines(transcript: Any, lines: list[str]) -> Any:
    """จับคู่บรรทัดเนื้อเพลงที่ไม่มีเวลากับ transcript เพื่อหาเวลาบรรทัด — เฟส 4"""
    raise NotImplementedError("เฟส 4")
