"""วางแผนการมิกซ์ระหว่างเพลง A -> B (ข้อ 7.2-7.4, 8)

MixPlan คือสัญญาระหว่าง AutoMix, audio engine และ UI:
  - engine: เวลาเริ่ม B (engine frame), automation lanes ของทั้งสอง deck, program ของ B (รวมช่วง stretch)
  - UI: ความยาวทรานซิชั่นภาพ = ความยาวมิกซ์จริง, beat ที่ใช้ซิงก์, ชื่อรูปแบบทรานซิชั่น
  - mixlog: context, action, เหตุผล (decision_log)
plan ต้องสร้างเสร็จ (รวม time-stretch ด้วย Rubber Band) ก่อนถึงจุดมิกซ์ — ไม่ทันใช้ crossfade ธรรมดา
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MixStyle(str, Enum):
    BEATMATCH_BLEND = "beatmatch_blend"
    BASS_SWAP = "bass_swap"
    FILTER_SWEEP = "filter_sweep"
    ECHO_OUT = "echo_out"
    SHORT_CROSSFADE = "short_crossfade"
    LONG_CROSSFADE = "long_crossfade"
    CLEAN_CUT = "clean_cut"  # ต่อแบบเรียบ: A จบตามธรรมชาติ เว้นสั้นๆ B เริ่มที่ downbeat แรก

    @property
    def safety_rank(self) -> int:
        """ยิ่งน้อยยิ่งเรียบ/ปลอดภัย ใช้ตอน 'ไม่แน่ใจ -> เลือกแบบที่เรียบกว่า'"""
        order = ["clean_cut", "short_crossfade", "long_crossfade", "filter_sweep",
                 "echo_out", "bass_swap", "beatmatch_blend"]
        return order.index(self.value)


@dataclass(slots=True)
class MixAction:
    """สิ่งที่ bandit เลือก (ข้อ 7.5 Action)"""

    style: MixStyle
    length_s: float
    b_entry: str = "start"        # "start" | "skip_intro_half" | "first_downbeat"
    curve: str = "equal_power"    # linear | equal_power | s_curve


@dataclass(slots=True)
class MixPlan:
    video_a: str
    video_b: str
    action: MixAction
    compat_score: float
    a_exit_s: float               # เวลาในเพลง A ที่เริ่มมิกซ์
    b_entry_s: float              # เวลาในเพลง B ที่เริ่มเล่น
    b_start_engine_frame: int | None = None  # ใส่ตอนติดตั้งลง engine
    tempo_ratio: float = 1.0      # time-stretch ของ B ช่วงเข้า (1.0 = ไม่ยืด)
    beat_times_s: list[float] = field(default_factory=list)  # beat ระหว่างมิกซ์ (UI Beat Pulse)
    lanes: dict[str, Any] = field(default_factory=dict)       # deck -> list[AutomationLane]
    visual_transition: str = "morph"
    explored: bool = False
    decision_log: dict[str, Any] = field(default_factory=dict)


def plan_transition(a: Any, b: Any, settings: Any, rules: dict[str, Any], learner: Any) -> MixPlan:
    """เฟส 6 (ระบบเรียนรู้ต่อเข้าในเฟส 7)"""
    raise NotImplementedError("เฟส 6")


def fallback_crossfade(video_a: str, video_b: str, a_duration: float, length_s: float = 4.0) -> MixPlan:
    """แผนสำรองที่ใช้ได้เสมอ (AutoMix พัง / analysis ไม่ทัน) — เฟส 5"""
    raise NotImplementedError("เฟส 5")
