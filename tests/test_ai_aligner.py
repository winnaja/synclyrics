"""LyricsAligner: ฟังก์ชันล้วน + ลำดับการทำงานกับ AI จำลอง (ไม่ใช้ torch/เครือข่าย)"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.ai import aligner as al
from app.core import events as ev
from app.core.models import Line, Lyrics, TimingLevel, Word, WordTimingSource


def make_lyrics(shift: float = 0.0, text2: str = "second line here") -> Lyrics:
    l1 = Line(1.0 + shift, 4.0 + shift, [Word("hello", 1.0 + shift, 2.0 + shift, trailing_space=True), Word("world", 2.0 + shift, 4.0 + shift)])
    l2 = Line(6.0 + shift, 9.0 + shift, [Word(w, 6.0 + shift + i, 7.0 + shift + i, trailing_space=i < 2) for i, w in enumerate(text2.split())])
    return Lyrics(lines=[l1, l2], timing=TimingLevel.LINE, source="lrclib", source_id="42", language="en", duration=200.0)


def test_lyrics_key_ignores_timing_but_not_text():
    assert al.lyrics_key(make_lyrics(0)) == al.lyrics_key(make_lyrics(30))
    assert al.lyrics_key(make_lyrics()) != al.lyrics_key(make_lyrics(text2="another one entirely"))


def test_lyrics_to_input_hides_times_when_source_has_none():
    ly = make_lyrics()
    assert al.lyrics_to_input(ly)[0]["start"] == 1.0
    ly.timing = TimingLevel.NONE
    inp = al.lyrics_to_input(ly)
    assert inp[0]["start"] is None and inp[0]["word_times"] is None and inp[0]["words"] == ["hello", "world"]


def test_apply_result_sets_aligned_times_and_emphasis_and_keeps_missing_lines():
    ly = make_lyrics()
    res = [{"i": 0, "start": 21.0, "end": 25.0, "resolved": True, "words": [[21.0, 22.0, 0.9], [22.0, 24.5, 0.8]]}]
    out = al.apply_result(ly, res)
    assert out.lines[0].start == 21.0 and out.lines[0].words[0].timing == WordTimingSource.ALIGNED
    assert out.lines[0].words[1].emphasis is True and out.lines[0].words[0].emphasis is False   # คำท้ายที่ลากเสียง ≥ 0.7 วิ
    assert out.lines[0].words[0].trailing_space is True and out.lines[0].text == "hello world"
    assert out.lines[1].start == 6.0                                                          # ไม่มีในผล = คงเดิม
    assert out.timing == TimingLevel.WORD
    assert ly.lines[0].start == 1.0                                                           # ต้นฉบับไม่ถูกแก้


def test_apply_result_resolved_only_and_word_count_mismatch_are_skipped():
    ly = make_lyrics()
    res = [{"i": 0, "start": 21.0, "end": 25.0, "resolved": False, "words": [[21.0, 22.0, 0.3], [22.0, 24.5, 0.3]]},
           {"i": 1, "start": 30.0, "end": 33.0, "resolved": True, "words": [[30.0, 31.0, 0.9]]}]   # จำนวนคำไม่ตรง
    out = al.apply_result(ly, res, resolved_only=True)
    assert out.lines[0].start == 1.0 and out.lines[1].start == 6.0


def test_transcript_to_lyrics_marks_ai_and_spaces_by_language():
    res = [{"i": 0, "text_words": ["hello", "there"], "words": [[1.0, 1.5, 0.8], [1.5, 2.0, 0.8]]}]
    en = al.lyrics_from_transcript(res, "en", 100.0)
    assert en.ai_transcribed and en.lines[0].text == "hello there"
    th = al.lyrics_from_transcript([{"i": 0, "text_words": ["สวัสดี", "ครับ"], "words": [[1.0, 1.5, 0.8], [1.5, 2.0, 0.8]]}], "th", 100.0)
    assert th.lines[0].text == "สวัสดีครับ"


def test_gaps_from_vocals_includes_intro_and_outro():
    gaps = al.gaps_from_vocals([[10.0, 30.0], [32.0, 60.0]], 70.0)
    assert gaps == [[0.0, 10.0], [60.0, 70.0]]


# ---------------- ลำดับการทำงาน ----------------
class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: dict) -> None:
        self.events.append((topic, payload))

    def retimed(self) -> list[dict]:
        return [p for t, p in self.events if t == ev.LYRICS_RETIMED]


class FakeAi:
    available = True
    started = True

    def __init__(self) -> None:
        self.submits: list[dict] = []
        self.cancelled: list[str] = []
        self.handler = None

    def submit_align(self, video_id, audio_path, lines, language, start_hint, handler, alts=None):
        self.submits.append({"video_id": video_id, "audio_path": audio_path, "lines": lines, "language": language, "hint": start_hint, "alts": alts or []})
        self.handler = handler
        return "job1"

    def cancel_video(self, video_id):
        self.cancelled.append(video_id)


class FakeMedia:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.calls = 0

    def fetch_and_download(self, video_id, target):
        self.calls += 1
        target.mkdir(parents=True, exist_ok=True)
        f = target / f"{video_id}.webm"
        f.write_bytes(b"x")
        return None, SimpleNamespace(path=f)


def make_aligner(tmp_path: Path, ai: FakeAi, bus: FakeBus, **kw):
    paths = SimpleNamespace(stems_cache_dir=tmp_path / "stems", cache_dir=tmp_path / "cache")
    return al.LyricsAligner(ai, bus, tmp_path / "t.sqlite3", paths, FakeMedia(tmp_path), {"analysis": {"algo_version": 1}}, **kw)


FINAL = {"video_id": "vid00000001", "mode": "match", "duration": 200.0, "coverage": 0.9, "version_mismatch": False, "language": "en",
         "offset_s": 20.0, "vocal_segments": [[20.0, 60.0]],
         "lines": [{"i": 0, "start": 21.0, "end": 25.0, "resolved": True, "words": [[21.0, 22.0, 0.9], [22.0, 24.5, 0.8]]},
                   {"i": 1, "start": 26.0, "end": 29.0, "resolved": True, "words": [[26.0, 27.0, 0.9], [27.0, 28.0, 0.9], [28.0, 29.0, 0.9]]}]}


def run(coro):
    return asyncio.run(coro)


def test_flow_partial_then_final_saved_then_reused_from_cache(tmp_path):
    ai, bus = FakeAi(), FakeBus()
    aligner = make_aligner(tmp_path, ai, bus)
    ly = make_lyrics()
    vid = "vid00000001"
    run(aligner.start(vid, ly, "จาก LRCLIB", 200.0))
    assert len(ai.submits) == 1 and ai.submits[0]["audio_path"].endswith(f"{vid}.webm")
    ai.handler({"type": "result", "payload": {"job_id": "job1", "kind": "align_partial", "data": {
        "lines": FINAL["lines"][:1], "windows_done": 1, "windows_total": 4, "coverage": 0.5}}})
    ai.handler({"type": "result", "payload": {"job_id": "job1", "kind": "align_final", "data": dict(FINAL)}})
    evs = bus.retimed()
    assert evs[0]["final"] is False and "25%" in evs[0]["source_label"] and evs[0]["lyrics"].lines[0].start == 21.0
    assert evs[-1]["final"] is True and evs[-1]["lyrics"].lines[1].start == 26.0 and evs[-1]["gaps"] == [[0.0, 20.0], [60.0, 200.0]]
    assert not (tmp_path / "cache" / "analysis" / vid).exists()          # ไฟล์เสียงชั่วคราวถูกลบ

    bus2 = FakeBus()
    aligner2 = make_aligner(tmp_path, FakeAi(), bus2)
    run(aligner2.start(vid, make_lyrics(shift=50.0), "จาก LRCLIB", 200.0))      # เวลาต้นฉบับต่างกันแต่ข้อความเดียวกัน = ใช้ผลเดิม
    assert aligner2.ai.submits == [] and bus2.retimed()[-1]["lyrics"].lines[0].start == 21.0


def test_changed_lyrics_text_is_not_served_from_cache(tmp_path):
    ai, bus = FakeAi(), FakeBus()
    aligner = make_aligner(tmp_path, ai, bus)
    run(aligner.start("vid00000001", make_lyrics(), "x", 200.0))
    ai.handler({"type": "result", "payload": {"job_id": "job1", "kind": "align_final", "data": dict(FINAL)}})
    ai2 = FakeAi()
    run(make_aligner(tmp_path, ai2, FakeBus()).start("vid00000001", make_lyrics(text2="completely other words"), "x", 200.0))
    assert len(ai2.submits) == 1


def test_version_mismatch_keeps_original_times_and_asks_for_next_candidate(tmp_path):
    ai, bus = FakeAi(), FakeBus()
    asked: list[str] = []
    aligner = make_aligner(tmp_path, ai, bus, on_mismatch=asked.append)
    run(aligner.start("vid00000001", make_lyrics(), "จาก X", 200.0))
    bad = dict(FINAL, version_mismatch=True, coverage=0.05)
    ai.handler({"type": "result", "payload": {"job_id": "job1", "kind": "align_final", "data": bad}})
    last = bus.retimed()[-1]
    assert last["lyrics"].lines[0].start == 1.0 and "คนละเวอร์ชัน" in last["source_label"] and asked == ["vid00000001"]


def test_cancel_drops_late_events(tmp_path):
    ai, bus = FakeAi(), FakeBus()
    aligner = make_aligner(tmp_path, ai, bus)
    run(aligner.start("vid00000001", make_lyrics(), "x", 200.0))
    aligner.cancel("vid00000001")
    ai.handler({"type": "result", "payload": {"job_id": "job1", "kind": "align_final", "data": dict(FINAL)}})
    assert bus.retimed() == [] and "vid00000001" in ai.cancelled


def test_no_lyrics_transcribes_and_publishes_ai_labeled_lyrics(tmp_path):
    ai, bus = FakeAi(), FakeBus()
    aligner = make_aligner(tmp_path, ai, bus)
    run(aligner.start("vid00000002", None, "", 120.0))
    assert ai.submits[0]["lines"] == []
    data = {"mode": "transcribe", "duration": 120.0, "language": "en", "vocal_segments": [[5.0, 100.0]],
            "lines": [{"i": 0, "start": 5.0, "end": 7.0, "resolved": True, "text_words": ["la", "la"], "words": [[5.0, 6.0, 0.8], [6.0, 7.0, 0.8]]}]}
    ai.handler({"type": "result", "payload": {"job_id": "job1", "kind": "align_final", "data": data}})
    out = bus.retimed()[-1]
    assert out["lyrics"].ai_transcribed and out["lyrics"].lines[0].text == "la la" and out["final"] is True


def test_ai_unavailable_does_nothing(tmp_path):
    ai, bus = FakeAi(), FakeBus()
    ai.available = False
    ai.started = False
    aligner = make_aligner(tmp_path, ai, bus)
    run(aligner.start("vid00000001", make_lyrics(), "x", 200.0))
    assert ai.submits == [] and bus.retimed() == []


def test_regroup_tokens_merges_thai_fragments_into_real_words():
    texts = ["ฟ", "ั", "ง", "ท", "ร", "ึ", "ง", "ใ", "จ"]
    times = [(i * 0.1, i * 0.1 + 0.1, 0.8) for i in range(len(texts))]
    words, out = al.regroup_tokens(texts, times, lambda t: ["ฟัง", "ทรึง", "ใจ"])
    assert words == ["ฟัง", "ทรึง", "ใจ"] and len(out) == 3
    assert abs(out[0][0] - 0.0) < 1e-9 and abs(out[0][1] - 0.3) < 1e-9 and abs(out[2][1] - 0.9) < 1e-9


def test_thai_transcript_lyrics_use_whole_words_not_fragments():
    frags = ["สวั", "ส", "ดี", "ครับ"]
    res = [{"i": 0, "text_words": frags, "words": [[1.0 + k * 0.4, 1.4 + k * 0.4, 0.8] for k in range(4)]}]
    th = al.lyrics_from_transcript(res, "th", 100.0)
    assert th.lines[0].text == "สวัสดีครับ" and 1 <= len(th.lines[0].words) <= 3


def test_reconstruct_lyrics_mix_lyric_text_and_ai_text():
    base = make_lyrics()
    rows = [{"start": 5.0, "end": 8.0, "src": [0], "text_words": ["hello", "world"], "words": [[5.0, 6.0, 0.9], [6.0, 8.0, 0.8]]},
            {"start": 9.0, "end": 11.0, "src": None, "text_words": ["new", "words"], "words": [[9.0, 10.0, 0.7], [10.0, 11.0, 0.7]]}]
    out = al.lyrics_from_reconstruct(base, rows, "en", 120.0)
    assert [ln.text for ln in out.lines] == ["hello world", "new words"]
    assert out.lines[0].words[0].trailing_space is True and out.ai_transcribed is True     # ครึ่งหนึ่งของบรรทัดมาจากข้อความที่ AI ฟังได้
    assert out.lines[0].words[1].emphasis is True            # คำท้ายลากเสียง 2 วิ
    assert out.duration == 120.0 and out.lines[1].start == 9.0


def test_clean_label_drops_stale_warnings():
    assert al.clean_label("จาก NetEase · ทีละบรรทัด · ความยาวต่างจากวิดีโอ 111 วิ เวลาอาจเลื่อน · จัดเวลาจากเสียง 40%") == "จาก NetEase · ทีละบรรทัด"


def test_ai_picks_alternate_lyrics_version_that_matches_the_audio_best():
    import asyncio

    from app.ai import aligner as al

    base = make_lyrics()
    alt = make_lyrics()
    h = al.LyricsAligner.__new__(al.LyricsAligner)
    h._alts = {"v": [(alt, "ALT")]}
    got, label = h._pick_base("v", base, "MAIN", {"alt": 1})
    assert got is alt and "ALT" in label and "ตรงกับเสียง" in label
    got, label = h._pick_base("v", base, "MAIN", {"alt": 0})
    assert got is base and label == "MAIN"
    assert h._pick_base("v", base, "MAIN", {"alt": 5}) == (base, "MAIN")                # ดัชนีเกิน = ใช้ฉบับหลัก
    _ = asyncio
