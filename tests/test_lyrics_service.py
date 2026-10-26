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
    return Lyrics(lines=lines, timing=timing, source=source, source_id=sid, title="Midnight Drive", artist="Nova Waves")


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


def _timed_line(text, t0=0.0, per=0.4):
    from app.core.models import Line, Word, WordTimingSource

    words = [Word(w, t0 + i * per, t0 + (i + 1) * per, timing=WordTimingSource.ESTIMATED, trailing_space=(i < len(text.split()) - 1))
             for i, w in enumerate(text.split())]
    return Line(start=words[0].start, end=words[-1].end, words=words)


def test_split_line_cuts_long_line_at_conjunction_and_keeps_word_times():
    from app.lyrics.linebreak import split_line

    ln = _timed_line("You know all that's fake and God knows why I need you")
    parts = split_line(ln, 30)
    assert len(parts) >= 2
    assert parts[0].text.endswith("fake") and parts[1].text.startswith("and")
    assert sum(len(p.words) for p in parts) == len(ln.words)
    assert parts[0].end <= parts[1].start + 1e-9 and parts[1].start == ln.words[len(parts[0].words)].start


def test_split_line_leaves_short_lines_and_lines_with_translation_alone():
    from app.lyrics.linebreak import split_line

    short = _timed_line("I wish I was special")
    assert split_line(short, 30) == [short]
    long_tr = _timed_line("You know all that's fake and God knows why I need you")
    long_tr.translation = "คำแปล"
    assert split_line(long_tr, 30) == [long_tr]


# ---------- fusion ต่อเข้า find() จริง ----------

def _fusable(source: str, texts: list[str], timing: TimingLevel = TimingLevel.LINE) -> Lyrics:
    lines = [Line(i * 4.0, i * 4.0 + 3.0, [Word(t, i * 4.0, i * 4.0 + 3.0)]) for i, t in enumerate(texts)]
    return Lyrics(lines=lines, timing=timing, source=source, source_id=source, title="Midnight Drive", artist="Nova Waves")


_BASE = ["alpha bravo charlie", "delta echo foxtrot", "golf hotel india", "juliet kilo lima",
         "mike november oscar", "papa quebec romeo"]


def _three_sources(wrong_in_top: bool = True):
    top = list(_BASE)
    if wrong_in_top:
        top[2] = "golf hotel oscar"
    a = list(_BASE)
    a[5] = "papa quebec sierra"
    return {
        "top": make_source("top", result=_fusable("top", top, TimingLevel.WORD)),
        "a": make_source("a", result=_fusable("a", a)),
        "b": make_source("b", result=_fusable("b", list(_BASE))),
    }


async def test_final_result_is_fused_not_the_top_candidate(db_path) -> None:
    """ฉบับที่คะแนนสูงสุดผิดบรรทัดหนึ่ง -> ผลสุดท้ายต้องเป็นฉบับที่ระบบรวมเอง ไม่ใช่เว็บเดียว"""
    svc = LyricsService(db_path, sources=_three_sources(), client=object())
    res = await svc.find(TRACK, 200.0)
    assert res.chosen is not None
    assert res.chosen.source == "fusion", "ผลสุดท้ายต้องเป็นฉบับที่ผ่านการรวม"
    assert res.chosen.lines[2].text == "golf hotel india", "บรรทัดที่ผิดต้องถูกแก้ตามเสียงข้างมาก"
    assert res.source_label.startswith("จาก SyncLyrics"), "ป้ายต้องไม่แอบอ้างเป็นเว็บใดเว็บหนึ่ง"


async def test_original_candidates_are_kept_alongside_fusion(db_path) -> None:
    """ต้องเก็บฉบับต้นทางไว้ตรวจย้อนหลัง ไม่ทิ้ง"""
    svc = LyricsService(db_path, sources=_three_sources(), client=object())
    res = await svc.find(TRACK, 200.0)
    kinds = {c.lyrics.source for c in res.candidates}
    assert {"top", "a", "b", "fusion"} <= kinds


async def test_fused_result_is_cached_and_reused_without_searching(db_path) -> None:
    calls = {"n": 0}
    srcs = _three_sources()
    for cls in srcs.values():
        orig = cls.search

        async def counting(self, q, c, orig=orig):
            calls["n"] += 1
            return await orig(self, q, c)
        cls.search = counting  # type: ignore[method-assign]
    svc = LyricsService(db_path, sources=srcs, client=object())
    await svc.find(TRACK, 200.0)
    before = calls["n"]
    res2 = await svc.find(TRACK, 200.0)
    assert calls["n"] == before, "มีฉบับรวมที่เวอร์ชันตรงใน cache แล้วต้องไม่ค้นใหม่"
    assert res2.from_cache and res2.chosen is not None and res2.chosen.source == "fusion"


async def test_legacy_cache_without_fusion_is_not_frozen(db_path) -> None:
    """cache เก่าที่มีแต่เนื้อดิบหลายฉบับ (ก่อนมีระบบรวม) ต้องไม่ข้าม fusion ไปตลอดกาล"""
    svc = LyricsService(db_path, sources=_three_sources(), client=object())
    await svc.find(TRACK, 200.0)
    conn = svc._db()
    conn.execute("DELETE FROM lyrics WHERE source='fusion'")      # จำลอง cache ก่อนมี fusion
    res = await svc.find(TRACK, 200.0)
    assert not res.from_cache, "มีเนื้อดิบพอรวมได้แต่ไม่มีฉบับรวม = ต้องค้น/รวมใหม่"
    assert res.chosen is not None and res.chosen.source == "fusion"


async def test_fusion_failure_falls_back_to_best_candidate(db_path, monkeypatch) -> None:
    """รวมไม่สำเร็จต้องยังมีเนื้อเพลงแสดง ไม่ใช่ว่าง"""
    from app.lyrics import fusion

    def boom(*a, **k):
        raise RuntimeError("fusion พัง")
    monkeypatch.setattr(fusion, "fuse", boom)
    svc = LyricsService(db_path, sources=_three_sources(), client=object())
    res = await svc.find(TRACK, 200.0)
    assert res.chosen is not None and res.chosen.source == "top"


async def test_user_choice_is_not_overridden_by_fusion(db_path) -> None:
    svc = LyricsService(db_path, sources=_three_sources(), client=object())
    first = await svc.find(TRACK, 200.0)
    other = next(c for c in first.candidates if c.lyrics.source == "b")
    cached, _ = await asyncio.to_thread(svc._load_cached, TRACK.video_id)
    lid = next(i for i, c in cached if c.lyrics.source == other.lyrics.source)
    await asyncio.to_thread(svc._set_choice, TRACK.video_id, lid)
    res = await svc.find(TRACK, 200.0)
    assert res.chosen is not None and res.chosen.source == "b", "ผู้ใช้เลือกเองแล้วต้องเคารพ"


async def test_next_candidate_walks_past_rejected_fusion_to_other_versions(db_path) -> None:
    """เสียงปฏิเสธฉบับที่เลือก -> ปุ่ม/ระบบ 'ถัดไป' ต้องเดินผ่านทุกฉบับไม่ซ้ำ ไม่วนอยู่ฉบับเดิม"""
    svc = LyricsService(db_path, sources=_three_sources(), client=object())
    first = await svc.find(TRACK, 200.0)
    seen = [first.chosen.source]
    for _ in range(4):
        nxt = await svc.next_candidate(TRACK.video_id)
        assert nxt.chosen is not None
        seen.append(nxt.chosen.source)
    assert len(set(seen)) == 4, f"ต้องผ่านครบ 4 ฉบับ (fusion + 3 แหล่ง) ก่อนวนกลับ: {seen}"
    assert seen[0] == seen[4], "ครบรอบแล้วต้องกลับมาที่ฉบับแรก"


async def test_stale_wrong_song_in_cache_is_not_shown(db_path) -> None:
    """เนื้อคนละเพลง (ศิลปินอื่น ความยาวต่าง 101 วิ) ที่เคยถูกบันทึกไว้ใน cache ต้องไม่ถูกแสดงต่อ

    ผู้ใช้รายงาน 2026-10-26: เพลง EVERYTHING ของ The Black Skirts ขึ้นเนื้ออังกฤษของเพลงอื่นจาก LRCLIB
    ป้ายเขียนว่า 'ความยาวต่างจากวิดีโอ 101 วิ' คือระบบรู้ว่าผิดแต่ cache ใช้ซ้ำโดยไม่ให้คะแนนใหม่
    """
    import json
    import time

    track = TrackRef(video_id="vidwrong0001", title="EVERYTHING", channel="The Black Skirts", duration=202.0)
    wrong = _fusable("lrclib", ["First you'll see me on the news,", "Then never again", "I'm rolling in my grave",
                                 "Regret regret", "more words here", "and more words"])
    wrong.title, wrong.artist, wrong.duration = "Everything", "Some Other Artist", 101.0
    svc = LyricsService(db_path, sources={}, client=object())
    svc._upsert_track(track, None)
    conn = svc._db()
    # จำลองผลที่ถูกบันทึกไว้ตอนก่อนมีเกณฑ์ตรวจ: คะแนนสูงทั้งที่เป็นคนละเพลง
    conn.execute("INSERT INTO lyrics(video_id, source, source_id, timing, language, score, payload, fetched_at) "
                 "VALUES(?,?,?,?,?,?,?,?)",
                 (track.video_id, wrong.source, wrong.source_id, wrong.timing.value, None, 85.0,
                  json.dumps(wrong.to_dict(), ensure_ascii=False), time.time()))
    res = await svc.find(track, 202.0)
    assert res.chosen is None, "ฉบับคนละเพลงต้องไม่ถูกแสดงแม้ cache จะจำคะแนนเก่าไว้สูง"


async def test_next_candidate_never_walks_into_low_score_candidates(db_path) -> None:
    """'ลองตัวถัดไป' ต้องไม่ลงไปหาฉบับที่คะแนนต่ำกว่าเกณฑ์รับ (มักเป็นเพลงอื่น)"""
    srcs = _three_sources()
    junk = _fusable("junk", ["zulu yankee xray"] * 6)
    junk.title, junk.artist = "Totally Different Song", "Nobody"     # cache เก็บชื่อจาก Lyrics เอง
    srcs["junk"] = make_source("junk", result=junk, title="Totally Different Song", artist="Nobody")
    svc = LyricsService(db_path, sources=srcs, client=object())
    first = await svc.find(TRACK, 200.0)
    seen = {first.chosen.source}
    for _ in range(6):
        nxt = await svc.next_candidate(TRACK.video_id)
        if nxt.chosen is not None:
            seen.add(nxt.chosen.source)
    assert "junk" not in seen, f"ไม่ควรเดินไปถึงฉบับคนละเพลง: {seen}"


def test_stored_names_only_apply_when_they_are_a_swap_of_the_current_parse() -> None:
    """ชื่อใน DB ที่ตัวแยกรุ่นเก่าเดาผิด (เช่น Regret / Everything Everything) ต้องไม่ทับชื่อจากวิดีโอ"""
    from app.lyrics.title_parser import parse_track, swap_meta

    meta = parse_track(TrackRef(video_id="v1", title="EVERYTHING", channel="The Black Skirts", duration=202.0))
    assert LyricsService._apply_stored_names(meta, ("Regret", "Everything Everything")) is meta
    sw = swap_meta(meta)
    assert LyricsService._apply_stored_names(meta, (sw.title, sw.artist)) == sw
