"""forced alignment ทีละบรรทัดด้วย torchaudio MMS_FA (ข้อ 5.1 ขั้น 6)

1. normalize ข้อความ: ไทย/ภาษาที่ไม่ใช่ละติน -> uroman เป็นละติน (เก็บ map กลับคำเดิม)
2. ตัดเสียง vocals ตามช่วงบรรทัด (+ขอบ) แล้ว batch หลายบรรทัด (fp16)
3. forced_align -> token spans -> รวมเป็นคำ -> map กลับคำเดิม
4. confidence ต่อคำ = ค่าเฉลี่ย prob ของ token; ต่ำกว่า min_confidence ใช้เวลาแบบประมาณ
torchaudio ต้องเป็น 2.11 (ดู requirements-ai.txt)
"""

from __future__ import annotations

from typing import Any


def load_model(config: dict[str, Any], device: str) -> Any:
    """โหลด MMS_FA bundle — เฟส 4"""
    raise NotImplementedError("เฟส 4")

def align_lines(model: Any, vocals: Any, sample_rate: int, lines: list[dict[str, Any]], language: str | None) -> Any:
    """คืนเวลาทีละคำ + confidence ต่อบรรทัด — เฟส 4"""
    raise NotImplementedError("เฟส 4")

def romanize(words: list[str], language: str | None) -> Any:
    """แปลงคำเป็นละตินด้วย uroman พร้อม map index กลับ — เฟส 4"""
    raise NotImplementedError("เฟส 4")
