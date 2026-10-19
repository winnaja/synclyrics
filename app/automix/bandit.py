"""ระบบเรียนรู้จากรางวัล: contextual bandit แบบ Thompson Sampling + Bayesian linear regression (ข้อ 7.5)

แบบจำลอง: แยก posterior ต่อ "แขน" (arm = ชุด action ที่เป็นไปได้ เช่น style+curve+ช่วงความยาว)
  reward ≈ w_arm · x  (x = context vector ที่ normalize แล้ว + bias)
  posterior ของ w: Normal(mu, Sigma) อัปเดตแบบปิดรูปทันทีหลังได้รางวัล (O(d^2), CPU)
ตัดสินใจ: สุ่ม w~ จาก posterior (ความแปรปรวนคูณด้วยค่าความกล้า) แล้วเลือกแขนที่ w~·x สูงสุด
  ในบรรดาแขนที่ผ่านกฎเหล็กแล้วเท่านั้น
prior: mu มาจาก automix_rules.yaml (แปลงกฎเป็นคะแนนตั้งต้น) ด้วยน้ำหนัก prior_strength
       -> ตอนยังไม่มีข้อมูล ทำงานเหมือนระบบกฎ
decay: ก่อนอัปเดตแต่ละครั้ง ขยาย Sigma ตามเวลาที่ผ่านไป (half-life) ให้ข้อมูลเก่าค่อยๆ หมดน้ำหนัก
ความปลอดภัย: compat < 40 ห้ามทดลอง (ใช้ mean ไม่สุ่ม), แย่ติดกัน 3 ครั้ง = ลดการทดลองชั่วคราว
เก็บสถานะ: ตาราง bandit_state (npz blob) + สำรองไฟล์วันละครั้ง ย้อนได้ 7 วัน
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ชื่อ feature ของ context (ลำดับนี้คือลำดับใน vector — เพิ่มท้ายเท่านั้น แล้วเพิ่ม version)
CONTEXT_FEATURES: tuple[str, ...] = (
    "bias",
    "bpm_diff_pct",
    "camelot_distance",
    "energy_end_a",
    "energy_start_b",
    "loudness_diff_db",
    "outro_len_a_s",
    "intro_len_b_s",
    "a_ends_with_fade",
    "beat_conf_min",
    "genre_similarity",
    "same_language",
    "compat_score",
)
MODEL_VERSION = 1


@dataclass(slots=True)
class Arm:
    key: str                      # เช่น "beatmatch_blend|equal_power|16bar|start"
    action: Any                   # MixAction
    mu: Any = None                # numpy (d,)
    sigma: Any = None             # numpy (d, d)
    n: float = 0.0                # จำนวนข้อมูลแบบถ่วง decay


@dataclass(slots=True)
class Decision:
    arm_key: str
    explored: bool                # True = เลือกเพราะสุ่ม (ไม่ใช่แขนที่ค่าเฉลี่ยดีสุด)
    sampled_scores: dict[str, float] = field(default_factory=dict)
    mean_scores: dict[str, float] = field(default_factory=dict)


class ThompsonBandit:
    """เฟส 7"""

    def choose(self, context: Any, allowed_arms: list[str], boldness: float, allow_explore: bool) -> Decision:
        raise NotImplementedError("เฟส 7")

    def update(self, arm_key: str, context: Any, reward: float, at_time: float) -> None:
        raise NotImplementedError("เฟส 7")

    def save(self, conn: Any) -> None:
        raise NotImplementedError("เฟส 7")

    def load(self, conn: Any) -> None:
        raise NotImplementedError("เฟส 7")

    def reset(self) -> None:
        raise NotImplementedError("เฟส 7")
