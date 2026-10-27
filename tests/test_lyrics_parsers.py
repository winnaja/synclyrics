"""parser LRC / YRC / QRC / VTT และเครื่องมือภาษาไทย — ใช้ข้อความสมมติเท่านั้น (ห้ามเนื้อเพลงจริง)"""

from __future__ import annotations

from app.core.models import TimingLevel, WordTimingSource
from app.lyrics import thai
from app.lyrics.parsers.lrc import parse_lrc, parse_plain, parse_time_tag
from app.lyrics.parsers.qrc import parse_qrc
from app.lyrics.parsers.subtitles import parse_vtt
from app.lyrics.parsers.yrc import parse_yrc

LRC = """[ar:Nova Waves]
[ti:Midnight Drive]
[length:03:20]
[00:10.50]alpha beta gamma
[00:14.00]delta epsilon
[00:18.250]
[00:20.00][00:40.00]zeta eta
"""


def test_parse_time_tag() -> None:
    assert parse_time_tag("01:02.50") == 62.5
    assert parse_time_tag("not time") is None


def test_lrc_line_level() -> None:
    ly = parse_lrc(LRC, duration=200)
    assert ly.timing == TimingLevel.LINE
    assert ly.title == "Midnight Drive" and ly.artist == "Nova Waves" and ly.duration == 200
    assert [ln.text for ln in ly.lines] == ["alpha beta gamma", "delta epsilon", "zeta eta", "zeta eta"]
    assert ly.lines[0].start == 10.5
    # บรรทัดว่างเป็นตัวบอกจบบรรทัดก่อนหน้า
    assert ly.lines[1].end == 18.25
    # หลาย timestamp ต่อบรรทัด เรียงตามเวลา
    assert [ln.start for ln in ly.lines[2:]] == [20.0, 40.0]


def test_lrc_offset_shifts_earlier() -> None:
    ly = parse_lrc("[offset:+500]\n[00:10.00]hello world\n")
    assert ly.lines[0].start == 9.5


def test_lrc_enhanced_word_level() -> None:
    text = "[00:10.00]<00:10.00>hel<00:10.40>lo <00:10.90>world <00:11.60>\n[00:12.00]<00:12.00>again <00:12.50>now <00:13.00>\n"
    ly = parse_lrc(text)
    assert ly.timing == TimingLevel.WORD
    w = ly.lines[0].words
    assert [x.text for x in w] == ["hel", "lo", "world"]
    assert (w[1].start, w[1].end) == (10.4, 10.9)
    assert w[2].end == 11.6
    assert w[1].trailing_space and not w[2].trailing_space
    assert all(x.timing == WordTimingSource.SOURCE for x in w)


def test_lrc_garbage_does_not_crash() -> None:
    assert parse_lrc("").lines == []
    assert parse_lrc("ไม่ใช่ lrc เลย\n[xx:yy]ผิด").lines == []


def test_parse_plain() -> None:
    ly = parse_plain("line one\n\nline two\n")
    assert ly.timing == TimingLevel.NONE and [ln.text for ln in ly.lines] == ["line one", "line two"]


def test_yrc_with_translation_and_metadata() -> None:
    yrc = (
        '{"t":0,"c":[{"tx":"credit: "}]}\n'
        "[1000,2000](1000,500,0)hel(1500,500,0)lo (2000,1000,0)world\n"
        "[4000,1500](4000,700,0)next(4700,800,0) line\n"
    )
    tl = "[00:01.20]แปลบรรทัดแรก\n[00:04.10]แปลบรรทัดสอง\n"
    ly = parse_yrc(yrc, translation_lrc=tl)
    assert ly.timing == TimingLevel.WORD and len(ly.lines) == 2
    assert [w.text for w in ly.lines[0].words] == ["hel", "lo", "world"]
    assert ly.lines[0].words[0].start == 1.0 and ly.lines[0].words[0].end == 1.5
    assert ly.lines[0].translation == "แปลบรรทัดแรก" and ly.lines[1].translation == "แปลบรรทัดสอง"
    assert ly.has_translation


def test_qrc_plain_text_form() -> None:
    qrc = '<Lyric_1 LyricType="1" LyricContent="[offset:0]&#10;[1000,1500]hel(1000,500)lo (1500,500)all(2000,500)"/>'
    ly = parse_qrc(qrc)
    assert ly.timing == TimingLevel.WORD
    assert [w.text for w in ly.lines[0].words] == ["hel", "lo", "all"]
    assert ly.lines[0].words[2].end == 2.5


def test_vtt_filters_noise_and_dedups() -> None:
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000
[Music]

00:00:05.000 --> 00:00:07.000
first <c>line</c>

00:00:07.000 --> 00:00:08.000
first line

00:00:09.500 --> 00:00:12.000
second line
"""
    ly = parse_vtt(vtt)
    assert [ln.text for ln in ly.lines] == ["first line", "second line"]
    assert ly.lines[0].end == 8.0 and ly.timing == TimingLevel.LINE


# ---------------- ภาษาไทย ----------------
def test_graphemes_never_split_marks() -> None:
    for g in thai.graphemes("เกี่ยวข้อง น้ำใจ"):
        assert not g.startswith(("ั", "ิ", "ี", "่", "้", "ำ")), g
    assert "".join(thai.graphemes("เกี่ยวข้อง")) == "เกี่ยวข้อง"
    assert "น้ำ" in thai.graphemes("น้ำ")  # วรรณยุกต์ + สระอำ ติดพยัญชนะ


def test_tokenize_mixed() -> None:
    toks = thai.tokenize("ฉันรักเธอ my love")
    assert "my" in toks and "love" in toks and len(toks) >= 4
    assert all(t.strip() for t in toks)


def test_detect_language() -> None:
    assert thai.detect_language("สวัสดีครับ") == "th"
    assert thai.detect_language("hello there") == "en"
    assert thai.detect_language("こんにちは世界") == "ja"
    assert thai.detect_language("안녕하세요") == "ko"
    assert thai.detect_language("12345 !!") is None


def test_syllable_count_positive() -> None:
    assert thai.syllable_count("love") == 1
    assert thai.syllable_count("beautiful") >= 3
    assert thai.syllable_count("สวัสดี") >= 1


def test_credit_lines_are_dropped_everywhere() -> None:
    from app.lyrics.parsers.lrc import is_credit_line

    assert is_credit_line("作词 : Abel Tesfaye/Daniel Lopatin")
    assert is_credit_line("Produced by: Someone")
    assert is_credit_line("เนื้อร้อง : ใครสักคน")
    assert not is_credit_line("I wrote a letter: it never came")
    lrc = parse_lrc("[00:01.00]作词 : A/B\n[00:02.00]作曲 : C\n[00:12.00]real line here\n")
    assert [ln.text for ln in lrc.lines] == ["real line here"]
    yrc = parse_yrc("[0,1000](0,500,0)作词 (500,500,0): X\n[2000,1000](2000,500,0)hello (2500,500,0)you")
    assert [ln.text for ln in yrc.lines] == ["hello you"]
    assert [ln.text for ln in parse_plain("Lyrics by: X\nreal line\n").lines] == ["real line"]


def test_vtt_drops_bracketed_sound_descriptions_but_keeps_inline_brackets():
    from app.lyrics.parsers.subtitles import parse_vtt

    vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n[Ring]\n\n00:00:03.000 --> 00:00:05.000\nThe club is not the best place [whoo]\n\n"
           "00:00:06.000 --> 00:00:07.000\n[Applause]\n")
    assert [ln.text for ln in parse_vtt(vtt).lines] == ["The club is not the best place [whoo]"]


def test_header_title_artist_line_at_zero_is_dropped() -> None:
    """บรรทัด 'ชื่อเพลง - ศิลปิน' ที่ 0 วิ (QQ/NetEase) ไม่ใช่เนื้อร้อง"""
    from app.lyrics.parsers.lrc import parse_lrc

    ly = parse_lrc("[00:00.00]사랑이 잘 - IU (아이유)/吴赫 (오혁)\n[00:14.51]미리 말할게 사과는 안 해\n[00:18.08]아무 말 없이 너 후회 안 해\n",
                   source="qqmusic")
    assert ly.lines[0].text == "미리 말할게 사과는 안 해"
