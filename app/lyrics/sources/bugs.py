"""Bugs (music.bugs.co.kr) — เว็บเพลงเกาหลี · เนื้อเพลงมีเวลาระดับบรรทัด · API ภายในของเว็บ ไม่เป็นทางการ

เพิ่มเมื่อ 2026-10-26: ผู้ใช้ฟังเพลงเกาหลีเยอะ และเว็บเกาหลีจับคู่ศิลปินชื่อฮันกึล (검정치마) ได้ตรงกว่าเว็บสากล
(เคส EVERYTHING ของ The Black Skirts: LRCLIB/NetEase มีเนื้อแต่ความยาวไม่ตรงกับวิดีโอที่ตัดสั้น)

รูปแบบเนื้อเพลงจาก /player/lyrics/T/<trackId> คือ JSON {"lyrics": "42.9|บรรทัด１＃48.1|บรรทัด２＃..."}
บรรทัดคั่นด้วย "＃" (อักษรเต็มส่วน) แต่ละบรรทัดขึ้นต้นด้วย "วินาที|"  ไม่มีเวลาจบ จึงใช้เวลาเริ่มของบรรทัดถัดไป
พังแล้วข้ามเงียบๆ (unofficial = True) และปิดได้ในหน้าตั้งค่า (src_bugs)
"""

from __future__ import annotations

import asyncio
import html
import re
from typing import TYPE_CHECKING

from app.core.log import get_logger
from app.core.models import Line, Lyrics, TimingLevel, Word
from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept-Language": "ko,en;q=0.8",
    "Referer": "https://music.bugs.co.kr/",
}
MAX_TRACKS = 4
_TRACK_RE = re.compile(r'<tr[^>]*\btrackId="(\d+)"[^>]*>(.*?)</tr>', re.S)
# แท็ก <p> มีแอตทริบิวต์เพิ่มได้ (เช่น adult_yn="N") จึงห้ามจับ '<p class="title">' แบบเป๊ะ
_TITLE_RE = re.compile(r'<p class="title"[^>]*>\s*<a[^>]*title="([^"]*)"', re.S)
_ARTIST_RE = re.compile(r'<p class="artist"[^>]*>\s*<a[^>]*title="([^"]*)"', re.S)
_TIME_RE = re.compile(r"^(\d+(?:\.\d+)?)\|(.*)$", re.S)


def parse_bugs_lyrics(raw: str, duration: float | None = None, source_id: str = "") -> Lyrics | None:
    """'42.9|ข้อความ＃48.1|ข้อความ' -> Lyrics (ระดับบรรทัด) · ไม่มีเวลาเลย = None (ไม่ใช่เนื้อซิงก์)"""
    stamps: list[tuple[float, str]] = []
    for part in raw.split("＃"):
        m = _TIME_RE.match(part.strip("\r\n "))
        if not m:
            continue
        text = html.unescape(m.group(2)).strip()
        if text:
            stamps.append((float(m.group(1)), text))
    if len(stamps) < 2:
        return None
    lines: list[Line] = []
    for i, (t, text) in enumerate(stamps):
        end = stamps[i + 1][0] if i + 1 < len(stamps) else (duration if duration and duration > t else t + 4.0)
        words = [Word(text, t, end, trailing_space=False)]
        lines.append(Line(start=t, end=end, words=words))
    return Lyrics(lines=lines, timing=TimingLevel.LINE, source="bugs", source_id=source_id, duration=duration)


def parse_search(page: str) -> list[tuple[str, str, str]]:
    """หน้าผลค้นหา -> [(trackId, ชื่อเพลง, ศิลปิน)]"""
    out: list[tuple[str, str, str]] = []
    for tid, body in _TRACK_RE.findall(page):
        t = _TITLE_RE.search(body)
        a = _ARTIST_RE.search(body)
        out.append((tid, html.unescape(t.group(1)) if t else "", html.unescape(a.group(1)) if a else ""))
    return out


class BugsSource(LyricsSource):
    name = "bugs"
    display_name = "Bugs"
    timeout_s = 7.0
    unofficial = True

    async def _get(self, client: "httpx.AsyncClient", url: str, **params):
        try:
            r = await client.get(url, params=params or None, headers=HEADERS, timeout=self.timeout_s)
            return r if r.status_code == 200 else None
        except Exception as e:
            get_logger("lyrics").debug("bugs failed", extra={"data": {"err": str(e)}})
            return None

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        # Bugs ค้นหาด้วยชื่อศิลปิน+ชื่อเพลงได้ทั้งฮันกึลและอังกฤษ
        q = query.meta.queries[0] if query.meta.queries else f"{query.meta.artist} {query.meta.title}"
        page = await self._get(client, "https://music.bugs.co.kr/search/track", q=q)
        if page is None:
            return []
        tracks = parse_search(page.text)[:MAX_TRACKS]

        async def one(tid: str, title: str, artist: str) -> LyricsCandidate | None:
            r = await self._get(client, f"https://music.bugs.co.kr/player/lyrics/T/{tid}")
            if r is None:
                return None
            try:
                raw = (r.json() or {}).get("lyrics") or ""
            except Exception:
                return None
            ly = parse_bugs_lyrics(raw, None, tid)
            if ly is None:
                return None
            ly.title, ly.artist = title, artist
            # Bugs ไม่บอกความยาวเพลงในหน้าค้นหา — ไม่เดา ปล่อยว่าง (scoring จะถือว่าไม่รู้ความยาว ไม่ลงโทษ)
            return LyricsCandidate(lyrics=ly, matched_title=title, matched_artist=artist, matched_duration=None)

        got = await asyncio.gather(*(one(*t) for t in tracks), return_exceptions=True)
        return [c for c in got if isinstance(c, LyricsCandidate)]


SOURCE = BugsSource
