"""YRC ของ NetEase: [line_start_ms,line_dur_ms](word_start_ms,word_dur_ms,0)คำ...

บรรทัดที่ขึ้นต้นด้วย {"t":..,"c":[..]} เป็น metadata (ผู้แต่ง/ผู้เรียบเรียง) ต้องข้าม
รวมคำแปลจาก tlyric (LRC) เข้ากับบรรทัดตามเวลาที่ใกล้ที่สุด
"""

from __future__ import annotations

from app.core.models import Lyrics


def parse_yrc(text: str, translation_lrc: str | None = None) -> Lyrics:
    """เฟส 1"""
    raise NotImplementedError("เฟส 1")
