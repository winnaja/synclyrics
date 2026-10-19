"""QRC ของ QQ Music: ข้อมูลเข้ารหัส (3DES ด้วย key สาธารณะที่ชุมชนรู้กัน) + zlib
หลังถอดได้ XML ที่มี LyricContent: [line_start,line_dur]คำ(word_start,word_dur)...
"""

from __future__ import annotations

from app.core.models import Lyrics


def decrypt_qrc(hex_payload: str) -> str:
    """เฟส 1"""
    raise NotImplementedError("เฟส 1")


def parse_qrc(text: str, translation_lrc: str | None = None) -> Lyrics:
    """เฟส 1"""
    raise NotImplementedError("เฟส 1")
