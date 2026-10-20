"""จับคู่เนื้อเพลงกับ transcript (ไม่ใช้ torch) — เคสสังเคราะห์: เวลาเลื่อนทั้งเพลง, ฟังผิด/ข้ามบรรทัด, ภาษาไทยไม่มีช่องว่าง"""

from __future__ import annotations

from app.ai.pipeline.match import InLine, TWord, match_lines, norm_chars

LYRICS = [
    "walking down the empty street", "city lights are fading slow", "i can hear your voice again",
    "echoing through the night", "hold me close and never let go", "we are dancing in the rain",
    "every moment feels so real", "stay with me until the dawn", "the world is turning round",
    "nothing else can bring me down", "singing out into the sky", "this is where we belong",
]


def build(shift: float = 8.0, drop: set[int] = frozenset(), typo: set[int] = frozenset(), with_src: bool = True):
    lines, trans, truth = [], [], []
    for k, text in enumerate(LYRICS):
        true_start = 20.0 + k * 6.0
        words = text.split()
        truth.append(true_start)
        src_start = true_start - shift
        lines.append(InLine(words=words, start=src_start if with_src else None, end=src_start + 5.0 if with_src else None))
        if k in drop:
            continue
        for wi, w in enumerate(words):
            ws = true_start + wi * 1.0
            t = w.replace("e", "a") if (k in typo and wi % 2 == 0) else w
            trans.append(TWord(t, ws, ws + 0.9))
    return lines, trans, truth


def test_norm_chars_keeps_thai_marks_and_drops_punctuation():
    assert norm_chars("Hello, World!") == "helloworld"
    assert norm_chars("เกี่ยวกัน ไหม?") == "เกี่ยวกันไหม"


def test_whole_song_shift_is_recovered():
    lines, trans, truth = build(shift=8.0)
    res = match_lines(lines, trans)
    assert res.coverage > 0.95 and all(l.resolved for l in res.lines)
    for out, t in zip(res.lines, truth):
        assert abs(out.start - t) < 0.3
    assert abs(res.offset_s - 8.0) < 0.3


def test_misheard_words_and_missing_line_still_align():
    lines, trans, truth = build(shift=-15.0, drop={5}, typo={2, 7})
    res = match_lines(lines, trans)
    assert not res.lines[5].resolved                       # เสียงไม่มีบรรทัดนี้ -> ประมาณจากจุดยึดข้างเคียง
    assert abs(res.lines[5].start - truth[5]) < 0.6        # เวลาต้นฉบับเลื่อนคงที่ จึงประมาณได้ใกล้
    for i, (out, t) in enumerate(zip(res.lines, truth)):
        if i != 5:
            assert abs(out.start - t) < 0.5, i
    starts = [l.start for l in res.lines]
    assert starts == sorted(starts)


def test_words_inside_a_line_follow_the_voice():
    lines, trans, truth = build()
    res = match_lines(lines, trans)
    line = res.lines[3]
    assert len(line.words) == 4
    for wi, (s, e, conf) in enumerate(line.words):
        assert abs(s - (truth[3] + wi)) < 0.2 and e > s and conf > 0.9


def test_lyrics_without_any_timestamps_get_anchored_times():
    lines, trans, truth = build(with_src=False, drop={4})
    res = match_lines(lines, trans)
    assert not res.lines[4].resolved
    assert truth[3] < res.lines[4].start < truth[5]        # อยู่ระหว่างบรรทัดข้างเคียงที่ resolved
    assert res.offset_s is None


def test_wrong_lyrics_give_low_coverage():
    lines = [InLine(words=["completely", "different", "song", "about", "nothing"], start=0.0, end=3.0) for _ in range(5)]
    _, trans, _ = build()
    res = match_lines(lines, trans)
    assert res.coverage < 0.4


def test_thai_without_spaces_matches_by_characters():
    lines = [InLine(words=["เกี่ยว", "กัน", "ไหม"], start=1.0, end=3.0), InLine(words=["ฉัน", "ยัง", "รอ", "เธอ"], start=5.0, end=8.0)]
    trans = [TWord("เกี่ยวกัน", 21.0, 22.0), TWord("ไหม", 22.0, 22.6), TWord("ฉันยังรอเธอ", 25.0, 27.0)]
    res = match_lines(lines, trans)
    assert res.lines[0].resolved and res.lines[1].resolved
    assert abs(res.lines[0].start - 21.0) < 0.3 and abs(res.lines[1].start - 25.0) < 0.3


def test_no_transcript_returns_source_untouched_shape():
    lines, _, _ = build()
    res = match_lines(lines, [])
    assert len(res.lines) == len(lines) and "no_anchor" in res.notes and res.coverage == 0.0


def test_group_words_into_lines_breaks_on_gaps_and_length():
    from app.ai.pipeline.match import group_words_into_lines

    words = [TWord("hello", 0, 0.5), TWord("world", 0.5, 1.0), TWord("again", 5.0, 5.5), TWord("now", 5.5, 6.0)]
    lines = group_words_into_lines(words)
    assert [ln.words for ln in lines] == [["hello", "world"], ["again", "now"]]
    assert lines[0].start == 0 and lines[1].end == 6.0
    long = [TWord("w" * 10, i * 0.5, i * 0.5 + 0.4) for i in range(12)]
    assert all(len(ln.words) <= 9 for ln in group_words_into_lines(long))


def test_chars_matching_a_far_away_repeat_do_not_stretch_a_line():
    # บรรทัด "hold me close" มีคำ "me" ไปจับคู่กับเสียงอีกช่วงที่ห่างไป 40 วิ (ฮุกซ้ำ) — บรรทัดต้องไม่ยืดข้ามช่วงนั้น
    lines = [InLine(words=["hold", "me", "close", "tonight"], start=10.0, end=14.0), InLine(words=["other", "line", "here"], start=20.0, end=23.0)]
    trans = [TWord("hold", 50.0, 50.5), TWord("me", 50.5, 51.0), TWord("close", 51.0, 51.6), TWord("tonight", 51.6, 52.4),
             TWord("other", 60.0, 60.5), TWord("line", 60.5, 61.0), TWord("here", 61.0, 61.5), TWord("me", 91.0, 91.5)]
    res = match_lines(lines, trans)
    assert abs(res.lines[0].start - 50.0) < 0.3 and res.lines[0].end - res.lines[0].start < 4.0


def _remix_case():
    """เนื้อเพลงเรียง A B C D แต่เสียงร้องเรียง C D X A B (X = ท่อนที่ไม่มีในเนื้อเพลง) — เรียงลำดับตามเนื้อเพลงไม่ได้"""
    lyr = {k: t.split() for k, t in zip("ABCD", ["walking down the empty street", "city lights are fading slow",
                                                  "i can hear your voice again", "echoing through the night"])}
    lines = [InLine(words=lyr[k], start=10.0 + 6 * i, end=14.0 + 6 * i) for i, k in enumerate("ABCD")]
    order = [("C", 5.0), ("D", 11.0), ("X", 17.0), ("A", 23.0), ("B", 29.0)]
    x_words = "completely different rap verse about money".split()
    trans = []
    for k, t0 in order:
        for wi, w in enumerate(x_words if k == "X" else lyr[k]):
            trans.append(TWord(w + ("," if wi == len(lyr.get(k, x_words)) - 1 else ""), t0 + wi * 0.8, t0 + wi * 0.8 + 0.7, 0.9))
    return lines, trans


def test_reconstruct_orders_lines_by_the_voice_and_uses_lyric_text_when_similar():
    from app.ai.pipeline.match import reconstruct_by_transcript

    lines, trans = _remix_case()
    rr = reconstruct_by_transcript(lines, trans)
    starts = [ln.start for ln in rr.lines]
    assert starts == sorted(starts) and len(rr.lines) == 5
    assert [ln.src for ln in rr.lines] == [[2], [3], None, [0], [1]]       # ข้อความจากเนื้อเพลงที่ตรง · ท่อนที่ไม่มีใช้ข้อความที่ AI ฟังได้
    assert rr.lines[2].text_words[:2] == ["completely", "different"]
    assert abs(rr.lines[3].start - 23.0) < 0.2 and abs(rr.lines[0].start - 5.0) < 0.2
    assert 0.5 < rr.coverage < 1.0


def test_reconstruct_with_no_lyrics_keeps_transcript_text():
    from app.ai.pipeline.match import reconstruct_by_transcript

    _, trans = _remix_case()
    rr = reconstruct_by_transcript([], trans)
    assert rr.coverage == 0.0 and all(ln.src is None for ln in rr.lines) and len(rr.lines) >= 3


def test_clean_transcript_drops_loops_and_gibberish_and_reliability_check():
    from app.ai.pipeline.match import clean_transcript, transcript_reliable

    loop = [TWord("yeah,", i * 0.3, i * 0.3 + 0.2, 0.5) for i in range(200)]
    junk = [TWord("Ayayay" * 20, 70.0, 75.0, 0.4)]
    real = [TWord(w, i, i + 0.5, 0.9) for i, w in enumerate(("word%d" % n for n in range(60)))]
    cleaned = clean_transcript(loop + junk + real)
    assert len(cleaned) == 3 + len(real)
    assert transcript_reliable(real) is True
    assert transcript_reliable(loop) is False                        # วนคำเดียว = hallucination
    assert transcript_reliable(real[:10]) is False                   # คำน้อยเกิน
    assert transcript_reliable([TWord(w.text, w.start, w.end, 0.2) for w in real]) is False   # มั่นใจต่ำ


def test_line_matched_to_a_far_repeat_is_rejected_by_neighbor_consistency():
    lines, trans, truth = build(shift=8.0)
    # บรรทัด 5 ("we are dancing in the rain") ถูกร้องจริงที่ 50 วิ แต่เสียงอีกช่วงไกล (95 วิ) ก็มีประโยคเดียวกันซ้ำ — ทำให้จับคู่ไปที่ช่วงหลังได้
    trans = [w for w in trans if not (truth[5] <= w.start < truth[5] + 4.5)]
    for wi, w in enumerate(LYRICS[5].split()):
        trans.append(TWord(w, 95.0 + wi, 95.9 + wi, 0.9))
    res = match_lines(lines, sorted(trans, key=lambda w: w.start))
    assert not res.lines[5].resolved                                  # ไม่เชื่อ: เพื่อนบ้านบอกว่าควรอยู่แถว 50 วิ
    assert abs(res.lines[5].start - truth[5]) < 1.0                   # ประมาณจากเวลาต้นฉบับ+จุดยึดแทน ใกล้ความจริง


def test_traditional_and_simplified_chinese_match_each_other():
    assert norm_chars("風箏的大距離") == norm_chars("风筝的大距离")
    lines = [InLine(words=list("风筝的大距离吹得好远"), start=10.0, end=14.0)]
    trans = [TWord(c, 30.0 + i * 0.3, 30.3 + i * 0.3, 0.9) for i, c in enumerate("風箏的大距離吹得好遠")]
    res = match_lines(lines, trans)
    assert res.lines[0].resolved and abs(res.lines[0].start - 30.0) < 0.3


def test_known_whisper_credit_hallucinations_are_detected():
    from app.ai.pipeline.transcribe import is_hallucination

    assert is_hallucination("优独播剧场——YoYo Television Series Exclusive") and is_hallucination("Thank you for watching!")
    assert not is_hallucination("I got you moonlight you're my starlight") and not is_hallucination("ฉันยังรอเธอ")


def test_fill_missing_lines_places_unheard_lyric_lines_in_voiced_gap_between_anchors():
    from app.ai.pipeline.match import InLine, ReLine, ReResult, fill_missing_lines

    lines = [InLine(words=["aaaa"]), InLine(words=["bbbbbbbb"]), InLine(words=["cccc"])]
    res = ReResult(lines=[ReLine(0.0, 2.0, [(0.0, 2.0, 1.0)], ["aaaa"], [0]), ReLine(10.0, 12.0, [(10.0, 12.0, 1.0)], ["cccc"], [2])], coverage=0.6)
    out = fill_missing_lines(res, lines, [(0.0, 12.0)], 12.0)
    mid = [r for r in out.lines if r.src == [1]]
    assert len(mid) == 1 and 2.0 <= mid[0].start < mid[0].end <= 10.0
    assert [r.start for r in out.lines] == sorted(r.start for r in out.lines)
    # เสียงร้องไม่มีในช่วงนั้น (ดนตรีล้วน) = ไม่เติม
    assert len(fill_missing_lines(res, lines, [(0.0, 2.0), (10.0, 12.0)], 12.0).lines) == 2


def test_tidy_lines_drops_duplicate_overlapping_line_and_trims_time_overlap():
    from app.ai.pipeline.match import ReLine, tidy_lines

    a = ReLine(10.0, 12.0, [(10.0, 12.0, 1.0)], ["God", "knows", "why", "I", "need", "you"], [79, 80])
    dup = ReLine(10.4, 11.5, [(10.4, 11.5, 1.0)], ["why", "I", "need", "you"], [79])
    nxt = ReLine(11.8, 13.0, [(11.8, 13.0, 1.0)], ["something", "else"], [81])
    out = tidy_lines([nxt, dup, a])
    assert [r.src for r in out] == [[79, 80], [81]]
    assert out[0].end <= out[1].start + 1e-9                    # เวลาไม่ทับกัน


def test_retime_unresolved_uses_web_time_plus_median_delta_of_neighbours():
    from app.ai.pipeline.match import InLine, retime_unresolved

    lines = [InLine(words=["a"], start=10.0, end=12.0), InLine(words=["b", "c"], start=15.0, end=17.0), InLine(words=["d"], start=20.0, end=22.0)]
    out = [{"i": 0, "resolved": True, "words": [[10.6, 11.0, 1.0]], "start": 10.6, "end": 11.0},
           {"i": 1, "resolved": False, "words": [[1.0, 2.0, 0.0], [2.0, 3.0, 0.0]], "start": 1.0, "end": 3.0},
           {"i": 2, "resolved": True, "words": [[20.7, 21.0, 1.0]], "start": 20.7, "end": 21.0}]
    retime_unresolved(out, lines)
    assert abs(out[1]["start"] - 15.65) < 0.1 and out[1]["end"] > out[1]["start"]


def test_heard_extras_collects_uncovered_confident_words_as_background_lines():
    from app.ai.pipeline.match import InLine, TWord, heard_extras

    lines = [InLine(words=["main", "lead", "line"]), InLine(words=["another", "lead", "line"])]
    out = [{"i": 0, "start": 10.0, "end": 12.0, "words": [[10.0, 12.0, 1.0]], "resolved": True},
           {"i": 1, "start": 20.0, "end": 22.0, "words": [[20.0, 22.0, 1.0]], "resolved": True}]
    tr = [TWord("main", 10.0, 10.5, 0.9), TWord("lead", 10.6, 11.0, 0.9), TWord("line", 11.1, 12.0, 0.9),
          TWord("ooh", 15.0, 15.3, 0.9), TWord("la", 15.4, 15.7, 0.9), TWord("la", 15.8, 16.1, 0.9),    # คอรัสที่ไม่มีในเว็บ
          TWord("blah", 30.0, 30.4, 0.2)]                                                                  # มั่นใจต่ำ = ทิ้ง
    ex = heard_extras(out, lines, tr)
    assert len(ex) == 1 and ex[0]["voice"] == "background" and ex[0]["extra"] and 15.0 <= ex[0]["start"] < 16.2


def test_heard_extras_skips_word_that_belongs_to_neighbouring_lyric_line():
    from app.ai.pipeline.match import InLine, TWord, heard_extras

    lines = [InLine(words=["That", "someday", "it", "would", "lead", "me", "back", "to", "you"])]
    out = [{"i": 0, "start": 55.0, "end": 58.0, "words": [[55.0, 58.0, 1.0]], "resolved": True}]
    tr = [TWord("That", 53.8, 54.3, 0.95), TWord("that", 55.0, 55.3, 0.9)]
    assert heard_extras(out, lines, tr) == []


def test_heard_extras_keeps_single_word_adlib_but_drops_short_stray_word():
    from app.ai.pipeline.match import InLine, TWord, heard_extras

    lines = [InLine(words=["some", "lead", "words", "here"]), InLine(words=["more", "lead", "words", "there"])]
    out = [{"i": 0, "start": 10.0, "end": 12.0, "words": [[10.0, 12.0, 1.0]], "resolved": True},
           {"i": 1, "start": 30.0, "end": 32.0, "words": [[30.0, 32.0, 1.0]], "resolved": True}]
    tr = [TWord("yeah", 20.0, 20.6, 0.9), TWord("then", 25.0, 25.3, 0.9)]
    ex = heard_extras(out, lines, tr)
    assert [e["text_words"] for e in ex] == [["yeah"]]


def test_emphasis_parse_and_pick_prefers_recurring_hook_words_and_spacing():
    from app.ai.emphasis import pick_emphasis
    from app.ai.emphasis_job import parse_answers

    lines = ["But I'm a creep", "I'm a weirdo", "What the hell am I doing here", "I don't belong here", "But I'm a creep",
             "Whatever you want", "I wish I was special", "You're so special", "But I'm a creep"]
    ans = parse_answers("1: creep\n2: weirdo\n3: hell\n4: belong\n5: creep\n6: -\n7: special\n8: special\n9: invented", lines)
    assert ans[0] == "creep" and 5 not in ans and 8 not in ans            # '-' และคำที่ไม่อยู่ในบรรทัดถูกทิ้ง
    picked = pick_emphasis(lines, ans)
    assert picked.get("butimacreep") == "creep"                           # คำฮุกที่ซ้ำมาก + บรรทัดซ้ำนับเป็นบรรทัดเดียว
    assert len(picked) <= 3


def test_ctc_to_result_accepts_consistent_offset_and_rejects_scrambled_alignment():
    from app.ai.pipeline.align import Span
    from app.ai.pipeline.match import InLine, ctc_to_result

    lines = [InLine(words=["a", "b"], start=10.0 + 5 * i, end=12.0 + 5 * i) for i in range(10)]
    good = [[Span(10.6 + 5 * i, 11.0 + 5 * i, 0.5), Span(11.0 + 5 * i, 11.6 + 5 * i, 0.5)] for i in range(10)]     # เว็บช้ากว่า 0.6 วิคงที่
    good[4] = [Span(40.0, 40.5, 0.3), Span(40.5, 41.0, 0.3)]                                                       # บรรทัดเดียวหลุดจากแนว
    res = ctc_to_result(good, lines)
    assert res is not None and res.offset_s is not None and abs(res.offset_s - 0.6) < 0.01
    assert sum(1 for ln in res.lines if ln.resolved) == 9 and not res.lines[4].resolved
    assert abs(res.lines[4].start - (10.0 + 20 + 0.6)) < 0.01                  # บรรทัดที่หลุด = เวลาเว็บ + ค่ากลาง
    scrambled = [[Span(30.0 - 3 * i, 30.5 - 3 * i, 0.3), Span(30.5 - 3 * i, 31.0 - 3 * i, 0.3)] for i in range(10)]
    assert ctc_to_result(scrambled, lines) is None                              # โครงสร้างต่าง = ใช้เส้นทาง Whisper
    assert ctc_to_result([None] * 10, lines) is None
