"""หาช่วงที่มีเสียงร้องจาก stem vocals (ข้อ 5.1 ขั้น 5)
RMS ต่อ frame + hysteresis + รวมช่วงที่ห่างกันน้อยกว่า 0.3 วิ — AutoMix ใช้กันเสียงร้องทับกัน (ข้อ 7.1)
"""

from __future__ import annotations

from typing import Any


def vocal_segments(vocals: Any, sample_rate: int) -> Any:
    """คืน [(start, end), ...] — เฟส 4"""
    raise NotImplementedError("เฟส 4")
