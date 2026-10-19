"""ตรวจและแก้ offset ระหว่างเนื้อเพลงกับเสียงอัตโนมัติ (ข้อ 5.1 ขั้น 7)
เช่น MV มีช่วงเปิดเรื่อง 15 วิ แต่เนื้อเพลงอิงเวอร์ชัน audio
วิธี: cross-correlate เวลาบรรทัดกับ vocal activity หาค่า shift ที่ดีที่สุด
"""

from __future__ import annotations

from typing import Any


def estimate_offset(line_starts: list[float], vocal_segments: list[tuple[float, float]]) -> Any:
    """คืน (offset วินาที, confidence) — เฟส 4"""
    raise NotImplementedError("เฟส 4")
