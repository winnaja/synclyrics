"""DSP แบบ block สำหรับ callback: biquad (EQ 3 ย่าน, HP/LP), echo, limiter (ข้อ 7.4)

ทุกตัวต้อง:
  - จองหน่วยความจำ (state, scratch) ตอนสร้างเท่านั้น
  - process(block) ทำงานแบบ in-place
  - เปลี่ยน coefficient ได้ทุก block (ค่ามาจาก automation lane) โดยไม่เกิดคลิก
ประสิทธิภาพ: biquad ต่อ sample ด้วย Python loop ช้าเกินไป — ทางเลือกคือ scipy.signal.lfilter
พร้อม zi หรือ numba; ตัดสินในเฟส 5 จากผลวัดจริง (บันทึกลง DECISIONS.md)
"""

from __future__ import annotations

import numpy as np


class Biquad:
    """biquad filter สเตอริโอ (RBJ cookbook) — เฟส 5"""

    def __init__(self, sample_rate: int, kind: str, freq_hz: float, gain_db: float = 0.0, q: float = 0.707) -> None:
        self.sample_rate = sample_rate
        self.kind = kind  # "lowshelf" | "peaking" | "highshelf" | "highpass" | "lowpass"
        self.freq_hz = freq_hz
        self.gain_db = gain_db
        self.q = q

    def set_params(self, freq_hz: float, gain_db: float = 0.0) -> None:
        raise NotImplementedError("เฟส 5")

    def process(self, block: np.ndarray) -> None:
        raise NotImplementedError("เฟส 5")


class ThreeBandEq:
    """EQ 3 ย่าน (low shelf ~200Hz / peaking ~1kHz / high shelf ~4kHz) — เฟส 5"""


class Echo:
    """delay/echo ซิงก์กับ beat (ความยาวเป็นจำนวน beat) — เฟส 6"""


class Limiter:
    """limiter ท้ายสุดกันเสียงแตก (peak, attack สั้น release ~100ms) — เฟส 1 แบบง่าย"""

    def __init__(self, sample_rate: int, ceiling_db: float = -1.0) -> None:
        self.sample_rate = sample_rate
        self.ceiling = float(10 ** (ceiling_db / 20))
        self.gain = 1.0

    def process(self, block: np.ndarray) -> None:
        raise NotImplementedError("เฟส 1")
