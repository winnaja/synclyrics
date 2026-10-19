"""QQ Music — API ไม่เป็นทางการ (ข้อ 4.2 ข้อ 5)

เฟส 1: ใช้ LRC ระดับบรรทัดจาก API (ไม่เข้ารหัส) — QRC ทีละคำต้องถอดรหัส ซึ่งยังไม่รองรับ
(ดู app/lyrics/parsers/qrc.py และ docs/DECISIONS.md) พังแล้วข้ามเงียบๆ ปิดได้ในหน้าตั้งค่า
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING, Any

from app.core.log import get_logger
from app.lyrics.parsers.lrc import parse_lrc
from app.lyrics.parsers.yrc import attach_translation
from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Referer": "https://y.qq.com/",
}
MAX_SONGS = 4


def _decode(text: str | None) -> str | None:
    """API ส่ง LRC เป็นข้อความตรงๆ หรือ base64 (ขึ้นกับพารามิเตอร์) รองรับทั้งสองแบบ"""
    if not text:
        return None
    if text.lstrip().startswith("["):
        return text
    try:
        return base64.b64decode(text).decode("utf-8")
    except Exception:
        return None


def build_candidate(song: dict[str, Any], data: dict[str, Any]) -> LyricsCandidate | None:
    lrc = _decode(data.get("lyric"))
    if not lrc:
        return None
    dur = float(song["interval"]) if song.get("interval") else None
    lyrics = parse_lrc(lrc, source="qqmusic", duration=dur)
    if not lyrics.lines:
        return None
    lyrics.has_translation = attach_translation(lyrics.lines, _decode(data.get("trans")))
    lyrics.source_id = str(song.get("songmid", ""))
    lyrics.duration = dur
    artist = ", ".join(s.get("name", "") for s in song.get("singer", []) if isinstance(s, dict))
    return LyricsCandidate(
        lyrics=lyrics, matched_title=song.get("songname", ""), matched_artist=artist, matched_duration=dur
    )


class QqMusicSource(LyricsSource):
    name = "qqmusic"
    display_name = "QQ Music"
    timeout_s = 7.0
    unofficial = True

    async def _json(self, client: "httpx.AsyncClient", url: str, params: dict[str, Any]) -> Any:
        try:
            r = await client.get(url, params=params, headers=HEADERS, timeout=self.timeout_s)
            if r.status_code != 200:
                return None
            text = r.text.strip()
            if not text.startswith("{") and "(" in text:  # JSONP
                text = text[text.index("(") + 1: text.rindex(")")]
            return json.loads(text)
        except Exception as e:
            get_logger("lyrics").debug("qqmusic failed", extra={"data": {"err": str(e)}})
            return None

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        q = query.meta.queries[0] if query.meta.queries else f"{query.meta.artist} {query.meta.title}"
        res = await self._json(client, "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                               {"w": q, "format": "json", "n": MAX_SONGS, "p": 1})
        songs = (((res or {}).get("data") or {}).get("song") or {}).get("list") or []

        async def one(song: dict[str, Any]) -> LyricsCandidate | None:
            data = await self._json(
                client, "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
                {"songmid": song.get("songmid"), "format": "json", "nobase64": 1, "g_tk": 5381},
            )
            return build_candidate(song, data) if isinstance(data, dict) else None

        got = await asyncio.gather(*(one(s) for s in songs[:MAX_SONGS]), return_exceptions=True)
        return [c for c in got if isinstance(c, LyricsCandidate)]


SOURCE = QqMusicSource
