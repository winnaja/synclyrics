"""LRCLIB (https://lrclib.net) — ฟรี ไม่ต้องใช้ key

ลำดับ: /api/get?track_name&artist_name&album_name&duration (ตรงเป๊ะ) -> /api/search?q=... (กว้างขึ้น)
ได้ syncedLyrics (LRC ทีละบรรทัด บางเพลงเป็น Enhanced LRC ทีละคำ) และ plainLyrics
ส่ง User-Agent ระบุชื่อโปรแกรมตามที่ LRCLIB ขอ
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from app.core.log import get_logger
from app.lyrics.parsers.lrc import parse_lrc, parse_plain
from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx

BASE = "https://lrclib.net/api"
HEADERS = {"User-Agent": "SyncLyrics/0.1 (personal use)"}
MAX_SEARCH_QUERIES = 2
MAX_RESULTS = 6


def to_candidate(item: dict[str, Any]) -> LyricsCandidate | None:
    """แปลงผลหนึ่งรายการของ LRCLIB (แยกออกมาให้ test ได้) — ไม่มีเนื้อเพลง/เพลงบรรเลง = None"""
    if item.get("instrumental"):
        return None
    synced, plain = item.get("syncedLyrics"), item.get("plainLyrics")
    dur = item.get("duration")
    dur = float(dur) if dur else None
    if synced and synced.strip():
        lyrics = parse_lrc(synced, source="lrclib", duration=dur)
    elif plain and plain.strip():
        lyrics = parse_plain(plain, source="lrclib")
    else:
        return None
    if not lyrics.lines:
        return None
    lyrics.source_id = str(item.get("id", ""))
    lyrics.title, lyrics.artist = item.get("trackName"), item.get("artistName")
    lyrics.duration = dur
    return LyricsCandidate(
        lyrics=lyrics, matched_title=item.get("trackName") or "",
        matched_artist=item.get("artistName") or "", matched_duration=dur,
    )


class LrclibSource(LyricsSource):
    name = "lrclib"
    display_name = "LRCLIB"
    timeout_s = 6.0

    async def _get_json(self, client: "httpx.AsyncClient", path: str, params: dict[str, Any]) -> Any:
        try:
            r = await client.get(f"{BASE}/{path}", params=params, headers=HEADERS, timeout=self.timeout_s)
            return r.json() if r.status_code == 200 else None
        except Exception as e:  # เครือข่าย/JSON พัง = ข้ามคำค้นนี้
            get_logger("lyrics").debug("lrclib request failed", extra={"data": {"path": path, "err": str(e)}})
            return None

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        meta = query.meta
        out: list[LyricsCandidate] = []
        seen: set[str] = set()

        def add(item: Any) -> None:
            if not isinstance(item, dict):
                return
            c = to_candidate(item)
            if c and c.lyrics.source_id not in seen:
                seen.add(c.lyrics.source_id)
                out.append(c)

        params: dict[str, Any] = {"track_name": meta.title, "artist_name": meta.artist}
        if meta.album:
            params["album_name"] = meta.album
        if query.duration:
            params["duration"] = int(round(query.duration))
        tasks = [self._get_json(client, "get", params)]
        tasks += [self._get_json(client, "search", {"q": q}) for q in meta.queries[:MAX_SEARCH_QUERIES]]
        exact, *searched = await asyncio.gather(*tasks)
        add(exact)
        for res in searched:
            if isinstance(res, list):
                for item in res[:MAX_RESULTS]:
                    add(item)
        return out


SOURCE = LrclibSource
