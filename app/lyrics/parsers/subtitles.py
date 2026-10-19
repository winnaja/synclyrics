"""คำบรรยาย YouTube (WebVTT / SRV3) -> Lyrics ทีละบรรทัด

กรองบรรทัดที่ไม่ใช่เนื้อเพลง ([Music], ♪ อย่างเดียว, เสียงประกอบ) และรวมบรรทัดซ้ำที่ซ้อนเวลากัน
"""

from __future__ import annotations

from app.core.models import Lyrics


def parse_vtt(text: str) -> Lyrics:
    """เฟส 1"""
    raise NotImplementedError("เฟส 1")
