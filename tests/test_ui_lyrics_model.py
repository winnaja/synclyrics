"""ทดสอบส่วน logic ล้วนของ LyricsModel (ไม่ต้องมี Qt): lyrics_to_rows และการหาบรรทัดปัจจุบัน"""

from __future__ import annotations

from app.core.models import Line, Lyrics, TimingLevel, Voice, Word, WordTimingSource
from app.ui.lyrics_model import GAP_MIN_S, find_line_index, lyrics_to_rows, word_to_dict


def _lyrics() -> Lyrics:
    # ข้อความสมมติทั้งหมด
    l1 = Line(
        start=1.0, end=3.0,
        words=[
            Word("ทดสอบ", 1.0, 2.0),
            Word("hello", 2.0, 3.0, timing=WordTimingSource.ESTIMATED, trailing_space=True),
            Word("world", 3.0, 3.5),
        ],
        translation="คำแปลสมมติ", romanization="tod-sob",
    )
    l2 = Line(start=4.0, end=6.0, words=[Word("สอง", 4.0, 6.0)], voice=Voice.SECOND)
    # ช่องว่าง 6.0 -> 12.0 = ช่วงดนตรี
    l3 = Line(start=12.0, end=14.0, words=[Word("สาม", 12.0, 14.0)], voice=Voice.BACKGROUND)
    return Lyrics(lines=[l1, l2, l3], timing=TimingLevel.WORD, source="test")


def test_rows_basic_fields() -> None:
    rows = lyrics_to_rows(_lyrics())
    assert len(rows) == 3
    r = rows[0]
    assert (r["start"], r["end"], r["voice"]) == (1.0, 3.0, "main")
    assert r["translation"] == "คำแปลสมมติ"
    assert r["romanization"] == "tod-sob"
    assert r["text"] == "ทดสอบhello world"
    assert [w["text"] for w in r["words"]] == ["ทดสอบ", "hello", "world"]
    assert rows[1]["voice"] == "second"
    assert rows[2]["voice"] == "background"
    assert rows[1]["translation"] == ""  # None -> ว่าง


def test_word_dict_flags() -> None:
    w = Word("a", 0.0, 1.0, timing=WordTimingSource.ESTIMATED, trailing_space=True)
    d = word_to_dict(w)
    assert d == {"text": "a", "start": 0.0, "end": 1.0, "estimated": True, "trailingSpace": True}
    assert word_to_dict(Word("b", 0, 1))["estimated"] is False


def test_gap_after_only_for_long_gaps() -> None:
    rows = lyrics_to_rows(_lyrics())
    assert rows[0]["gapAfter"] == 0.0  # 3.0 -> 4.0 สั้น
    assert rows[1]["gapAfter"] == 6.0  # 6.0 -> 12.0
    assert rows[2]["gapAfter"] == 0.0  # บรรทัดสุดท้ายไม่มีถัดไป
    assert GAP_MIN_S == 4.0


def test_empty_lyrics() -> None:
    assert lyrics_to_rows(Lyrics(lines=[], timing=TimingLevel.NONE, source="x")) == []


def test_find_line_index_bisect() -> None:
    starts = [1.0, 4.0, 12.0]
    assert find_line_index(starts, 0.0) == -1  # ก่อนบรรทัดแรก
    assert find_line_index(starts, 0.999) == -1
    assert find_line_index(starts, 1.0) == 0  # เท่ากับ start = ถึงบรรทัดนั้นแล้ว
    assert find_line_index(starts, 3.99) == 0
    assert find_line_index(starts, 4.0) == 1
    assert find_line_index(starts, 8.0) == 1  # ช่วงว่าง ยังอยู่บรรทัดก่อนหน้า
    assert find_line_index(starts, 12.0) == 2
    assert find_line_index(starts, 9999.0) == 2  # เลยบรรทัดสุดท้าย
    assert find_line_index([], 5.0) == -1


def test_resolve_font_prefers_main_then_fallback() -> None:
    from app.ui.app_window import resolve_font

    assert resolve_font("SF Thonburi", ["Prompt"], ["Arial", "sf thonburi"]) == "sf thonburi"
    assert resolve_font("SF Thonburi", ["Prompt", "Kanit"], ["Arial", "Kanit"]) == "Kanit"
    assert resolve_font("SF Thonburi", ["Prompt"], ["Arial"]) == "SF Thonburi"  # ไม่มีเลย: ให้ Qt หาแทน


def test_default_font_is_sf_thonburi() -> None:
    from app.core.config import Settings

    assert Settings().lyrics_look.font_family == "SF Thonburi"
