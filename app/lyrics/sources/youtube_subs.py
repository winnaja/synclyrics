"""คำบรรยายของวิดีโอจาก YouTube (เฉพาะที่คนทำ ไม่ใช่ auto-generated) (ข้อ 4.2 ข้อ 2)

ตรงกับเวอร์ชันของวิดีโอ 100% (เวลาตรงกับ MV) จึงได้โบนัสใน scoring
ข้อมูลมาจาก query.extras["subtitles"] = VideoInfo.subtitles ของ yt-dlp: {lang: [{ext, url}, ...]}
(player ส่งมาให้ เพื่อไม่ต้องเรียก yt-dlp ซ้ำ) ดาวน์โหลดไฟล์ VTT ผ่าน httpx
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from app.core.log import get_logger
from app.lyrics.parsers.subtitles import parse_vtt
from app.lyrics.thai import detect_language
from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx

LANG_PREFERENCE = ("th", "en", "ja", "ko", "zh")
MAX_LANGS = 3
MIN_LINES = 6  # คำบรรยายที่สั้นกว่านี้มักเป็นชื่อเพลง/เครดิต ไม่ใช่เนื้อเพลง


def _preference(track_text: str) -> tuple[str, ...]:
    """ภาษาที่น่าจะเป็นภาษาร้อง: เดาจากตัวอักษรในชื่อวิดีโอ แล้วตามด้วยลำดับมาตรฐาน"""
    guess = detect_language(track_text)
    first = (guess,) if guess and guess != "zh" else ()
    return first + tuple(p for p in LANG_PREFERENCE if p not in first)


def rank_subtitles(subs: dict[str, list[dict[str, Any]]], track_text: str = "") -> list[tuple[str, str]]:
    """เรียงคำบรรยายที่มี vtt ตามภาษาที่น่าจะเป็นเนื้อเพลงจริง คืน [(ภาษา, url)]"""
    pref = _preference(track_text)
    langs = [lang for lang in subs if lang != "live_chat"]
    langs.sort(key=lambda lang: next((i for i, p in enumerate(pref) if lang.lower().startswith(p)), 99))
    out: list[tuple[str, str]] = []
    for lang in langs:
        for fmt in subs[lang]:
            if fmt.get("ext") == "vtt" and fmt.get("url"):
                out.append((lang, fmt["url"]))
                break
    return out


def pick_subtitle_url(subs: dict[str, list[dict[str, Any]]], track_text: str = "") -> tuple[str, str] | None:
    """เลือก (ภาษา, url ของไฟล์ vtt) ที่น่าจะใช่ที่สุด"""
    ranked = rank_subtitles(subs, track_text)
    return ranked[0] if ranked else None


class YoutubeSubsSource(LyricsSource):
    name = "youtube_subs"
    display_name = "คำบรรยาย YouTube"
    timeout_s = 8.0

    async def _one(self, lang: str, url: str, query: LyricsQuery, client: "httpx.AsyncClient") -> LyricsCandidate | None:
        try:
            r = await client.get(url, timeout=self.timeout_s)
            if r.status_code != 200:
                return None
            lyrics = parse_vtt(r.text, source=self.name)
        except Exception as e:
            get_logger("lyrics").debug("youtube_subs failed", extra={"data": {"err": str(e)}})
            return None
        if len(lyrics.lines) < MIN_LINES:
            return None
        lyrics.source_id = lang
        return LyricsCandidate(lyrics=lyrics, matched_title=query.meta.title,
                               matched_artist=query.meta.artist, matched_duration=query.duration)

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        """คืนได้หลายภาษา (สูงสุด MAX_LANGS) เรียงตามความน่าจะเป็นภาษาร้อง — ผิดภาษากด "ผลถัดไป" ได้"""
        ranked = rank_subtitles(query.extras.get("subtitles") or {}, f"{query.track.title} {query.track.channel}")
        got = await asyncio.gather(*(self._one(lang, url, query, client) for lang, url in ranked[:MAX_LANGS]))
        return [c for c in got if c is not None]


SOURCE = YoutubeSubsSource
