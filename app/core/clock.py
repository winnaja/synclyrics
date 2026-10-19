"""นาฬิกาของเพลง — แหล่งเวลาเดียวที่ UI ใช้ไฮไลต์เนื้อเพลง (ข้อ 3.3: อ่านทุกเฟรม ไม่ใช้ timer)

มี 2 แบบ ใช้ผ่าน protocol `Clock` เหมือนกัน:

1. MediaClock — โหมดแอป: audio engine เป็นคนเขียน (จาก audio callback) UI เป็นคนอ่าน
   เขียนแบบ seqlock ลง numpy array ที่จองไว้ล่วงหน้า ไม่มี lock ไม่จองหน่วยความจำก้อนใหม่
   (ถ้าวันหนึ่งย้าย audio ไปอีก process ใช้ array นี้บน shared_memory ได้เลย)
2. RemoteClock — โหมดคู่หู: ส่วนขยายส่ง currentTime มาเป็นระยะ เราประมาณเวลาระหว่างข้อความ
   ชดเชย latency และค่อยๆ ไล่ให้ตรง (slew) แทนการกระโดด

หน่วยเวลา: วินาที (float) ทั้งหมด, เวลาเครื่องใช้ time.perf_counter()
"""

from __future__ import annotations

import time
from typing import Protocol

import numpy as np


class Clock(Protocol):
    """สิ่งที่ UI ต้องการจากนาฬิกา"""

    def position(self, at: float | None = None) -> float:
        """ตำแหน่งในเพลง (วินาที) ณ เวลาเครื่อง `at` (perf_counter) ค่าเริ่มต้น = ตอนนี้"""
        ...

    @property
    def playing(self) -> bool: ...

    @property
    def generation(self) -> int:
        """เพิ่มทุกครั้งที่ seek / เปลี่ยนเพลง — UI ใช้ตัดสินว่าควร snap แทน animate"""
        ...


# ตำแหน่งช่องใน array ของ MediaClock
_SEQ, _POS, _HOST, _RATE, _PLAYING, _GEN = range(6)


class MediaClock:
    """นาฬิกาที่ audio engine เขียน (writer เดียว) และหลาย thread อ่านได้

    writer เรียก publish() ทุก audio callback:
      media_pos  = ตำแหน่งเพลง ณ sample แรกของ buffer นี้
      host_time  = perf_counter() ตอน callback + output latency (เวลาที่ sample นั้นออกลำโพงจริง)
    """

    __slots__ = ("_buf", "_last_read", "_last_gen")

    def __init__(self, buffer: np.ndarray | None = None) -> None:
        # buffer: ส่ง array จาก shared memory เข้ามาได้ (float64 ยาว 6)
        self._buf = buffer if buffer is not None else np.zeros(6, dtype=np.float64)
        self._last_read = 0.0
        self._last_gen = -1

    # ---------- ฝั่งเขียน (audio callback) ----------
    def publish(self, media_pos: float, host_time: float, rate: float, playing: bool, generation: int) -> None:
        """เขียน snapshot ใหม่ (ห้ามเรียกจากหลาย thread พร้อมกัน)"""
        b = self._buf
        b[_SEQ] += 1.0  # เลขคี่ = กำลังเขียน
        b[_POS] = media_pos
        b[_HOST] = host_time
        b[_RATE] = rate
        b[_PLAYING] = 1.0 if playing else 0.0
        b[_GEN] = generation
        b[_SEQ] += 1.0  # เลขคู่ = เขียนเสร็จ

    # ---------- ฝั่งอ่าน ----------
    def _snapshot(self) -> tuple[float, float, float, bool, int]:
        b = self._buf
        for _ in range(100):
            s1 = b[_SEQ]
            if s1 % 2.0 == 0.0:
                pos, host, rate, playing, gen = b[_POS], b[_HOST], b[_RATE], b[_PLAYING], b[_GEN]
                if b[_SEQ] == s1:
                    return float(pos), float(host), float(rate), playing != 0.0, int(gen)
        # writer ค้างกลางการเขียน (ไม่ควรเกิด) — ใช้ค่าที่อ่านได้ล่าสุด
        return float(b[_POS]), float(b[_HOST]), float(b[_RATE]), b[_PLAYING] != 0.0, int(b[_GEN])

    def position(self, at: float | None = None) -> float:
        """ตำแหน่งเพลงแบบ extrapolate ระหว่าง callback และไม่ถอยหลัง (ภายใน generation เดียวกัน)"""
        now = time.perf_counter() if at is None else at
        pos, host, rate, playing, gen = self._snapshot()
        value = pos + (now - host) * rate if playing else pos
        if gen != self._last_gen:
            self._last_gen = gen
        elif playing and value < self._last_read and self._last_read - value < 0.05:
            # jitter ของจังหวะ callback ทำให้ถอยเล็กน้อยได้ — ยึดค่าเดิมไว้ ภาพจะไม่สั่น
            value = self._last_read
        self._last_read = value
        return max(0.0, value)

    @property
    def playing(self) -> bool:
        return self._snapshot()[3]

    @property
    def generation(self) -> int:
        return self._snapshot()[4]


class RemoteClock:
    """นาฬิกาโหมดคู่หู: ประมาณเวลาจากข้อความของส่วนขยาย

    ส่วนขยายกับโปรแกรมอยู่เครื่องเดียวกัน จึงใช้ wall clock (Date.now() กับ time.time())
    เทียบกันตรงๆ เพื่อหา latency ของแต่ละข้อความได้
    """

    SNAP_THRESHOLD_S = 0.25  # คลาดเกินนี้ = กระโดดไปเลย (seek หรือกระตุก)
    SLEW_TIME_S = 0.5  # คลาดน้อยกว่านั้น ค่อยๆ ไล่ให้ทันภายในเวลานี้

    def __init__(self) -> None:
        self._base_pos = 0.0  # ตำแหน่งที่แสดง ณ _base_host
        self._base_host = time.perf_counter()
        self._rate = 1.0  # rate ของเพลงตาม YouTube
        self._slew = 0.0  # ความเร็วเพิ่ม/ลดชั่วคราวเพื่อไล่ให้ตรง (วินาทีต่อวินาที)
        self._slew_until = 0.0
        self._playing = False
        self._gen = 0

    def update(
        self,
        media_time: float,
        sent_at_epoch_ms: float,
        rate: float,
        paused: bool,
        seeked: bool = False,
        now_host: float | None = None,
        now_epoch: float | None = None,
    ) -> None:
        """รับข้อความจากส่วนขยาย (เรียกจาก thread ของ bridge)"""
        now_host = time.perf_counter() if now_host is None else now_host
        now_epoch = time.time() if now_epoch is None else now_epoch
        latency = max(0.0, min(1.0, now_epoch - sent_at_epoch_ms / 1000.0))
        target = media_time + (0.0 if paused else latency * rate)
        current = self.position(now_host)

        self._rate = rate
        error = target - current
        if seeked or paused != (not self._playing) or abs(error) > self.SNAP_THRESHOLD_S:
            if seeked or abs(error) > self.SNAP_THRESHOLD_S:
                self._gen += 1
            self._base_pos, self._base_host = target, now_host
            self._slew, self._slew_until = 0.0, 0.0
        else:
            self._base_pos, self._base_host = current, now_host
            self._slew = error / self.SLEW_TIME_S
            self._slew_until = now_host + self.SLEW_TIME_S
        self._playing = not paused

    def position(self, at: float | None = None) -> float:
        now = time.perf_counter() if at is None else at
        if not self._playing:
            return max(0.0, self._base_pos)
        dt = max(0.0, now - self._base_host)
        slew_dt = max(0.0, min(dt, self._slew_until - self._base_host))
        return max(0.0, self._base_pos + dt * self._rate + slew_dt * self._slew)

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def generation(self) -> int:
        return self._gen
