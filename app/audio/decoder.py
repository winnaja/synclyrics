"""ถอดรหัสไฟล์เสียงเป็น PCM float32 ด้วย ffmpeg (subprocess) แบบทยอย

ffmpeg -i <ไฟล์จาก yt-dlp> -f f32le -ac 2 -ar <engine rate> pipe:1
อ่าน stdout ทีละก้อน เขียนลง PcmBuffer (memmap .f32) แล้วเพิ่ม frames_ready
-> deck เริ่มเล่นได้เมื่อมีเสียงพอ ~2 วิ ไม่ต้องรอถอดรหัสทั้งเพลง (เป้าหมาย: เริ่มภายใน 3 วิ)

ffmpeg: หา bin/ffmpeg.exe ข้างโปรแกรมก่อน (ตัวติดตั้งรวมไว้) แล้วค่อย PATH
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.audio.deck import PcmBuffer


@dataclass(slots=True)
class DecodeJob:
    source: Path | str          # ไฟล์ที่ yt-dlp โหลดมา (หรือ URL สตรีม)
    target: Path                # <cache>/audio/<videoId>.f32
    sample_rate: int
    duration_s: float           # ใช้จองขนาด memmap ล่วงหน้า (+ เผื่อ 2 วิ)
    http_headers: dict[str, str] | None = None


class Decoder:
    """ตัวถอดรหัสหนึ่งงาน รันใน thread ของตัวเอง ยกเลิกได้"""

    def __init__(self, job: DecodeJob, on_progress: Callable[[int], None] | None = None) -> None:
        self.job = job
        self.on_progress = on_progress
        self.buffer: PcmBuffer | None = None

    def start(self) -> PcmBuffer:
        """เริ่ม ffmpeg และคืน PcmBuffer ทันที (ข้อมูลจะทยอยมา) — เฟส 1"""
        raise NotImplementedError("เฟส 1")

    def cancel(self) -> None:
        """ฆ่า ffmpeg และลบไฟล์ที่ยังไม่สมบูรณ์ — เฟส 1"""
        raise NotImplementedError("เฟส 1")


def find_ffmpeg() -> Path | None:
    """หา ffmpeg.exe — เฟส 1"""
    raise NotImplementedError("เฟส 1")
