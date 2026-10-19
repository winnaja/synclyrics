"""LRCLIB (https://lrclib.net) — ฟรี ไม่ต้องใช้ key

ลำดับ: /api/get?track_name&artist_name&album_name&duration (ตรงเป๊ะ) -> /api/search?q=... (กว้างขึ้น)
ได้ syncedLyrics (LRC ทีละบรรทัด บางเพลงเป็น Enhanced LRC ทีละคำ) และ plainLyrics
ส่ง User-Agent ระบุชื่อโปรแกรมตามที่ LRCLIB ขอ
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx


class LrclibSource(LyricsSource):
    name = "lrclib"
    display_name = "LRCLIB"
    timeout_s = 6.0

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        raise NotImplementedError("เฟส 1")


SOURCE = LrclibSource
