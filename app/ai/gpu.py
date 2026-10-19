"""ข้อมูล GPU สำหรับ health check, หน้า debug และการตัดสินใจลดขนาดโมเดล

ใช้ pynvml (nvidia-ml-py) — อ่านได้จาก process หลักโดยไม่ต้อง import torch
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GpuInfo:
    name: str
    driver: str
    vram_total_mb: int
    vram_used_mb: int


def query_gpu() -> GpuInfo | None:
    """None = ไม่มี NVIDIA GPU / ไม่มีไดรเวอร์ — เฟส 4 (หน้า debug เฟส 8)"""
    raise NotImplementedError("เฟส 4")
