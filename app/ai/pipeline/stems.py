"""แยก stems ด้วย Demucs htdemucs (fp16, segment ~7 วิ) ทีละช่วงของเพลง

ผล: cache/stems/<videoId>/vocals.f32 และ instrumental.f32 (เขียนเฉพาะช่วงที่ทำแล้ว)
ช่วงที่ซ้อนกันหัวท้ายใช้ crossfade รวมกัน กันรอยต่อ
"""

from __future__ import annotations

from typing import Any


def separate_range(model: Any, pcm_path: str, sample_rate: int, start: float, end: float, out_dir: str) -> Any:
    """แยก stems ช่วง [start, end) แล้วเขียนลงไฟล์ stems — เฟส 4"""
    raise NotImplementedError("เฟส 4")

def load_model(config: dict[str, Any], device: str) -> Any:
    """โหลด htdemucs ค้างไว้ใน VRAM — เฟส 4"""
    raise NotImplementedError("เฟส 4")
