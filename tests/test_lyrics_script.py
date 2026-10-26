"""เนื้อเพลงต้องตรงภาษาของเพลง: เพลงเกาหลีห้ามได้เนื้อจีน/ญี่ปุ่น (ผู้ใช้รายงาน 2026-10-26)

ข้อความที่ใช้เป็นคำสั้นๆ สมมติ ไม่ใช่เนื้อเพลงจริง
"""


def _lyr(texts):
    from app.core.models import Line, Lyrics, TimingLevel, Word

    lines = [Line(i * 3.0, i * 3.0 + 2.5, [Word(t, i * 3.0, i * 3.0 + 2.5)]) for i, t in enumerate(texts)]
    return Lyrics(lines=lines, timing=TimingLevel.LINE, source="x", source_id="x")


def _meta(title, artist="", alts=()):
    from app.core.models import TrackMeta

    return TrackMeta(title=title, artist=artist, alt_titles=tuple(alts))


KO = ["안녕하세요 나는 여기", "사랑해 너를 언제나", "오늘도 그대를 생각해", "별빛 아래에서 만나요"]
JA = ["こんにちは私はここに", "愛してるあなたをいつも", "今日もあなたを想って", "星空の下で会おう"]
ZH = ["你好我在这里", "我爱你永远", "今天也想着你", "在星空下相见"]
TH = ["สวัสดีฉันอยู่ที่นี่", "รักเธอเสมอมา", "วันนี้ก็คิดถึงเธอ", "พบกันใต้แสงดาว"]
EN = ["hello i am here", "i love you always", "thinking of you today", "meet me under stars"]


def test_korean_song_rejects_chinese_and_japanese_lyrics():
    from app.lyrics import scoring

    m = _meta("자각몽 Lucid Dream", "aespa")
    assert scoring.script_factor(_lyr(KO), m)[0] == 1.0
    assert scoring.script_factor(_lyr(ZH), m)[0] < 0.5, "เพลงเกาหลีได้เนื้อจีน ต้องถูกลดคะแนนหนัก"
    assert scoring.script_factor(_lyr(JA), m)[0] < 0.5, "เพลงเกาหลีได้เนื้อญี่ปุ่น ต้องถูกลดคะแนนหนัก"


def test_japanese_song_rejects_chinese_translation():
    """เนื้อจีนที่ไม่มีคานะเลย = ฉบับแปล ไม่ใช่เนื้อเพลงญี่ปุ่น"""
    from app.lyrics import scoring

    m = _meta("夜に駆ける", "YOASOBI")
    assert scoring.script_factor(_lyr(JA), m)[0] == 1.0
    assert scoring.script_factor(_lyr(ZH), m)[0] < 0.5
    assert scoring.script_factor(_lyr(KO), m)[0] < 0.5


def test_thai_song_rejects_korean_and_accepts_thai():
    from app.lyrics import scoring

    m = _meta("รักเธอเสมอ", "ศิลปิน")
    assert scoring.script_factor(_lyr(TH), m)[0] == 1.0
    assert scoring.script_factor(_lyr(KO), m)[0] < 0.5


def test_han_title_accepts_chinese_and_japanese_but_not_korean():
    """ชื่อเป็นฮั่นจื้อล้วนเป็นได้ทั้งจีนและญี่ปุ่น ต้องไม่ปฏิเสธผิด"""
    from app.lyrics import scoring

    m = _meta("星空", "歌手")
    assert scoring.script_factor(_lyr(ZH), m)[0] == 1.0
    assert scoring.script_factor(_lyr(JA), m)[0] == 1.0
    assert scoring.script_factor(_lyr(KO), m)[0] < 0.5


def test_english_title_gives_no_verdict():
    """ชื่ออังกฤษอย่างเดียวบอกภาษาไม่ได้ (K-pop ชื่ออังกฤษมีเยอะ) ต้องไม่ไปลดคะแนนมั่ว"""
    from app.lyrics import scoring

    m = _meta("Midnight Drive", "Nova Waves")
    for t in (KO, JA, ZH, TH, EN):
        assert scoring.script_factor(_lyr(t), m)[0] == 1.0


def test_korean_song_with_english_mixed_lyrics_is_fine():
    """K-pop ที่มีท่อนอังกฤษปนเยอะ ต้องไม่ถูกตีว่าผิดภาษา"""
    from app.lyrics import scoring

    mixed = KO[:2] + EN[:2]
    assert scoring.script_factor(_lyr(mixed), _meta("자각몽", "aespa"))[0] == 1.0


def test_romanized_lyrics_for_korean_song_is_penalised_mildly():
    from app.lyrics import scoring

    f = scoring.script_factor(_lyr(EN), _meta("자각몽 Lucid Dream", "aespa"))[0]
    assert 0.25 < f < 1.0


def test_score_candidate_drops_wrong_script_below_accept_threshold():
    from app.lyrics import scoring
    from app.lyrics.sources.base import LyricsCandidate

    m = _meta("자각몽 Lucid Dream", "aespa")
    good = LyricsCandidate(lyrics=_lyr(KO), matched_title="자각몽 Lucid Dream", matched_artist="aespa",
                           matched_duration=200.0)
    bad = LyricsCandidate(lyrics=_lyr(ZH), matched_title="自觉梦 Lucid Dream", matched_artist="aespa",
                          matched_duration=200.0)
    gs = scoring.score_candidate(good, m, 200.0)
    bs = scoring.score_candidate(bad, m, 200.0)
    assert gs > bs + 20
    assert "script_mismatch" in bad.score_detail and "script_mismatch" not in good.score_detail


def test_fusion_does_not_mix_scripts():
    """ฉบับแปลจีนต้องไม่ถูกเอามารวมกับฉบับเกาหลี"""
    from app.lyrics import fusion
    from app.lyrics.sources.base import LyricsCandidate

    def c(texts, src, score):
        x = LyricsCandidate(lyrics=_lyr(texts), matched_title="t", matched_artist="a")
        x.lyrics.source = src
        x.lyrics.source_id = src
        x.score = score
        x.score_detail = {"base": score}
        return x

    ko1 = c(KO + ["이어지는 노래"] * 2, "a", 90.0)
    zh = c(ZH + ["延续的歌"] * 2, "b", 85.0)
    assert fusion._version_ok(ko1, zh) is False
