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


def _s(x: object) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def query_gpu() -> GpuInfo | None:
    """None = ไม่มี NVIDIA GPU / ไม่มีไดรเวอร์ / อ่านไม่ได้ (ห้าม raise — ผู้เรียกใช้แสดง "ไม่มี GPU")"""
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            return GpuInfo(name=_s(pynvml.nvmlDeviceGetName(h)), driver=_s(pynvml.nvmlSystemGetDriverVersion()),
                           vram_total_mb=int(mem.total // 2**20), vram_used_mb=int(mem.used // 2**20))
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001
        return None
