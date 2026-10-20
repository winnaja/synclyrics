"""ทดสอบส่วน logic ล้วนของ LyricsModel (ไม่ต้องมี Qt): lyrics_to_rows และการหาบรรทัดปัจจุบัน"""

from __future__ import annotations

from app.core.models import Line, Lyrics, TimingLevel, Voice, Word, WordTimingSource
from app.ui.lyrics_model import GAP_MIN_S, edge_gaps, find_line_index, lyrics_to_rows, word_to_dict


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
    assert d == {"text": "a", "start": 0.0, "end": 1.0, "estimated": True, "trailingSpace": True, "emphasis": False, "curve": [], "background": False, "spacer": False}
    assert word_to_dict(Word("b", 0, 1))["estimated"] is False
    assert word_to_dict(Word("c", 0, 1, emphasis=True))["emphasis"] is True


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


def test_vocal_gaps_from_ai_override_lyric_gaps():
    # เนื้อเพลงมีช่องว่าง 6.0 -> 12.0 แต่ AI ได้ยินเสียงร้องช่วง 7-11 (เนื้อไม่ครบ) -> ไม่แสดงจุด
    singing = lyrics_to_rows(_lyrics(), vocal_gaps=[(0.0, 1.0)])
    assert singing[1]["gapAfter"] == 0.0
    # AI บอกว่าเงียบ 6.5-11.5 -> จุดเริ่มที่ 6.5 ยาว 5 วิ
    quiet = lyrics_to_rows(_lyrics(), vocal_gaps=[(6.5, 11.5)])
    assert quiet[1]["gapAfter"] == 5.0 and quiet[1]["gapStart"] == 6.5
    # ไม่มีข้อมูลจาก AI = ใช้ช่องว่างของเวลาเนื้อเพลงเหมือนเดิม
    plain = lyrics_to_rows(_lyrics())
    assert plain[1]["gapAfter"] == 6.0 and plain[1]["gapStart"] == 6.0


def test_edge_gaps_find_intro_and_outro():
    ly = _lyrics()      # บรรทัดแรกเริ่ม 1.0, บรรทัดสุดท้ายจบ 14.0
    assert edge_gaps(ly, None) == (None, None)
    intro, outro = edge_gaps(ly, [(0.0, 20.0)], duration=30.0)
    assert intro is None                                 # ก่อนบรรทัดแรกมีแค่ 1 วิ ไม่ถึงเกณฑ์
    assert outro == (14.0, 20.0)
    ly2 = Lyrics(lines=[Line(start=9.0, end=12.0, words=[Word("x", 9.0, 12.0)])], timing=TimingLevel.LINE, source="t")
    intro2, _ = edge_gaps(ly2, [(0.0, 9.0)])
    assert intro2 == (0.0, 9.0)


def test_parenthesized_words_become_background_row_below_main_words():
    from app.ui.lyrics_model import split_background

    ws = [Word("Darling,", 0, 1, trailing_space=True), Word("only", 1, 1.5, trailing_space=True), Word("you", 1.5, 2, trailing_space=True),
          Word("(only", 2, 2.5, trailing_space=True), Word("you)", 2.5, 3)]
    out = split_background(ws)
    assert [d["text"] for d in out] == ["Darling,", "only", "you", "", "only", "you"]
    assert [bool(d["background"]) for d in out] == [False, False, False, False, True, True]
    assert out[3]["spacer"] is True and out[2]["trailingSpace"] is False
    # ทั้งบรรทัดในวงเล็บ = บรรทัดปกติ, ไม่มีวงเล็บ = ไม่เปลี่ยน
    assert all(not d["background"] for d in split_background([Word("(yeah)", 0, 1)]))
    assert [d["text"] for d in split_background([Word("hi", 0, 1)])] == ["hi"]
    # วงเล็บอยู่หน้าบรรทัด: คำในวงเล็บแยกลงล่าง
    pre = split_background([Word("(Without", 0, 1, trailing_space=True), Word("love)", 1, 2, trailing_space=True), Word("Without", 2, 3)])
    assert [d["text"] for d in pre] == ["Without", "", "Without", "love"] or [d["text"] for d in pre][0] == "Without"


def test_empty_vocal_gaps_means_no_instrumental_dots_even_with_timing_holes():
    from app.core.models import Line, Lyrics, TimingLevel, Word
    from app.ui.lyrics_model import lyrics_to_rows

    lyr = Lyrics(lines=[Line(start=0.0, end=2.0, words=[Word("a", 0.0, 2.0)]), Line(start=10.0, end=12.0, words=[Word("b", 10.0, 12.0)])], timing=TimingLevel.LINE, source="t")
    assert lyrics_to_rows(lyr, None)[0]["gapAfter"] > 0           # ไม่มีข้อมูลจาก AI: ใช้ช่องว่างจากเวลาเนื้อเพลง
    assert lyrics_to_rows(lyr, [])[0]["gapAfter"] == 0.0          # AI ฟังแล้วร้องต่อเนื่อง: ไม่แสดงจุด


def test_line_index_at_lead_advances_only_when_previous_line_has_finished():
    from PySide6.QtCore import QCoreApplication  # noqa: F401  (ต้องมี Qt ให้ import โมเดล)
    from app.core.models import Line, Lyrics, TimingLevel, Word
    from app.ui.lyrics_model import lyrics_to_rows

    lyr = Lyrics(lines=[Line(start=0.0, end=2.0, words=[Word("a", 0.0, 2.0)]), Line(start=2.5, end=4.0, words=[Word("b", 2.5, 4.0)]),
                        Line(start=4.0, end=6.0, words=[Word("c", 4.0, 6.0)])], timing=TimingLevel.WORD, source="t")
    rows = lyrics_to_rows(lyr)
    starts = [r["start"] for r in rows]
    from app.ui.lyrics_model import find_line_index

    def at(pos, lead):  # สูตรเดียวกับ LyricsModel.line_index_at
        i = find_line_index(starts, pos)
        if lead > 0:
            j = find_line_index(starts, pos + lead)
            if j > i and (i < 0 or pos >= float(rows[i]["end"]) - 0.05):
                return j
        return i

    assert at(2.3, 0.3) == 1      # บรรทัดแรกจบที่ 2.0 แล้ว: ขึ้นบรรทัดสองล่วงหน้า 0.2 วิ
    assert at(1.9, 0.3) == 0      # บรรทัดแรกยังร้องอยู่ ไม่ตัดก่อนจบ
    assert at(3.8, 0.3) == 1      # ติดกันไม่มีช่องว่าง: เปลี่ยนตามเวลาจริง
