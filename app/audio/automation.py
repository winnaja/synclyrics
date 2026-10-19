"""curve การเปลี่ยนค่าของ deck (gain, EQ, filter, echo) — คำนวณล่วงหน้าทั้งหมด (ข้อ 7.4)

AutomationLane = จุดหัก (เวลา engine เป็น frame, ค่า) ที่ planner สร้างไว้ก่อนเริ่มมิกซ์
callback แค่ "อ่านค่า" ด้วย interpolate ห้ามคำนวณ curve ใน callback
ทุกค่าเปลี่ยนแบบต่อเนื่องเสมอ ห้ามกระโดด (กันเสียงคลิก)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class Param(str, Enum):
    """พารามิเตอร์ต่อ deck ที่ automate ได้"""

    GAIN = "gain"            # 0..1 (linear)
    EQ_LOW = "eq_low"        # dB  (-inf ถึง +6) ใช้ -40 แทนตัดเบส
    EQ_MID = "eq_mid"        # dB
    EQ_HIGH = "eq_high"      # dB
    HIGHPASS_HZ = "hp_hz"    # 20 = ปิด
    LOWPASS_HZ = "lp_hz"     # 20000 = ปิด
    ECHO_SEND = "echo_send"  # 0..1
    ECHO_FEEDBACK = "echo_fb"  # 0..0.9


DEFAULTS: dict[Param, float] = {
    Param.GAIN: 1.0, Param.EQ_LOW: 0.0, Param.EQ_MID: 0.0, Param.EQ_HIGH: 0.0,
    Param.HIGHPASS_HZ: 20.0, Param.LOWPASS_HZ: 20000.0, Param.ECHO_SEND: 0.0, Param.ECHO_FEEDBACK: 0.0,
}


# ---------------------------------------------------------------------------
# curve พื้นฐาน: รับ x ใน [0,1] คืน y ใน [0,1] (fade-in) — fade-out ใช้ curve(1-x)
# ---------------------------------------------------------------------------
def curve_linear(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0.0, 1.0)


def curve_equal_power(x: np.ndarray) -> np.ndarray:
    """ผลรวมพลังงานคงที่: in^2 + out^2 = 1"""
    return np.sin(np.clip(x, 0.0, 1.0) * (np.pi / 2.0))


def curve_s(x: np.ndarray) -> np.ndarray:
    """S-curve (smootherstep) นิ่งตอนต้นและตอนท้าย"""
    x = np.clip(x, 0.0, 1.0)
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


CURVES = {"linear": curve_linear, "equal_power": curve_equal_power, "s_curve": curve_s}


@dataclass(slots=True)
class AutomationLane:
    """ค่าของพารามิเตอร์หนึ่งตัวตามเวลา engine (frame) — ก่อนจุดแรก/หลังจุดสุดท้ายค้างค่าขอบ"""

    param: Param
    frames: np.ndarray  # int64 เรียงจากน้อยไปมาก
    values: np.ndarray  # float64 ยาวเท่า frames

    def value_at(self, frame: int) -> float:
        """ค่า ณ frame (ใช้ใน callback: np.interp ไม่จองหน่วยความจำก้อนใหญ่)"""
        return float(np.interp(frame, self.frames, self.values))

    @staticmethod
    def ramp(param: Param, start_frame: int, length_frames: int, v0: float, v1: float,
             curve: str = "linear", points: int = 64) -> "AutomationLane":
        """สร้าง lane แบบ ramp จาก v0 ไป v1 ตาม curve (สร้างนอก callback เท่านั้น)"""
        x = np.linspace(0.0, 1.0, max(2, points))
        y = CURVES[curve](x)
        frames = (start_frame + x * length_frames).astype(np.int64)
        return AutomationLane(param, frames, v0 + (v1 - v0) * y)
