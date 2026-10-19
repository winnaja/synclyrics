"""ให้คะแนนผลเนื้อเพลงเพื่อเลือกอันที่ถูกเพลงอัตโนมัติ (ข้อ 4.3)

คะแนน 0-100 จาก:
  - ชื่อเพลงคล้าย (rapidfuzz token_set_ratio หลัง normalize)
  - ศิลปินตรง
  - ความยาวต่างไม่เกิน 3 วิ (เกิน 10 วิ = ตัดทิ้ง)
  - ระดับเวลา: ทีละคำ > ทีละบรรทัด > ไม่มีเวลา
  - version tag ต้องตรง (MV เป็น live แต่เนื้อเพลงเป็น studio = หักหนัก)
  - แหล่งที่ตรงกับวิดีโอโดยตรง (คำบรรยาย YouTube) ได้โบนัสเรื่องเวลา
น้ำหนักแต่ละข้อเก็บใน WEIGHTS ด้านล่าง (ปรับได้โดยไม่แตะ logic)
"""

from __future__ import annotations

from app.core.models import TrackMeta
from app.lyrics.sources.base import LyricsCandidate

WEIGHTS: dict[str, float] = {
    "title": 35.0,
    "artist": 20.0,
    "duration": 20.0,
    "timing": 15.0,
    "version": 10.0,
}
MAX_DURATION_DIFF_S = 3.0
REJECT_DURATION_DIFF_S = 10.0


def score_candidate(candidate: LyricsCandidate, meta: TrackMeta, duration: float | None) -> float:
    """เติม candidate.score และ candidate.score_detail แล้วคืนคะแนน — เฟส 1"""
    raise NotImplementedError("เฟส 1")
