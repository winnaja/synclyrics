

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
