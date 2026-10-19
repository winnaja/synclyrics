"""แปลงสัญญาณผู้ใช้เป็นรางวัล -1..+1 (ตารางข้อ 7.5)
ดาวมีน้ำหนักสูงสุดและแทนสัญญาณอัตโนมัติทั้งหมดของการมิกซ์นั้น กดซ้ำใช้ค่าล่าสุด
"""

from __future__ import annotations

from typing import Any


def reward_from_events(events: list[dict[str, Any]], stars: int | None, rules: dict[str, Any]) -> Any:
    """คืนรางวัลสุดท้าย — เฟส 7"""
    raise NotImplementedError("เฟส 7")
