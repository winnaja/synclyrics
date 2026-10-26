

def _cand(texts, source, score):
    from app.core.models import Line, Lyrics, TimingLevel, Word
    from app.lyrics.sources.base import LyricsCandidate

    lines = [Line(start=i * 3.0, end=i * 3.0 + 2.5, words=[Word(w, i * 3.0, i * 3.0 + 2.5) for w in t.split()]) for i, t in enumerate(texts)]
    return LyricsCandidate(lyrics=Lyrics(lines=lines, timing=TimingLevel.LINE, source=source), score=score)


def test_apply_consensus_prefers_version_that_agrees_with_other_sources():
    from app.lyrics import scoring

    base = ["You know all that's fake", "and God knows why I need you", "I wish I was special", "But I'm a creep", "I'm a weirdo"]
    other = ["Completely different words here", "nothing alike at all", "another unrelated line", "yet more text", "and so on"]
    a, b, c = _cand(base, "lrclib", 70.0), _cand(base, "netease", 66.0), _cand(other, "qqmusic", 72.0)
    scoring.apply_consensus([a, b, c])
    assert a.score > c.score and b.score > c.score                  # สองแหล่งตรงกัน ชนะฉบับเดี่ยวที่คะแนนปกติสูงกว่าเล็กน้อย
    scoring.apply_consensus([a, b, c])                              # เรียกซ้ำไม่บวกซ้ำ
    assert abs(a.score - (70.0 + scoring.CONSENSUS_WEIGHT * a.score_detail["consensus"])) < 0.05


def test_apply_consensus_leaves_single_candidate_unchanged():
    from app.lyrics import scoring

    a = _cand(["one two three", "four five six", "seven eight nine", "ten eleven twelve"], "lrclib", 80.0)
    scoring.apply_consensus([a])
    assert a.score == 80.0


def test_same_title_and_artist_survives_big_duration_gap():
    """เคสจริง: EVERYTHING ของ The Black Skirts ยาว 293 วิ แต่วิดีโอตัดสั้นเหลือ 202 วิ (ต่าง 91 วิ)
    เดิมถูกปฏิเสธเป็น 0 แล้วระบบไปแสดงเนื้อคนละเพลง · ชื่อ+ศิลปินตรงกันต้องไม่ตกเพราะความยาวอย่างเดียว"""
    from app.core.models import Line, Lyrics, TimingLevel, TrackMeta, Word
    from app.lyrics import scoring
    from app.lyrics.sources.base import LyricsCandidate

    meta = TrackMeta(title="EVERYTHING", artist="The Black Skirts")
    lines = [Line(i * 4.0, i * 4.0 + 3.0, [Word("you are my everything", i * 4.0, i * 4.0 + 3.0)]) for i in range(8)]

    def score(title, artist, dur):
        c = LyricsCandidate(lyrics=Lyrics(lines=lines, timing=TimingLevel.LINE, source="lrclib", source_id="1"),
                            matched_title=title, matched_artist=artist, matched_duration=dur)
        return scoring.score_candidate(c, meta, 202.0)

    assert score("EVERYTHING", "The Black Skirts", 293.0) >= scoring.MIN_ACCEPT_SCORE
    # แต่คนละเพลงยังต้องตกเหมือนเดิม
    assert score("Everything", "Some Other Artist", 293.0) < scoring.MIN_ACCEPT_SCORE
    assert score("Another Song", "The Black Skirts", 293.0) < scoring.MIN_ACCEPT_SCORE


def _score_case(title, artist, dur, meta_title="EVERYTHING", meta_artist="The Black Skirts", video=202.0):
    from app.core.models import Line, Lyrics, TimingLevel, TrackMeta, Word
    from app.lyrics import scoring
    from app.lyrics.sources.base import LyricsCandidate

    meta = TrackMeta(title=meta_title, artist=meta_artist)
    lines = [Line(i * 4.0, i * 4.0 + 3.0, [Word("some words", i * 4.0, i * 4.0 + 3.0)]) for i in range(8)]
    c = LyricsCandidate(lyrics=Lyrics(lines=lines, timing=TimingLevel.LINE, source="lrclib", source_id="1"),
                        matched_title=title, matched_artist=artist, matched_duration=dur)
    return scoring.score_candidate(c, meta, video)


def test_same_title_different_artist_is_rejected():
    """ผู้ใช้ติติง: 'ไม่แมชศิลปิน ดูแต่ชื่อเพลง' — ชื่อตรงแต่คนละศิลปิน (Lifehouse/Alanis) เคยได้ 79-81 ผ่านเกณฑ์ง่ายๆ"""
    from app.lyrics import scoring

    assert _score_case("Everything", "Lifehouse", 203.0) < scoring.MIN_ACCEPT_SCORE
    assert _score_case("Everything", "Alanis Morissette", 201.0) < scoring.MIN_ACCEPT_SCORE


def test_same_artist_different_title_is_rejected():
    from app.lyrics import scoring

    assert _score_case("Another Song", "The Black Skirts", 202.0) < scoring.MIN_ACCEPT_SCORE


def test_artist_in_another_script_is_not_treated_as_a_mismatch():
    """黑裙子 = The Black Skirts (คนละระบบอักษร เทียบข้อความไม่ได้) ห้ามตีว่าคนละศิลปินเมื่อความยาวตรง"""
    from app.lyrics import scoring

    assert _score_case("EVERYTHING", "黑裙子", 202.0) >= scoring.MIN_ACCEPT_SCORE
    # แต่ถ้าความยาวไม่ตรงด้วย หลักฐานอ่อนเกินไป ต้องไม่ผ่านง่ายๆ
    assert _score_case("EVERYTHING", "黑裙子", 293.0) < _score_case("EVERYTHING", "黑裙子", 202.0)


def test_video_title_fragment_does_not_vouch_for_a_different_artist():
    """ชื่อเพลง 'EVERYTHING' ต้องไม่ทำให้วง 'Everything Everything' ดูเหมือนศิลปินที่ตรง"""
    from app.core.models import TrackRef
    from app.lyrics.scoring import score_candidate  # noqa: F401
    from app.lyrics import scoring

    assert scoring._similar("The Black Skirts", "Everything Everything") < 0.5
    assert scoring._similar("EVERYTHING", "Regret") < 0.5
    assert TrackRef is not None


def test_other_artist_with_overlapping_title_word_is_rejected():
    """'The Black Skirts - EVERYTHING' ต้องไม่ได้เนื้อของ 'Everything Is Recorded' (เคสจริง ชื่อวิดีโอมีชื่อเพลงรวมกับศิลปิน)"""
    from app.core.models import Line, Lyrics, TimingLevel, Word
    from app.lyrics import scoring
    from app.lyrics.sources.base import LyricsCandidate
    from app.lyrics.title_parser import parse_track
    from app.core.models import TrackRef

    meta = parse_track(TrackRef(video_id="v", title="The Black Skirts - EVERYTHING", channel="The Worst Taste", duration=304.0))
    lines = [Line(i * 4.0, i * 4.0 + 3.0, [Word("x", i * 4.0, i * 4.0 + 3.0)]) for i in range(8)]
    ly = Lyrics(lines=lines, timing=TimingLevel.LINE, source="lrclib", source_id="1")
    c = LyricsCandidate(lyrics=ly, matched_title="Everything Is Recorded", matched_artist="Everything Is Recorded",
                        matched_duration=307.3)
    assert scoring.score_candidate(c, meta, 304.0) < scoring.MIN_ACCEPT_SCORE
