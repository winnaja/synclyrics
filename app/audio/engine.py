"""AudioEngine — หัวใจของโปรแกรม: เสียงห้ามสะดุดเด็ดขาด (ARCHITECTURE.md §3)

โครงสร้าง thread:
  - PortAudio callback thread (sounddevice, WASAPI shared): เรียก _callback ทุก ~10-20ms
  - engine control thread: จัดการ underrun (เปิด stream ใหม่ด้วย buffer ใหญ่ขึ้น), log สถิติ
  - ฝั่งอื่น (player, UI) เรียกเมธอดสาธารณะได้จากทุก thread — เมธอดเหล่านี้แค่ใส่คำสั่งลง deque

กฎเหล็กของ _callback (ห้ามละเมิด — ละเมิดแล้วเสียงกระตุกแบบหาสาเหตุยาก):
  1. ห้าม lock / ห้าม I/O / ห้าม log / ห้ามเรียก DB / ห้ามรอ queue แบบบล็อก
  2. ห้ามจอง numpy array ใหม่ — ใช้ scratch buffer ที่จองไว้ตอนเปิด stream และ out= ทุกครั้ง
  3. คำสั่งจากภายนอกอ่านจาก collections.deque ด้วย popleft() (atomic ใน CPython ไม่ต้อง lock)
  4. exception ใน callback: ส่งความเงียบ + เพิ่มตัวนับ error (control thread เป็นคน log)
  5. งานที่หนักกว่า "ก็อป PCM + คูณ gain + filter ต่อ block" ต้องทำล่วงหน้านอก callback

GIL: AI อยู่คนละ process แล้ว งาน CPU ใน process หลักต้องแบ่งเป็นชิ้นสั้น (<5ms ต่อชิ้น)
engine ตั้ง sys.setswitchinterval(0.001) ให้ callback ได้ GIL เร็ว — ดู docs/DECISIONS.md

sample rate ของ engine = sample rate เริ่มต้นของอุปกรณ์เสียง (มักเป็น 48000)
decoder resample ให้ตรงตั้งแต่ถอดรหัส callback จึงไม่ต้อง resample
"""

from __future__ import annotations

import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.audio.automation import AutomationLane
from app.audio.deck import Deck, Segment
from app.core.clock import MediaClock

CHANNELS = 2
DTYPE = "float32"


@dataclass(slots=True)
class EngineStats:
    """สถิติสำหรับหน้า debug (callback เขียนเฉพาะตัวเลข)"""

    callbacks: int = 0
    underruns: int = 0          # output_underflow จากอุปกรณ์
    starvations: int = 0        # เล่นถึงส่วนที่ decoder ยังถอดรหัสไม่ถึง
    callback_errors: int = 0
    max_callback_ms: float = 0.0
    limiter_gain_reduction_db: float = 0.0
    blocksize: int = 0
    latency_ms: float = 0.0
    sample_rate: int = 0


@dataclass(slots=True)
class EngineConfig:
    device: str | int | None = None  # None = อุปกรณ์เริ่มต้นของ Windows
    buffer_ms: int = 15              # เริ่มต้น 10-20ms (ข้อ 7.4)
    max_buffer_ms: int = 120         # underrun ซ้ำๆ เพิ่มได้ถึงเท่านี้
    master_volume: float = 1.0
    limiter_ceiling_db: float = -1.0


class AudioEngine:
    """เครื่องเล่น 2 deck — API ทุกตัว thread-safe และไม่บล็อก"""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.decks: tuple[Deck, Deck] = (Deck(0), Deck(1))
        # นาฬิกาแยกต่อ deck: ระหว่างมิกซ์มีสองเพลงพร้อมกัน UI อ่านของ deck ที่กำลังแสดงเนื้อเพลง
        self.clocks: tuple[MediaClock, MediaClock] = (MediaClock(), MediaClock())
        self.stats = EngineStats()
        self.frames_rendered: int = 0  # เวลา engine (frame) — automation และ play(at_frame) อ้างอิงค่านี้
        self._commands: deque[tuple[str, Any]] = deque()
        self._stream: Any = None
        self._scratch: np.ndarray | None = None  # จองตอนเปิด stream ขนาด max blocksize
        sys.setswitchinterval(0.001)

    # ------------------------------------------------------------------
    # วงจรชีวิต
    # ------------------------------------------------------------------
    def start(self) -> None:
        """เปิด output stream (WASAPI shared) และ control thread — เฟส 1"""
        raise NotImplementedError("เฟส 1")

    def stop(self) -> None:
        raise NotImplementedError("เฟส 1")

    def set_device(self, device: str | int | None) -> None:
        """เปลี่ยนอุปกรณ์เสียงขาออก (เปิด stream ใหม่ เสียงขาดสั้นๆ ยอมรับได้) — เฟส 1"""
        raise NotImplementedError("เฟส 1")

    @property
    def sample_rate(self) -> int:
        return self.stats.sample_rate

    # ------------------------------------------------------------------
    # คำสั่ง (ใส่คิว — callback ทำตามที่ต้น block ถัดไป)
    # ------------------------------------------------------------------
    def load(self, deck_id: int, video_id: str, program: list[Segment]) -> None:
        """โหลดเพลงลง deck (ยังไม่เล่น)"""
        self._commands.append(("load", (deck_id, video_id, program)))

    def play(self, deck_id: int, at_frame: int | None = None) -> None:
        """เริ่มเล่นทันที หรือ ณ เวลา engine at_frame (แม่นระดับ sample — ใช้ตอนมิกซ์)"""
        self._commands.append(("play", (deck_id, at_frame)))

    def pause(self, deck_id: int) -> None:
        self._commands.append(("pause", deck_id))

    def seek(self, deck_id: int, media_time_s: float) -> None:
        """กระโดดไปเวลาเพลง (fade สั้น 5ms กันคลิก) generation ของนาฬิกา +1"""
        self._commands.append(("seek", (deck_id, media_time_s)))

    def set_lanes(self, deck_id: int, lanes: list[AutomationLane]) -> None:
        """ติดตั้ง automation ที่คำนวณไว้ล่วงหน้า (แทนที่ lane เดิมของพารามิเตอร์เดียวกัน)"""
        self._commands.append(("lanes", (deck_id, lanes)))

    def clear_deck(self, deck_id: int) -> None:
        """ล้าง deck หลังมิกซ์จบ (รอเพลงถัดไป)"""
        self._commands.append(("clear", deck_id))

    def set_master_volume(self, volume: float) -> None:
        """ระดับเสียงรวม (ramp 20ms กันคลิก)"""
        self._commands.append(("volume", float(volume)))

    # ------------------------------------------------------------------
    # callback (ดูกฎด้านบน)
    # ------------------------------------------------------------------
    def _callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """mix 2 deck -> master gain -> limiter -> outdata  (เฟส 1: deck เดียว, เฟส 5: 2 deck)

        ลำดับในแต่ละ block:
          1. ทำคำสั่งที่ค้างใน deque
          2. ต่อ deck: ก็อป PCM ตาม program -> automation (gain ramp ต่อ sample, EQ/filter ต่อ block)
          3. รวมสอง deck -> master volume -> limiter
          4. publish นาฬิกาของแต่ละ deck: host_time = perf_counter() + output latency
          5. frames_rendered += frames
        """
        raise NotImplementedError("เฟส 1")


@dataclass(slots=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    default_samplerate: float
    is_default: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def list_output_devices() -> list[DeviceInfo]:
    """รายชื่ออุปกรณ์เสียงขาออก (WASAPI บน Windows) — เฟส 1"""
    raise NotImplementedError("เฟส 1")
