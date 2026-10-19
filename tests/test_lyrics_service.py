"""LyricsService: ค้นหลายแหล่งพร้อมกัน, แหล่งพังต้องข้าม, cache, ผลถัดไป, plugin และ parser ของแหล่งจริง"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import LyricsSourceSettings
from app.core.models import Line, Lyrics, TimingLevel, TrackRef, Word
from app.lyrics.service import LyricsService
from app.lyrics.sources import base as sbase
from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource
from app.lyrics.sources.lrclib import to_candidate
from app.lyrics.sources.netease import build_lyrics
from app.lyrics.sources.qqmusic import build_candidate
from app.lyrics.sources.youtube_subs import pick_subtitle_url

TRACK = TrackRef(video_id="vid00000001", title="Nova Waves - Midnight Drive (Official MV)",
                 channel="Nova Waves", duration=200.0)


def _lyrics(source: str, timing: TimingLevel, sid: str = "1") -> Lyrics:
    lines = [Line(i * 4.0, i * 4.0 + 3.0, [Word(f"line {i} of text", i * 4.0, i * 4.0 + 3.0)]) for i in range(8)]
    return Lyrics(lines=lines, timing=timing, source=source, source_id=sid)


def make_source(name: str, *, result=None, delay: float = 0.0, boom: bool = False, unofficial: bool = False,
                title: str = "Midnight Drive", artist: str = "Nova Waves", dur: float = 200.0):
    class S(LyricsSource):
        async def search(self, query: LyricsQuery, client) -> list[LyricsCandidate]:
            await asyncio.sleep(delay)
            if boom:
                raise RuntimeError("api changed")
            return [LyricsCandidate(lyrics=result, matched_title=title, matched_artist=artist, matched_duration=dur)]

    S.name, S.display_name, S.unofficial, S.timeout_s = name, name.upper(), unofficial, 0.5
    return S


@pytest.fixture()
def db_path(app_paths):
    return app_paths.db_file


async def test_picks_best_and_survives_broken_source(db_path) -> None:
    sources = {
        "good": make_source("good", result=_lyrics("good", TimingLevel.WORD)),
        "broken": make_source("broken", boom=True, unofficial=True),
        "wrong": make_source("wrong", result=_lyrics("wrong", TimingLevel.WORD), title="Totally Different", artist="X"),
    }
    svc = LyricsService(db_path, sources=sources, client=object())
    res = await svc.find(TRACK, 200.0)
    assert res.chosen is not None and res.chosen.source == "good"
    assert res.source_label == "จาก GOOD · ทีละคำ"
    assert len(res.candidates) >= 1 and not res.from_cache


async def test_line_level_gets_estimated_words(db_path) -> None:
    svc = LyricsService(db_path, sources={"a": make_source("a", result=_lyrics("a", TimingLevel.LINE))}, client=object())
    res = await svc.find(TRACK, 200.0)
    assert res.chosen is not None and len(res.chosen.lines[0].words) > 1  # แตกเป็นคำแล้ว


async def test_cache_hit_skips_sources(db_path) -> None:
    calls = {"n": 0}
    base_src = make_source("a", result=_lyrics("a", TimingLevel.LINE))
    orig = base_src.search

    async def counting(self, q, c):
        calls["n"] += 1
        return await orig(self, q, c)

    base_src.search = counting  # type: ignore[method-assign]
    svc = LyricsService(db_path, sources={"a": base_src}, client=object())
    await svc.find(TRACK, 200.0)
    res2 = await svc.find(TRACK, 200.0)
    assert calls["n"] == 1 and res2.from_cache and res2.chosen is not None


async def test_disabled_source_not_called(db_path) -> None:
    src = make_source("a", result=_lyrics("a", TimingLevel.LINE))
    svc = LyricsService(db_path, settings=LyricsSourceSettings(enabled={"a": False}), sources={"a": src}, client=object())
    res = await svc.find(TRACK, 200.0)
    assert res.chosen is None and res.needs_ai_transcription


async def test_no_result_flags_ai_transcription(db_path) -> None:
    svc = LyricsService(db_path, sources={"b": make_source("b", boom=True)}, client=object())
    res = await svc.find(TRACK, 200.0)
    assert res.chosen is None and res.needs_ai_transcription and res.source_label == "ไม่พบเนื้อเพลง"


async def test_next_candidate_cycles_and_remembers(db_path) -> None:
    sources = {
        "a": make_source("a", result=_lyrics("a", TimingLevel.WORD)),
        "b": make_source("b", result=_lyrics("b", TimingLevel.LINE)),
    }
    svc = LyricsService(db_path, sources=sources, client=object())
    first = await svc.find(TRACK, 200.0)
    nxt = await svc.next_candidate(TRACK.video_id)
    assert nxt.chosen is not None and nxt.chosen.source != first.chosen.source
    again = await svc.find(TRACK, 200.0)  # จำตัวเลือกของผู้ใช้
    assert again.chosen.source == nxt.chosen.source and again.from_cache
    third = await svc.next_candidate(TRACK.video_id)
    assert third.chosen.source == first.chosen.source  # วนกลับ


async def test_on_update_fires_early_then_improves(db_path) -> None:
    sources = {
        "slow_good": make_source("slow_good", result=_lyrics("slow_good", TimingLevel.WORD), delay=0.25),
        "fast_ok": make_source("fast_ok", result=_lyrics("fast_ok", TimingLevel.NONE), dur=200.0),
    }
    svc = LyricsService(db_path, sources=sources, client=object())
    seen: list[str] = []
    res = await svc.find(TRACK, 200.0, on_update=lambda r: seen.append(r.chosen.source))
    assert seen[0] == "fast_ok" and res.chosen.source == "slow_good" and "slow_good" in seen


async def test_manual_lyrics(db_path) -> None:
    svc = LyricsService(db_path, sources={}, client=object())
    await svc.find(TRACK, 200.0)  # สร้างแถว tracks
    ly = svc.set_manual_lyrics(TRACK.video_id, "one two\nthree four\n")
    assert len(ly.lines) == 2 and ly.lines[0].words[0].timing.value == "estimated"
    res = await svc.find(TRACK, 200.0)
    assert res.from_cache and res.chosen.source == "manual"


def test_plugins_discovered() -> None:
    found = sbase.discover()
    assert {"lrclib", "netease", "qqmusic", "lyrics_ovh", "youtube_subs"} <= set(found)


def test_lrclib_item_conversion() -> None:
    c = to_candidate({"id": 7, "trackName": "T", "artistName": "A", "duration": 200,
                      "syncedLyrics": "[00:01.00]hello there\n[00:03.00]second line\n", "plainLyrics": "x"})
    assert c is not None and c.lyrics.timing == TimingLevel.LINE and c.matched_duration == 200.0
    plain = to_candidate({"id": 8, "trackName": "T", "artistName": "A", "plainLyrics": "a\nb\n"})
    assert plain is not None and plain.lyrics.timing == TimingLevel.NONE
    assert to_candidate({"id": 9, "instrumental": True}) is None
    assert to_candidate({"id": 10}) is None


def test_netease_prefers_yrc_with_translation() -> None:
    data = {"yrc": {"lyric": "[1000,2000](1000,1000,0)hello (2000,1000,0)you"},
            "lrc": {"lyric": "[00:01.00]hello you"}, "tlyric": {"lyric": "[00:01.10]สวัสดี"}}
    c = build_lyrics({"id": 5, "name": "T", "duration": 200000, "artists": [{"name": "A"}]}, data)
    assert c and c.lyrics.timing == TimingLevel.WORD and c.lyrics.has_translation and c.matched_duration == 200.0
    lrc_only = build_lyrics({"id": 5, "name": "T"}, {"lrc": {"lyric": "[00:01.00]a b\n[00:03.00]c d"}})
    assert lrc_only and lrc_only.lyrics.timing == TimingLevel.LINE
    assert build_lyrics({"id": 5}, {}) is None


def test_qqmusic_candidate_plain_and_base64() -> None:
    import base64

    lrc = "[00:01.00]hello there\n[00:03.00]more words"
    song = {"songmid": "m1", "songname": "T", "singer": [{"name": "A"}], "interval": 200}
    assert build_candidate(song, {"lyric": lrc}) is not None
    c = build_candidate(song, {"lyric": base64.b64encode(lrc.encode()).decode()})
    assert c and c.matched_artist == "A" and c.matched_duration == 200.0
    assert build_candidate(song, {"lyric": ""}) is None


def test_pick_subtitle_prefers_language_and_vtt() -> None:
    subs = {"en": [{"ext": "vtt", "url": "u-en"}], "th": [{"ext": "srv3", "url": "x"}, {"ext": "vtt", "url": "u-th"}],
            "live_chat": [{"ext": "json", "url": "chat"}]}
    assert pick_subtitle_url(subs) == ("th", "u-th")
    assert pick_subtitle_url({}) is None
