"""LRC และ Enhanced LRC (A2 extension: <mm:ss.xx> ทีละคำ)

ใช้ทั้งอ่าน (LRCLIB) และเขียน (export จาก Tap Sync ข้อ 9.4)
รองรับ: [offset:+/-ms], หลาย timestamp ต่อบรรทัด, บรรทัดว่าง = ช่วงดนตรี, [ar:] [ti:] [length:]
"""

from __future__ import annotations

from app.core.models import Lyrics


def parse_lrc(text: str, source: str = "lrc") -> Lyrics:
    """แปลง LRC/Enhanced LRC เป็น Lyrics (timing = WORD ถ้ามีเวลาทีละคำครบ) — เฟส 1"""
    raise NotImplementedError("เฟส 1")


def to_enhanced_lrc(lyrics: Lyrics) -> str:
    """เขียน Lyrics เป็น Enhanced LRC (ใช้ export ใน Tap Sync) — เฟส 8"""
    raise NotImplementedError("เฟส 8")
