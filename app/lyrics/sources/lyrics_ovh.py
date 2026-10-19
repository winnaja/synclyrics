"""Lyrics.ovh — ได้เนื้อเพลงไม่มีเวลา (ข้อ 4.2 ข้อ 6) ส่งไปประมาณเวลา/จัดเวลาด้วย AI ต่อ

https://api.lyrics.ovh/v1/<artist>/<title> -> {"lyrics": "..."}
ไม่บอกความยาว จึงได้คะแนนความยาวแบบ "ไม่รู้" เป็นแหล่งสำรองท้ายสุดเสมอ
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from app.core.log import get_logger
from app.lyrics.parsers.lrc import parse_plain
from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx


class LyricsOvhSource(LyricsSource):
    name = "lyrics_ovh"
    display_name = "Lyrics.ovh"
    timeout_s = 8.0

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        meta = query.meta
        if not meta.artist or not meta.title:
            return []
        url = f"https://api.lyrics.ovh/v1/{quote(meta.artist, safe='')}/{quote(meta.title, safe='')}"
        try:
            r = await client.get(url, timeout=self.timeout_s)
            if r.status_code != 200:
                return []
            text = (r.json() or {}).get("lyrics") or ""
        except Exception as e:
            get_logger("lyrics").debug("lyrics.ovh failed", extra={"data": {"err": str(e)}})
            return []
        lyrics = parse_plain(text.replace("\r", ""), source=self.name)
        if len(lyrics.lines) < 3:
            return []
        lyrics.title, lyrics.artist = meta.title, meta.artist
        return [LyricsCandidate(lyrics=lyrics, matched_title=meta.title, matched_artist=meta.artist)]


SOURCE = LyricsOvhSource
