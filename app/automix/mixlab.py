"""Mix Lab ในหน้า debug (ข้อ 7.9): เลือก 2 เพลงจาก cache, ฟังตัวอย่าง 20 วิ,
ลองทุกรูปแบบ, เลื่อนจุดเข้าออกเองแล้วบันทึกเป็นค่าของคู่นั้น (pair_overrides), render เป็น WAV
รวมคำสั่ง batch: render คู่ที่ได้ดาวน้อยเพื่อฟังเทียบก่อน/หลังแก้กฎ
"""

from __future__ import annotations

from typing import Any


def render_preview(plan: Any, seconds: float) -> Any:
    """render ช่วงมิกซ์แบบ offline (ใช้ DSP ชุดเดียวกับ engine) — เฟส 7"""
    raise NotImplementedError("เฟส 7")

def batch_render_low_rated(conn: Any, out_dir: str) -> Any:
    """render ทุกคู่ที่ได้ <= 2 ดาว — เฟส 7"""
    raise NotImplementedError("เฟส 7")
