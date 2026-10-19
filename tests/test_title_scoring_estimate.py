"""แยกชื่อเพลง, ให้คะแนนผลเนื้อเพลง, เวลาแบบประมาณ"""

from __future__ import annotations

import json
import time

import pytest

from app.core.models import Line, Lyrics, TimingLevel, TrackMeta, TrackRef, Word, WordTimingSource
from app.lyrics import scoring
from app.lyrics.parsers.lrc import parse_lrc, parse_plain
from app.lyrics.sources.base import LyricsCandidate
from app.lyrics.timing_estimate import estimate_line, estimate_lyrics
from app.lyrics.title_parser import _no_brackets, clean_title, parse_track
from tests.conftest import FIXTURES

CASES = json.loads((FIXTURES / "titles.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_title_cases(case: dict) -> None:
    meta = parse_track(TrackRef(**case["track"]))
    exp = case["expect"]
    assert meta.title == exp["title"]
    assert meta.artist == exp["artist"]
    assert sorted(meta.version_tags) == sorted(exp["tags"])
    for q in exp.get("queries_contain", []):
        assert q in meta.queries
    assert meta.queries[0].casefold() in (
        f"{meta.artist} {meta.title}".casefold(),
        f"{_no_brackets(meta.artist)} {_no_brackets(meta.title)}".casefold(),
    )
    assert len(set(q.casefold() for q in meta.queries)) == len(meta.queries)  # ไม่มีคำค้นซ้ำ


def test_clean_title_keeps_meaningful_brackets() -> None:
    assert clean_title("Song (Part II)")[0] == "Song (Part II)"


# ---------------- scoring ----------------
def _cand(title: str, artist: str, dur: float | None, timing: TimingLevel, source: str = "lrclib") -> LyricsCandidate:
    ly = Lyrics(lines=[Line(0, 1, [Word("x", 0, 1)])], timing=timing, source=source)
    return LyricsCandidate(lyrics=ly, matched_title=title, matched_artist=artist, matched_duration=dur)


META = TrackMeta(title="Midnight Drive", artist="Nova Waves", duration=200.0, queries=())


def test_scoring_prefers_right_song() -> None:
    good = _cand("Midnight Drive", "Nova Waves", 201.0, TimingLevel.LINE)
    wrong = _cand("Sunny Morning", "Other Band", 200.0, TimingLevel.WORD)
    assert scoring.score_candidate(good, META, 200.0) > scoring.score_candidate(wrong, META, 200.0)
    assert good.score >= scoring.MIN_ACCEPT_SCORE > wrong.score


def test_scoring_rejects_wrong_duration() -> None:
    far = _cand("Midnight Drive", "Nova Waves", 420.0, TimingLevel.WORD)
    assert scoring.score_candidate(far, META, 200.0) == 0.0


def test_scoring_long_mv_is_penalised_not_rejected() -> None:
    near = _cand("Midnight Drive", "Nova Waves", 200.0, TimingLevel.LINE)
    long_mv = _cand("Midnight Drive", "Nova Waves", 170.0, TimingLevel.LINE)  # MV ยาวกว่าเสียง 30 วิ
    s_near, s_long = scoring.score_candidate(near, META, 200.0), scoring.score_candidate(long_mv, META, 200.0)
    assert scoring.MIN_ACCEPT_SCORE <= s_long < s_near
    assert long_mv.score_detail["duration_diff_s"] == 30.0


def test_scoring_swapped_order_matches_via_alt_titles() -> None:
    meta = TrackMeta(title="INK WARUNTORN", artist="Some Song [ X ]", duration=300.0,
                     alt_titles=("Some Song [ X ] - INK WARUNTORN", "Some Song [ X ]", "Some Song", "INK WARUNTORN"))
    c = _cand("Some Song", "Ink Waruntorn", 300.0, TimingLevel.LINE)
    assert scoring.score_candidate(c, meta, 300.0) >= 70


def test_scoring_timing_level_order() -> None:
    word = _cand("Midnight Drive", "Nova Waves", 200.0, TimingLevel.WORD)
    line = _cand("Midnight Drive", "Nova Waves", 200.0, TimingLevel.LINE)
    none = _cand("Midnight Drive", "Nova Waves", 200.0, TimingLevel.NONE)
    s = [scoring.score_candidate(c, META, 200.0) for c in (word, line, none)]
    assert s[0] > s[1] > s[2]


def test_scoring_version_mismatch_penalised() -> None:
    live = _cand("Midnight Drive (Live)", "Nova Waves", 200.0, TimingLevel.LINE)
    studio = _cand("Midnight Drive", "Nova Waves", 200.0, TimingLevel.LINE)
    assert scoring.score_candidate(studio, META, 200.0) > scoring.score_candidate(live, META, 200.0)


def test_scoring_direct_source_bonus_and_bounds() -> None:
    subs = _cand("", "", None, TimingLevel.LINE, source="youtube_subs")
    sc = scoring.score_candidate(subs, META, 200.0)
    assert sc > 85 and sc <= 100
    assert "direct_bonus" in subs.score_detail


def test_scoring_unknown_duration_is_not_fatal() -> None:
    c = _cand("Midnight Drive", "Nova Waves", None, TimingLevel.NONE, source="lyrics_ovh")
    assert scoring.score_candidate(c, META, None) >= scoring.MIN_ACCEPT_SCORE


# ---------------- timing estimate ----------------
def test_estimate_line_distribution_and_last_word_weight() -> None:
    ln = Line(10.0, 14.0, [Word("one two three four", 10.0, 14.0)])
    out = estimate_line(ln)
    ws = out.words
    assert [w.text for w in ws] == ["one", "two", "three", "four"]
    assert ws[0].start == 10.0 and abs(ws[-1].end - 14.0) < 1e-6
    assert all(a.end == pytest.approx(b.start) for a, b in zip(ws, ws[1:]))
    assert all(w.timing == WordTimingSource.ESTIMATED for w in ws)
    assert ws[-1].duration > ws[0].duration  # คำท้ายได้เวลามากกว่า
    assert ws[0].trailing_space and not ws[-1].trailing_space


def test_estimate_line_caps_long_gap() -> None:
    ln = Line(0.0, 30.0, [Word("short line", 0.0, 30.0)])  # ตามด้วยช่วงดนตรียาว
    out = estimate_line(ln)
    assert out.words[-1].end < 10.0


def test_estimate_line_thai() -> None:
    ln = Line(5.0, 9.0, [Word("ฉันรักเธอ มากเลย", 5.0, 9.0)])
    out = estimate_line(ln)
    assert len(out.words) >= 3 and out.words[0].start == 5.0
    assert out.words[-1].end <= 9.0 + 1e-6


def test_estimate_lyrics_untimed_spreads_over_song() -> None:
    ly = parse_plain("\n".join(f"this is line number {i}" for i in range(10)))
    out = estimate_lyrics(ly, 200.0)
    starts = [ln.start for ln in out.lines]
    assert starts == sorted(starts) and starts[0] >= 200 * 0.05 and out.lines[-1].end <= 200 * 0.95
    assert out.timing == TimingLevel.NONE  # ยังบอกว่าต้องให้ AI จัดเวลา
    assert all(w.timing == WordTimingSource.ESTIMATED for ln in out.lines for w in ln.words)


def test_estimate_lyrics_uses_vocal_segments() -> None:
    ly = parse_plain("a b c\nd e f\ng h i")
    out = estimate_lyrics(ly, 200.0, vocal_segments=[(30.0, 90.0)])
    assert out.lines[0].start == pytest.approx(30.0) and out.lines[-1].end == pytest.approx(90.0)


def test_estimate_lyrics_word_level_untouched_and_fast() -> None:
    wl = parse_lrc("[00:01.00]<00:01.00>a <00:01.50>b <00:02.00>\n")
    assert estimate_lyrics(wl, 100.0) is wl
    big = parse_lrc("\n".join(f"[{i // 60:02d}:{i % 60:02d}.00]ฉันรักเธอ more words here {i}" for i in range(80)))
    estimate_lyrics(big, 300.0)  # warm-up pythainlp
    t = time.perf_counter()
    estimate_lyrics(big, 300.0)
    assert time.perf_counter() - t < 0.2  # เป้า < 50ms ต่อเพลง ให้เผื่อเครื่องช้า
