"""Lyrics.ovh (https://api.lyrics.ovh/v1/<artist>/<title>) — เนื้อเพลงไม่มีเวลา (ข้อ 4.2 ข้อ 6)

ได้ TimingLevel.NONE เสมอ -> ระหว่างรอใช้เวลาแบบประมาณทั้งเพลง
แล้วส่งให้ AI หาเวลาบรรทัดด้วย whisper ก่อน แล้ว align ทีละคำ (ข้อ 5.1 ขั้น 6)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx


class LyricsOvhSource(LyricsSource):
    name = "lyrics_ovh"
    display_name = "Lyrics.ovh"
    timeout_s = 6.0

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        raise NotImplementedError("เฟส 1")


SOURCE = LyricsOvhSource
