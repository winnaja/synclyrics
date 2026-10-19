"""LyricsService — จุดเดียวที่ส่วนอื่นเรียกเพื่อได้เนื้อเพลง (ข้อ 4.2-4.4)

find(track) ทำตามลำดับนี้ใน asyncio loop (thread IO):
  1. cache ใน SQLite ตาม videoId (มีตัวเลือกที่ผู้ใช้เลือกไว้ -> ใช้อันนั้นเลย)
  2. แยกชื่อเพลง (title_parser) -> สร้าง LyricsQuery
  3. asyncio.gather ทุกแหล่งที่เปิดอยู่ (แต่ละแหล่งมี timeout ของตัวเอง) — แหล่งพัง = ข้าม
  4. ให้คะแนน (scoring) เรียงผล เก็บทุกผลลง DB (ใช้กด "ผลถัดไป")
  5. ผลที่ดีที่สุดไม่มีเวลาทีละคำ -> ใส่เวลาแบบประมาณ (timing_estimate) ภายใน 1 วิหลังกดเล่น
  6. ไม่เจอเลย -> ขอ AI ถอดเสียง (faster-whisper) ผ่าน AI scheduler แล้วแสดงป้าย "ถอดเสียงโดย AI"
ผลส่งออกทาง EventBus: LYRICS_READY

กดเล่นแล้วต้องมีเนื้อเพลงเสมอ ห้ามถามผู้ใช้ — การวางเนื้อเพลงเองเป็นแค่ทางสำรองในเมนู
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.models import Lyrics, TrackRef
from app.lyrics.sources.base import LyricsCandidate


@dataclass(slots=True)
class LyricsResult:
    chosen: Lyrics | None
    candidates: list[LyricsCandidate]
    source_label: str  # เช่น "จาก LRCLIB · ทีละคำ"
    from_cache: bool = False
    needs_ai_transcription: bool = False


class LyricsService:
    """ประสานงานแหล่งเนื้อเพลงทั้งหมด — เฟส 1"""

    async def find(self, track: TrackRef, duration: float | None) -> LyricsResult:
        raise NotImplementedError("เฟส 1")

    async def next_candidate(self, video_id: str) -> LyricsResult:
        """ปุ่ม "ผลถัดไป": สลับไปผลอันดับถัดไปและจำไว้ตาม videoId"""
        raise NotImplementedError("เฟส 1")

    def set_manual_lyrics(self, video_id: str, text: str) -> Lyrics:
        """ทางสำรองในเมนู: ผู้ใช้วางเนื้อเพลงเอง (ได้ TimingLevel.NONE -> ประมาณเวลา + AI)"""
        raise NotImplementedError("เฟส 1")


def source_label(lyrics: Lyrics, display_name: str) -> str:
    """ข้อความเล็กๆ มุมจอ (ข้อ 4.3)"""
    level = {"word": "ทีละคำ", "line": "ทีละบรรทัด", "none": "ประมาณเวลา"}[lyrics.timing.value]
    prefix = "ถอดเสียงโดย AI" if lyrics.ai_transcribed else f"จาก {display_name}"
    return f"{prefix} · {level}"
