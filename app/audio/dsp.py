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
    """limiter ท้ายสุดกันเสียงแตก (peak, attack ทันที release ~100ms) — เฟส 1 แบบง่าย

    หลักการ: คำนวณ gain เป้าหมายต่อ block = ceiling / peak
      - ถ้าต้องลด gain: ลดทันที (ไล่ลงภายใน ~1ms แรกของ block) ไม่ให้ peak ทะลุเพดาน
      - ถ้าปล่อย gain กลับ: ค่อยๆ ไต่ขึ้นแบบ exponential ด้วยเวลา release
      - สุดท้าย np.clip เป็นด่านสุดท้าย รับประกันว่าไม่เกินเพดานแน่นอน
    ถ้า gain == 1 และ peak ไม่เกินเพดาน: ไม่แตะข้อมูลเลย (bit-exact)
    ไม่จองหน่วยความจำใน process() — scratch จองใน __init__ ตาม max_block
    """

    RELEASE_S = 0.1   # เวลาปล่อย gain กลับ
    ATTACK_S = 0.001  # ช่วงไล่ gain ลงต้น block (กันคลิก ส่วนที่เหลือ clip ช่วย)

    def __init__(self, sample_rate: int, ceiling_db: float = -1.0, max_block: int = 8192) -> None:
        self.sample_rate = sample_rate
        self.ceiling = float(10 ** (ceiling_db / 20))
        self.gain = 1.0
        self.gain_reduction_db = 0.0  # ค่าลดล่าสุด (dB, >= 0) สำหรับหน้า debug
        self.max_block = max_block
        self._abs = np.zeros((max_block, 2), dtype=np.float32)
        self._ramp = np.zeros((max_block, 1), dtype=np.float32)
        self._idx = np.arange(max_block, dtype=np.float32).reshape(-1, 1)

    def _ramp_gain(self, block: np.ndarray, n: int, g0: float, g1: float) -> None:
        """คูณ block ด้วย gain ที่ไล่เส้นตรงจาก g0 ไป g1 ตลอด n sample (in-place ไม่จองใหม่)"""
        ramp = self._ramp[:n]
        np.multiply(self._idx[:n], (g1 - g0) / n, out=ramp)
        np.add(ramp, g0, out=ramp)
        np.multiply(block, ramp, out=block)

    def process(self, block: np.ndarray) -> None:
        """ประมวลผล block float32 (n, 2) แบบ in-place; block ยาวกว่า max_block จะแบ่งทำทีละชิ้น"""
        total = block.shape[0]
        start = 0
        while start < total:
            end = min(total, start + self.max_block)
            self._process_chunk(block[start:end])
            start = end

    def _process_chunk(self, block: np.ndarray) -> None:
        n = block.shape[0]
        if n == 0:
            return
        absb = self._abs[:n]
        np.abs(block, out=absb)
        peak = float(absb.max())
        ceiling = self.ceiling
        if not np.isfinite(peak):
            # NaN/inf หลุดมา: แทนด้วยค่าปลอดภัยแล้วคำนวณ peak ใหม่ (ไม่จองหน่วยความจำ)
            np.nan_to_num(block, nan=0.0, posinf=ceiling, neginf=-ceiling, copy=False)
            np.abs(block, out=absb)
            peak = float(absb.max())
        g0 = self.gain
        target = ceiling / peak if peak > ceiling else 1.0

        if target < g0:
            # attack ทันที: ไล่ลงภายใน ATTACK_S แล้วคงที่ที่ target
            g1 = target
            att = min(n, max(1, int(self.sample_rate * self.ATTACK_S)))
            self._ramp_gain(block[:att], att, g0, g1)
            if att < n:
                np.multiply(block[att:], g1, out=block[att:])
        else:
            # release: ไต่ขึ้นหา target แบบ exponential (ไม่เกิน target จึงไม่ทะลุเพดาน)
            g1 = target - (target - g0) * float(np.exp(-n / (self.RELEASE_S * self.sample_rate)))
            if g1 >= 1.0 - 1e-6:
                g1 = 1.0
            if g0 != 1.0 or g1 != 1.0:
                self._ramp_gain(block, n, g0, g1)

        self.gain = g1
        # ด่านสุดท้าย: ห้ามเกินเพดาน (กรณี ramp ต้น block หรือค่า NaN/inf)
        if peak > ceiling:
            np.clip(block, -ceiling, ceiling, out=block)
        self.gain_reduction_db = 0.0 if g1 >= 1.0 else -20.0 * float(np.log10(g1))
