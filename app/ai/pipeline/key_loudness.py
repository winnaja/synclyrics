"""key (librosa chroma + Krumhansl-Schmuckler -> Camelot) และ loudness LUFS (pyloudnorm) — ข้อ 5.1 ขั้น 4
ทำบน CPU ได้ (ไม่ใช้ GPU)
"""

from __future__ import annotations

from typing import Any


def detect_key(instrumental: Any, sample_rate: int) -> Any:
    """คืน (key เช่น 'A minor', camelot เช่น '8A', confidence) — เฟส 4"""
    raise NotImplementedError("เฟส 4")

def integrated_lufs(pcm: Any, sample_rate: int) -> Any:
    """คืนค่า LUFS ทั้งเพลง — เฟส 4"""
    raise NotImplementedError("เฟส 4")

def edge_energy(pcm: Any, sample_rate: int, seconds: float) -> Any:
    """energy ต้น/ท้ายเพลง (0-1) และเพลงจบแบบ fade หรือไม่ — เฟส 4"""
    raise NotImplementedError("เฟส 4")
