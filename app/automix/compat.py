"""คะแนนความเข้ากัน 0-100 ระหว่างเพลง A และ B (ข้อ 7.2)
น้ำหนักและเกณฑ์ทั้งหมดอ่านจาก automix_rules.yaml หมวด compatibility
"""

from __future__ import annotations

from typing import Any


def compatibility(a: Any, b: Any, rules: dict[str, Any]) -> Any:
    """คืน (คะแนน, รายละเอียดแต่ละด้าน) — เฟส 6"""
    raise NotImplementedError("เฟส 6")

def camelot_distance(a: str, b: str) -> Any:
    """ระยะบน Camelot wheel -> ชื่อกลุ่ม same/adjacent/two_steps/energy_boost/other — เฟส 6"""
    raise NotImplementedError("เฟส 6")
