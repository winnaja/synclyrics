"""Deck = เครื่องเล่นหนึ่งช่อง (มี 2 ตัว: A/B สลับกันไปเรื่อยๆ ข้อ 7.4)

ข้อมูลเสียง: PCM float32 interleaved stereo ที่ sample rate ของ engine
เก็บเป็นไฟล์ <videoId>.f32 ใน cache แล้ว np.memmap — ทั้ง deck และ AI worker อ่านไฟล์เดียวกัน
(ห้ามโหลดซ้ำ ข้อ 5.1 ขั้น 1) และ decoder เขียนต่อท้ายไปเรื่อยๆ ได้ (เล่นก่อนถอดรหัสเสร็จ)

PlaybackProgram: รายการ Segment ที่ deck เล่นตามลำดับ ใช้ทำ time-stretch แบบ render ล่วงหน้า
เช่น intro ของเพลง B ที่ยืดด้วย Rubber Band (buffer แยก) แล้วต่อด้วยต้นฉบับ
callback จึงไม่ต้อง resample เลย และนาฬิกาเพลงยังถูกต้องเพราะทุก Segment บอก media time ของมัน
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

from app.audio.automation import AutomationLane, Param


class PcmBuffer:
    """PCM ของเพลงหนึ่งเพลง (อาจยังถอดรหัสไม่เสร็จ)

    frames_ready เพิ่มขึ้นเรื่อยๆ จาก decoder thread — callback อ่านค่า int นี้อย่างเดียว
    ถ้าเล่นถึงส่วนที่ยังไม่พร้อม: deck ส่งความเงียบ และนับ starvation (ไม่ใช่ underrun ของอุปกรณ์)
    """

    def __init__(self, data: np.ndarray, sample_rate: int, path: Path | None = None) -> None:
        if data.ndim != 2 or data.shape[1] != 2 or data.dtype != np.float32:
            raise ValueError("PCM ต้องเป็น float32 รูป (frames, 2)")
        self.data = data
        self.sample_rate = sample_rate
        self.path = path
        self.frames_ready = 0  # เขียนโดย decoder เท่านั้น
        self.complete = False
        self.total_frames = data.shape[0]

    @staticmethod
    def open_file(path: Path, sample_rate: int, total_frames: int) -> "PcmBuffer":
        """เปิดไฟล์ .f32 แบบ memmap (สร้างไฟล์ขนาดเต็มไว้ก่อนถ้ายังไม่มี)"""
        mode = "r+" if path.exists() else "w+"
        mm = np.memmap(path, dtype=np.float32, mode=mode, shape=(total_frames, 2))
        return PcmBuffer(mm, sample_rate, path)

    @staticmethod
    def from_array(data: np.ndarray, sample_rate: int) -> "PcmBuffer":
        """สร้าง buffer จาก array ที่พร้อมทั้งหมดแล้ว (ใช้ใน test/render) — complete และ frames_ready เต็ม"""
        buf = PcmBuffer(np.ascontiguousarray(data, dtype=np.float32), sample_rate)
        buf.frames_ready = buf.total_frames
        buf.complete = True
        return buf


def full_program(buffer: PcmBuffer, media_start_s: float = 0.0) -> "list[Segment]":
    """program มี Segment เดียวครอบทั้ง buffer (เล่นต้นฉบับตรงๆ ไม่ stretch)

    src_end ใช้ total_frames ของ buffer — ถ้า buffer ยังถอดรหัสไม่เสร็จ total_frames คือค่าประมาณ
    (ขนาด memmap) deck จะรอ/เงียบตาม frames_ready และจบเมื่อ complete แล้วถึงเฟรมสุดท้ายจริง
    """
    return [Segment(buffer, 0, buffer.total_frames, media_start_s, 1.0)]


@dataclass(slots=True)
class Segment:
    """ช่วงของ PCM ที่จะเล่น พร้อมการ map ไปเวลาของเพลงต้นฉบับ"""

    buffer: PcmBuffer
    src_start: int          # frame เริ่มใน buffer
    src_end: int            # frame จบ (ไม่รวม)
    media_start_s: float    # เวลาเพลงต้นฉบับ ณ src_start
    media_rate: float = 1.0  # เวลาต้นฉบับเดินกี่วินาทีต่อ 1 วินาทีที่เล่น (stretch แล้ว != 1)


class DeckState(str, Enum):
    EMPTY = "empty"
    LOADING = "loading"   # มี buffer แต่ยังไม่พอเริ่มเล่น
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    ENDED = "ended"


@dataclass(slots=True)
class Deck:
    """สถานะของ deck — ถูกแก้ใน callback เท่านั้น (ฝั่งอื่นสั่งผ่านคิวคำสั่งของ engine)"""

    deck_id: int  # 0 = A, 1 = B
    video_id: str | None = None
    state: DeckState = DeckState.EMPTY
    program: list[Segment] = field(default_factory=list)
    seg_index: int = 0
    seg_pos: int = 0  # frame ภายใน segment ปัจจุบัน
    generation: int = 0  # +1 ทุกครั้ง seek/โหลดเพลงใหม่ (ส่งต่อให้ MediaClock)
    lanes: dict[Param, AutomationLane] = field(default_factory=dict)
    # ค่าปัจจุบันของพารามิเตอร์ (ใช้ตอนไม่มี lane) — เริ่มจาก automation.DEFAULTS
    static: dict[Param, float] = field(default_factory=dict)

    def media_position(self) -> float:
        """เวลาเพลงต้นฉบับ (วินาที) ณ ตำแหน่งปัจจุบัน"""
        if not self.program:
            return 0.0
        seg = self.program[min(self.seg_index, len(self.program) - 1)]
        return seg.media_start_s + (self.seg_pos / seg.buffer.sample_rate) * seg.media_rate
