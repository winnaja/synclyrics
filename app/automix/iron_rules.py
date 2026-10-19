"""กฎเหล็ก (ข้อ 7.1) — ด่านสุดท้ายก่อนใช้ action ใดๆ รวมถึงตอนระบบเรียนรู้ทดลอง

ทุกฟังก์ชันที่นี่ต้องเป็น pure function (ไม่มี I/O) และมี test ครบทุกข้อ
ถ้า action ไม่ผ่าน: ตัดออกจากตัวเลือก ถ้าไม่เหลืออะไรเลย -> CLEAN_CUT (ผ่านทุกกฎเสมอ)

กฎ:
  1. ห้ามเสียงร้องสองเพลงทับกัน (vocal_segments ของ A ช่วงท้าย vs ของ B ช่วงต้น + vocal_guard_s)
  2. เพลง A จบแบบ fade/โน้ตลากยาว: ห้ามตัด ให้ซ้อน B เข้ามาช่วงท้ายเท่านั้น
  3. ห้ามมิกซ์ทับประโยคสุดท้ายของเนื้อเพลง A
  4. beat_confidence ต่ำ -> ห้าม beatmatch_blend / bass_swap
  5. ห้ามปรับ tempo เกิน max_tempo_change_pct ของผู้ใช้
  6. ไม่ใช่เพลง (ยาวเกิน 15 นาที / ไม่มี beat) -> เฟดธรรมดาเท่านั้น
  7. เพลงที่ตั้ง "ห้ามมิกซ์" -> เล่นจนจบแล้วต่อแบบเรียบ
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RuleViolation:
    rule: str      # ชื่อกฎ เช่น "vocal_overlap"
    detail: str    # ข้อความภาษาไทยสำหรับ decision_log


def check_action(action: Any, a: Any, b: Any, plan_times: Any, settings: Any, rules: dict[str, Any]) -> list[RuleViolation]:
    """คืนรายการกฎที่ action นี้ละเมิด (ว่าง = ผ่าน) — เฟส 6"""
    raise NotImplementedError("เฟส 6")


def allowed_actions(candidates: list[Any], a: Any, b: Any, settings: Any, rules: dict[str, Any]) -> tuple[list[Any], dict[str, list[RuleViolation]]]:
    """กรองเหลือเฉพาะ action ที่ผ่านทุกกฎ คืน (ที่ผ่าน, เหตุผลที่ตัดแต่ละตัว) — เฟส 6"""
    raise NotImplementedError("เฟส 6")
