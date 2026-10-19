"""เครื่องมือภาษาไทย: ตัดคำ, นับพยางค์, ตรวจภาษา (ข้อ 3.3)

ตัดคำด้วย pythainlp (engine "newmm") — โหลดครั้งแรกช้า ~1 วิ: warm-up ตอนเปิดโปรแกรมใน background
การวาดสระ/วรรณยุกต์ให้ถูกตำแหน่งเป็นงานของ UI (Qt text shaping ด้วย HarfBuzz)
สิ่งที่ module นี้ต้องรับประกัน: ห้ามตัดคำแยกสระบน/ล่าง/วรรณยุกต์ออกจากพยัญชนะ
(ตัด grapheme cluster เท่านั้น — ใช้ตอน Typewriter และ wipe ทีละตัวอักษร)
"""

from __future__ import annotations


def tokenize(text: str) -> list[str]:
    """ตัดคำไทยปนอังกฤษ คืนรายการคำ (ช่องว่างไม่รวม) — เฟส 1"""
    raise NotImplementedError("เฟส 1")


def syllable_count(word: str) -> int:
    """จำนวนพยางค์โดยประมาณ (ไทยใช้ pythainlp, อังกฤษนับกลุ่มสระ) — เฟส 1"""
    raise NotImplementedError("เฟส 1")


def graphemes(text: str) -> list[str]:
    """แยกเป็นกลุ่มตัวอักษรที่ห้ามแยกกัน (พยัญชนะ + สระบน/ล่าง + วรรณยุกต์) — เฟส 1"""
    raise NotImplementedError("เฟส 1")


def detect_language(text: str) -> str | None:
    """เดาภาษาจากสัดส่วนอักษร ("th", "en", "ja", "ko", "zh") — เฟส 1"""
    raise NotImplementedError("เฟส 1")
