"""แปลเนื้อเพลง: แผนการแปล (ซ้ำ/บริบท) + ตัวประสานฝั่งหลักกับ AI จำลอง"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.ai import translate_job as tj
from app.ai.translator import LyricsTranslator, needs_translation
from app.core import events as ev
from app.core.models import Line, Lyrics, TimingLevel, Word


def make(lines: list[str], lang: str | None = "en", translations: list[str | None] | None = None) -> Lyrics:
    out = []
    for i, t in enumerate(lines):
        ln = Line(i * 4.0, i * 4.0 + 3.0, [Word(w, i * 4.0, i * 4.0 + 1.0, trailing_space=True) for w in t.split()])
        if translations:
            ln.translation = translations[i]
        out.append(ln)
    return Lyrics(lines=out, timing=TimingLevel.LINE, source="lrclib", source_id="1", language=lang)


def test_nllb_code_mapping_and_fallback():
    assert tj.nllb_code("ja") == "jpn_Jpan" and tj.nllb_code("en-US") == "eng_Latn" and tj.nllb_code(None) == tj.DEFAULT_SRC
    assert tj.nllb_code("xx") == tj.DEFAULT_SRC


def test_plan_dedupes_repeated_lines_and_gives_short_lines_context():
    unique, index_of, ctx = tj.plan(["I love you so", "", "Oh", "I love you, so!", "Baby"])
    assert unique == ["I love you so", "Oh", "Baby"]
    assert index_of == {0: 0, 2: 1, 3: 0, 4: 2}
    assert ctx == {"Baby": "I love you, so!"}          # "Oh" มาหลังบรรทัดว่าง = ไม่มีบริบท


def test_needs_translation_rules():
    assert needs_translation(make(["hello there"]))[0] is True
    assert needs_translation(make(["สวัสดีครับ"], lang="th"))[0] is False
    assert needs_translation(make(["hello there"]), enabled=False)[0] is False
    assert needs_translation(make(["hello there"], translations=["สวัสดีนะ"]))[0] is False      # มีคำแปลไทยจากแหล่งแล้ว
    assert needs_translation(make(["hello there"], translations=["你好"]))[0] is True               # คำแปลจีน ไม่ใช่ไทย
    assert needs_translation(None)[0] is False


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, topic, payload):
        self.events.append((topic, payload))


class FakeAi:
    available = True
    started = True

    def __init__(self) -> None:
        self.submits: list[dict] = []
        self.handler = None

    def submit_translate(self, video_id, lines, source_lang, target_lang, handler):
        self.submits.append({"video_id": video_id, "lines": lines, "src": source_lang, "tgt": target_lang})
        self.handler = handler
        return "t1"

    def cancel_video(self, video_id):
        pass


def test_translator_submits_saves_publishes_and_reuses_cache(tmp_path: Path):
    cfg = {"translate": {"enabled": True, "model": "m1", "target_lang": "tha_Thai"}}
    ai, bus = FakeAi(), FakeBus()
    tr = LyricsTranslator(ai, bus, tmp_path / "t.sqlite3", cfg)
    ly = make(["hello there", "my friend"])
    asyncio.run(tr.start("vid00000001", ly))
    assert ai.submits[0]["lines"] == ["hello there", "my friend"] and ai.submits[0]["src"] == "en" and ai.submits[0]["tgt"] == "tha_Thai"
    ai.handler({"type": "result", "payload": {"job_id": "t1", "kind": "translate_final", "data": {"translations": ["สวัสดี", "เพื่อนของฉัน"]}}})
    published = [p for t, p in bus.events if t == ev.TRANSLATION_READY]
    assert published[-1]["translations"] == ["สวัสดี", "เพื่อนของฉัน"] and published[-1]["lang"] == "th"

    ai2, bus2 = FakeAi(), FakeBus()
    asyncio.run(LyricsTranslator(ai2, bus2, tmp_path / "t.sqlite3", cfg).start("vid00000001", make(["hello there", "my friend"])))
    assert ai2.submits == [] and [p for t, p in bus2.events if t == ev.TRANSLATION_READY][-1]["translations"][0] == "สวัสดี"

    ai3, bus3 = FakeAi(), FakeBus()                                  # เปลี่ยนโมเดลแปล = ผลเก่าใช้ไม่ได้
    cfg3 = {"translate": {"enabled": True, "model": "m2"}}
    asyncio.run(LyricsTranslator(ai3, bus3, tmp_path / "t.sqlite3", cfg3).start("vid00000001", make(["hello there", "my friend"])))
    assert len(ai3.submits) == 1


def test_translator_ignores_mismatched_or_empty_results(tmp_path: Path):
    ai, bus = FakeAi(), FakeBus()
    tr = LyricsTranslator(ai, bus, tmp_path / "t.sqlite3", {"translate": {"enabled": True, "model": "m"}})
    asyncio.run(tr.start("vid00000001", make(["a b", "c d"])))
    ai.handler({"type": "result", "payload": {"job_id": "t1", "kind": "translate_final", "data": {"translations": ["", ""]}}})
    assert [p for t, p in bus.events if t == ev.TRANSLATION_READY] == []
