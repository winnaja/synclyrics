"""เทสต์การรวมเนื้อเพลงหลายแหล่งเป็นฉบับเดียว (app/lyrics/fusion.py)

ข้อความที่ใช้เป็นคำสมมติ ไม่ใช่เนื้อเพลงจริง
"""


def _cand(texts, source, score, tags=frozenset(), timing=None):
    from app.core.models import Line, Lyrics, TimingLevel, Word
    from app.lyrics.sources.base import LyricsCandidate

    lines = [
        Line(start=i * 3.0, end=i * 3.0 + 2.5,
             words=[Word(w, i * 3.0, i * 3.0 + 2.5, trailing_space=True) for w in t.split()])
        for i, t in enumerate(texts)
    ]
    lyr = Lyrics(lines=lines, timing=timing or TimingLevel.LINE, source=source, source_id=source)
    c = LyricsCandidate(lyrics=lyr, matched_title="t", matched_artist="a")
    c.score = score
    c.score_detail = {"base": score}
    if tags:
        c.lyrics.title = "x " + " ".join(sorted(tags))
    return c


def _texts(cand):
    return [ln.text for ln in cand.lyrics.lines]


BASE = ["alpha bravo charlie", "delta echo foxtrot", "golf hotel india", "juliet kilo lima",
        "mike november oscar", "papa quebec romeo"]


def test_majority_line_replaces_wrong_line_in_top_candidate():
    """ฉบับคะแนนสูงสุดมีบรรทัดหนึ่งผิด อีกสองแหล่งตรงกัน -> ฉบับรวมต้องใช้ของสองแหล่งนั้น"""
    from app.lyrics import fusion

    wrong = list(BASE)
    wrong[2] = "golf hotel oscar"          # ฉบับหลักผิดบรรทัดนี้
    top = _cand(wrong, "lrclib", 90.0)
    # สองแหล่งอิสระเห็นตรงกันที่บรรทัดนี้ แต่ต่างกันที่อื่น (ถ้าเหมือนกันเป๊ะทั้งฉบับ = ลอกกันมา นับเสียงเดียว)
    a_texts = list(BASE)
    a_texts[5] = "papa quebec sierra"
    a = _cand(a_texts, "netease", 70.0)
    b = _cand(BASE, "qqmusic", 65.0)

    got = fusion.fuse([top, a, b])
    assert got is not None, "ควรรวมได้เมื่อมีหลายเสียง"
    fused, report = got
    assert _texts(fused)[2] == BASE[2], "บรรทัดที่ผิดต้องถูกแทนด้วยเสียงข้างมาก"
    assert _texts(fused)[0] == BASE[0], "บรรทัดที่ตรงกันอยู่แล้วต้องไม่เปลี่ยน"
    assert report.lines_replaced == 1
    assert fused.lyrics.source == fusion.SOURCE_NAME, "ต้องเป็นฉบับใหม่ ไม่ใช่อ้างไปยังแหล่งเดิม"


def test_identical_mirrors_do_not_outvote_a_stronger_source():
    """สามเว็บที่ลอกกันมาต้องนับเป็นเสียงเดียว ไม่ใช่สามเสียง"""
    from app.lyrics import fusion

    mirrored = list(BASE)
    mirrored[1] = "delta echo golf"        # ข้อความของกลุ่มที่ลอกกันมา
    top = _cand(BASE, "lrclib", 90.0)
    m1 = _cand(mirrored, "mirror1", 60.0)
    m2 = _cand(mirrored, "mirror2", 60.0)
    m3 = _cand(mirrored, "mirror3", 60.0)

    got = fusion.fuse([top, m1, m2, m3])
    assert got is not None
    fused, report = got
    assert report.voters == 2, "ฉบับที่เหมือนกันเป๊ะต้องยุบเหลือเสียงเดียว"
    assert _texts(fused)[1] == BASE[1], "เสียงที่ลอกกันมาต้องไม่ชนะแหล่งที่คะแนนสูงกว่า"


def test_different_versions_are_not_merged():
    """live/remix ต้องไม่เอามารวมกับฉบับสตูดิโอ"""
    from app.lyrics import fusion
    from app.lyrics.sources.base import LyricsCandidate

    studio = _cand(BASE, "lrclib", 90.0)
    live_texts = list(BASE)
    live_texts[0] = "mike november oscar"
    live = _cand(live_texts, "netease", 85.0)
    live.lyrics.title = "song (Live)"      # scoring._candidate_tags อ่านแท็กจากชื่อ

    got = fusion.fuse([studio, live])
    # เหลือเสียงเดียวหลังตัดคนละเวอร์ชัน = ไม่มีอะไรให้รวม
    assert got is None or _texts(got[0])[0] == BASE[0], "ห้ามดึงข้อความจากคนละเวอร์ชันเข้ามา"
    assert isinstance(studio, LyricsCandidate)


def test_single_source_is_not_fused():
    from app.lyrics import fusion

    assert fusion.fuse([_cand(BASE, "lrclib", 90.0)]) is None


def test_low_score_candidates_cannot_vote():
    """แหล่งที่คะแนนต่ำ (น่าจะคนละเพลง) ไม่มีสิทธิ์โหวต"""
    from app.lyrics import fusion

    junk = _cand(["zulu yankee xray", "whiskey victor uniform"] * 2, "junk", 5.0)
    assert fusion.fuse([_cand(BASE, "lrclib", 90.0), junk]) is None


def test_different_line_splits_still_align():
    """อีกแหล่งรวมสองบรรทัดเป็นบรรทัดเดียว -> ต้องไม่ทำให้บรรทัดอื่นเลื่อนตาม"""
    from app.lyrics import fusion

    merged = ["alpha bravo charlie delta echo foxtrot", BASE[2], BASE[3], BASE[4], BASE[5]]
    top = _cand(BASE, "lrclib", 90.0)
    other = _cand(merged, "netease", 80.0)
    third_texts = list(BASE)
    third_texts[5] = "papa quebec tango"
    third = _cand(third_texts, "qqmusic", 75.0)

    got = fusion.fuse([top, other, third])
    assert got is not None
    fused, _ = got
    assert _texts(fused) == BASE, "โครงของฉบับหลักต้องคงเดิมเมื่ออีกแหล่งแบ่งบรรทัดต่างกัน"


def test_close_vote_keeps_the_spine_text():
    """เสียงปริ่มๆ ต้องไม่สลับข้อความ (กันเนื้อเพลงเปลี่ยนไปมา)"""
    from app.lyrics import fusion

    alt = list(BASE)
    alt[3] = "juliet kilo mike"
    top = _cand(BASE, "lrclib", 80.0)
    other = _cand(alt, "netease", 79.0)
    third = _cand(alt, "qqmusic", 10.0)    # คะแนนต่ำ โหวตไม่ได้

    got = fusion.fuse([top, other, third])
    assert got is not None
    fused, _ = got
    assert _texts(fused)[3] == BASE[3], "ชนะไม่ขาดต้องยึดฉบับหลักไว้"


def test_timing_level_drops_when_text_changed():
    """บรรทัดที่เปลี่ยนข้อความ เวลาทีละคำเดิมใช้ไม่ได้แล้ว ต้องบอกตามจริง"""
    from app.core.models import TimingLevel
    from app.lyrics import fusion

    wrong = list(BASE)
    wrong[1] = "delta echo golf"
    top = _cand(wrong, "lrclib", 90.0, timing=TimingLevel.WORD)
    a_texts = list(BASE)
    a_texts[5] = "papa quebec sierra"
    a = _cand(a_texts, "netease", 80.0)
    b = _cand(BASE, "qqmusic", 75.0)

    fused, report = fusion.fuse([top, a, b])
    assert report.lines_replaced == 1
    assert fused.lyrics.timing == TimingLevel.LINE
