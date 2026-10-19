"""LyricsModel — QAbstractListModel ของบรรทัดเนื้อเพลงสำหรับ QML (ส่วนที่ 3.3)

role ต่อบรรทัด: start, end, voice, words (list ของ {text, start, end, timing}), translation, romanization
อัปเกรดเวลาจาก AI ทีละช่วง (LYRICS_TIMING_UPDATED): emit dataChanged เฉพาะบรรทัดที่เปลี่ยน
QML ทำ morph เวลาเก่า -> ใหม่แบบ smooth (ห้ามกระโดด)
"""

from __future__ import annotations


class LyricsModel:
    """เฟส 1 (จะสืบทอด QAbstractListModel — import PySide6 ภายในเฟส 1)"""
