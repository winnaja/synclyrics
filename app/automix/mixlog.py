"""บันทึกการมิกซ์ลง SQLite (ตาราง mixes / mix_events) + log เหตุผลแบบละเอียด (ข้อ 7.9)
และสร้าง "รายงานมิกซ์ที่ไม่เพราะ" เป็นข้อความพร้อมส่งให้ AI
"""

from __future__ import annotations

from typing import Any


def record_mix(conn: Any, plan: Any, context: Any, decision_log: dict[str, Any]) -> Any:
    """เพิ่มแถวใน mixes คืน mix_id — เฟส 6"""
    raise NotImplementedError("เฟส 6")

def add_event(conn: Any, mix_id: int, kind: str, value: float) -> Any:
    """บันทึกสัญญาณอัตโนมัติ — เฟส 7"""
    raise NotImplementedError("เฟส 7")

def bad_mix_report(conn: Any, rules_text: str) -> Any:
    """รวมข้อมูลมิกซ์ที่ได้ดาวน้อย + เหตุผล + rules + สถิติ — เฟส 7"""
    raise NotImplementedError("เฟส 7")
