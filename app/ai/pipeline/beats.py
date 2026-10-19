"""วิเคราะห์จังหวะและท่อนเพลงทั้งเพลง (ข้อ 5.1 ขั้น 3)

ตัวหลัก beat_this (ติดตั้งง่าย) — allin1 ถ้าติดตั้งได้ (ได้ท่อน intro/verse/chorus ด้วย)
ใช้ stems จาก stems.py ร่วมกัน ห้ามแยกเสียงซ้ำ
beat_confidence: วัดจากความสม่ำเสมอของ inter-beat interval (ต่ำ = ห้าม beat-match)
"""

from __future__ import annotations

from typing import Any


def analyze_beats(pcm_path: str, sample_rate: int, stems_dir: str | None, prefer: str) -> Any:
    """คืน bpm, beats, downbeats, beat_confidence, sections, analyzer — เฟส 4"""
    raise NotImplementedError("เฟส 4")

def simple_sections(beats: list[float], downbeats: list[float], vocal_segments: list[tuple[float, float]], energy: Any) -> Any:
    """ตัวแบ่งท่อนแบบง่าย (ใช้เมื่อไม่มี allin1): intro/outro จากช่วงไม่มีเสียงร้อง + energy — เฟส 4"""
    raise NotImplementedError("เฟส 4")
