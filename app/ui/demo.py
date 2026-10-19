"""ดู UI เฟส 1 แบบเดี่ยวๆ ด้วยข้อมูลปลอม (ข้อความสมมติ ไม่ใช่เนื้อเพลงจริง) + นาฬิกาปลอมที่เดินเอง

รัน: python -m app.ui.demo   (เพิ่ม --safe เพื่อลองโหมดเรียบ)
"""

from __future__ import annotations

import sys
import time
from typing import Any

from app.core.config import Settings
from app.core.events import LYRICS_READY, PLAYBACK_STATE, TRACK_CHANGED, TRACK_META_READY, EventBus
from app.core.models import (
    Line,
    Lyrics,
    TimingLevel,
    TrackMeta,
    TrackRef,
    Voice,
    Word,
    WordTimingSource,
)
from app.ui.app_window import UiContext, create_ui

DURATION_S = 90.0


class DemoClock:
    """นาฬิกาปลอม: เดินตามเวลาเครื่อง หยุด/เล่น/seek ได้"""

    def __init__(self) -> None:
        self._base = 0.0
        self._t0 = time.perf_counter()
        self._playing = True
        self.generation = 0

    def position(self, at: float | None = None) -> float:
        if not self._playing:
            return self._base
        return min(DURATION_S, self._base + (time.perf_counter() - self._t0))

    @property
    def playing(self) -> bool:
        return self._playing

    def seek(self, s: float) -> None:
        self._base, self._t0 = s, time.perf_counter()
        self.generation += 1

    def toggle(self) -> None:
        self._base = self.position()
        self._t0 = time.perf_counter()
        self._playing = not self._playing


class DemoController:
    """controller ปลอม: ควบคุมแค่นาฬิกาปลอม"""

    def __init__(self, clock: DemoClock, bus: EventBus) -> None:
        self.clock, self.bus = clock, bus

    def toggle_pause(self) -> None:
        self.clock.toggle()
        self.bus.publish(PLAYBACK_STATE, {"playing": self.clock.playing, "video_id": "demo"})

    def seek(self, seconds: float) -> None:
        self.clock.seek(seconds)

    def play_url(self, text: str) -> None:
        print("play_url:", text)

    def adjust_offset(self, delta_s: float) -> None:
        print("offset:", delta_s)

    def next_lyrics_candidate(self) -> None:
        print("next candidate")

    def set_volume(self, v: float) -> None:
        print("volume:", v)


def fake_lyrics() -> Lyrics:
    """เนื้อเพลงสมมติ 8 บรรทัด มีช่วงดนตรีกลางเพลง คู่ และคำแปล"""
    texts = [
        ["ทดสอบ", "ระบบ", "ไฮไลต์", "ทีละคำ"],
        ["this", "is", "a", "made-up", "line"],
        ["ข้อความสมมติ", "สำหรับ", "ดูหน้าตา"],
        ["la", "la", "la", "test", "test"],
        ["เส้นเวลา", "ไหลไป", "เรื่อยๆ"],
        ["another", "fake", "sentence", "here"],
        ["ปิดท้าย", "ด้วย", "บรรทัดปลอม"],
        ["the", "end", "of", "the", "demo"],
    ]
    starts = [4.0, 9.0, 14.0, 19.0, 36.0, 41.0, 46.0, 51.0]  # ช่องว่าง 19->36 = ช่วงดนตรี
    lines: list[Line] = []
    for i, (ws, st) in enumerate(zip(texts, starts)):
        step = 3.6 / len(ws)
        words = [
            Word(
                w, st + k * step, st + (k + 1) * step,
                timing=WordTimingSource.ESTIMATED if i % 3 == 2 else WordTimingSource.SOURCE,
                trailing_space=w.isascii() and k < len(ws) - 1,
            )
            for k, w in enumerate(ws)
        ]
        lines.append(Line(
            start=st, end=st + 3.6, words=words,
            voice=Voice.SECOND if i == 3 else Voice.MAIN,
            translation="(คำแปลสมมติ)" if i == 0 else None,
        ))
    return Lyrics(lines=lines, timing=TimingLevel.WORD, source="demo", ai_transcribed=True, duration=DURATION_S)


def main(argv: list[str]) -> int:
    bus = EventBus()
    clock = DemoClock()
    ctx = UiContext(
        bus=bus, get_clock=lambda: clock, controller=DemoController(clock, bus),
        settings=Settings(), shutdown=lambda: None,
    )
    app, engine = create_ui(ctx, safe_mode="--safe" in argv)
    bus.publish(TRACK_CHANGED, {"video_id": "demo", "track_ref": TrackRef(video_id="demo", title="เพลงทดสอบ")})
    bus.publish(TRACK_META_READY, {
        "video_id": "demo", "meta": TrackMeta(title="เพลงทดสอบ (ข้อมูลปลอม)", artist="ศิลปินสมมติ", duration=DURATION_S),
        "cover_path": None, "palette": [],
    })
    bus.publish(PLAYBACK_STATE, {"playing": True, "video_id": "demo"})
    bus.publish(LYRICS_READY, {
        "video_id": "demo", "lyrics": fake_lyrics(),
        "source_label": "จาก DEMO · ทีละคำ", "candidates_count": 1,
    })
    result: Any = app.exec()
    engine.refs.adapter.close()
    return int(result)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
