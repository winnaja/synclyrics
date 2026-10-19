"""NetEase Cloud Music — API ไม่เป็นทางการ (ข้อ 4.2 ข้อ 4)

มักมีเวลาระดับคำ (YRC) + คำแปล (tlyric)
API เปลี่ยนได้ทุกเมื่อ: พังแล้วข้ามเงียบๆ (unofficial = True) และปิดได้ในหน้าตั้งค่า
parser ของ YRC อยู่ที่ app/lyrics/parsers/yrc.py
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from app.core.log import get_logger
from app.lyrics.parsers.lrc import parse_lrc
from app.lyrics.parsers.yrc import attach_translation, parse_yrc
from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Referer": "https://music.163.com/",
}
MAX_SONGS = 4


def build_lyrics(song: dict[str, Any], data: dict[str, Any]) -> LyricsCandidate | None:
    """แปลงผลของ /api/song/lyric + ข้อมูลเพลงเป็น candidate (แยกออกมาให้ test ได้)"""
    yrc = ((data.get("yrc") or {}).get("lyric") or "").strip()
    lrc = ((data.get("lrc") or {}).get("lyric") or "").strip()
    tlyric = ((data.get("tlyric") or {}).get("lyric") or "").strip() or None
    dur_ms = song.get("duration") or song.get("dt")
    dur = dur_ms / 1000.0 if dur_ms else None
    lyrics = parse_yrc(yrc, translation_lrc=tlyric, source="netease") if yrc else None
    if lyrics is None or not lyrics.lines:
        if not lrc:
            return None
        lyrics = parse_lrc(lrc, source="netease", duration=dur)
        if not lyrics.lines:
            return None
        lyrics.has_translation = attach_translation(lyrics.lines, tlyric)
    lyrics.source_id = str(song.get("id", ""))
    lyrics.duration = dur
    artists = song.get("artists") or song.get("ar") or []
    artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict))
    return LyricsCandidate(
        lyrics=lyrics, matched_title=song.get("name", ""), matched_artist=artist, matched_duration=dur
    )


class NeteaseSource(LyricsSource):
    name = "netease"
    display_name = "NetEase"
    timeout_s = 7.0
    unofficial = True

    async def _json(self, client: "httpx.AsyncClient", url: str, params: dict[str, Any]) -> Any:
        try:
            r = await client.get(url, params=params, headers=HEADERS, timeout=self.timeout_s)
            return r.json() if r.status_code == 200 else None
        except Exception as e:
            get_logger("lyrics").debug("netease failed", extra={"data": {"err": str(e)}})
            return None

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        q = query.meta.queries[0] if query.meta.queries else f"{query.meta.artist} {query.meta.title}"
        res = await self._json(client, "https://music.163.com/api/search/get",
                               {"s": q, "type": 1, "limit": MAX_SONGS, "offset": 0})
        songs = ((res or {}).get("result") or {}).get("songs") or []

        async def one(song: dict[str, Any]) -> LyricsCandidate | None:
            data = await self._json(
                client, "https://music.163.com/api/song/lyric",
                {"id": song.get("id"), "lv": 1, "kv": 1, "tv": -1, "yv": 1},
            )
            return build_lyrics(song, data) if isinstance(data, dict) else None

        got = await asyncio.gather(*(one(s) for s in songs[:MAX_SONGS]), return_exceptions=True)
        return [c for c in got if isinstance(c, LyricsCandidate)]


SOURCE = NeteaseSource
