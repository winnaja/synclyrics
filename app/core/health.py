"""ตรวจสุขภาพตอนเปิดโปรแกรม (ข้อ 11.2) — GPU, ffmpeg, yt-dlp, cookies, ส่วนขยาย, เน็ต

ทุกการตรวจคืน HealthItem พร้อมวิธีแก้ภาษาไทย รันใน background ไม่บล็อกการเปิดโปรแกรม
ผลแสดงในหน้า debug และแจ้งเตือนเฉพาะรายการที่ status = "error"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["ok", "warn", "error", "skipped"]


@dataclass(slots=True)
class HealthItem:
    key: str          # "gpu", "ffmpeg", "ytdlp", "cookies", "extension", "network", "audio_device"
    status: Status
    message: str      # สิ่งที่เจอ
    fix: str = ""     # วิธีแก้ที่คนทั่วไปทำตามได้


def run_all() -> list[HealthItem]:
    """เฟส 1 (ffmpeg, yt-dlp, เน็ต, เสียง) / เฟส 2 (ส่วนขยาย) / เฟส 4 (GPU) / เฟส 8 (ครบ + UI)"""
    raise NotImplementedError("เฟส 1")
