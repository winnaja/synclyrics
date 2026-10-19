"""Smoke test ของ UI: โหลด Main.qml แบบ offscreen ต้องไม่มี warning/error ของ QML
และเหตุการณ์จาก bus (รวมจาก thread อื่น) ต้องมาถึง PlayerBridge / LyricsModel ใน UI thread

ฉากทดสอบรันใน subprocess แยก (ไฟล์นี้รันตรงๆ ได้) เพื่อไม่ให้ PySide6 ถูกโหลดเข้า process ของ pytest
— ไม่งั้น test_smoke_imports.test_no_heavy_imports จะพังเมื่อลำดับการรัน test เปลี่ยน
exit code 0 = ผ่าน, 77 = ข้าม (ไม่มี PySide6 / สร้างหน้าต่างไม่ได้), อื่นๆ = พัง
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.events import (
    ERROR,
    LYRICS_READY,
    PLAYBACK_STATE,
    TRACK_CHANGED,
    TRACK_META_READY,
    EventBus,
)
from app.core.models import Line, Lyrics, TimingLevel, TrackMeta, TrackRef, Word
from app.ui.app_window import PLAYER_STATUS, UiContext, build_look, css_color_to_qml

pytestmark = pytest.mark.qt

ROOT = Path(__file__).resolve().parent.parent
SKIP_CODE = 77


class FakeClock:
    """นาฬิกาปลอม: ทุกครั้งที่อ่านเวลาเดินหน้า 0.05 วิ"""

    def __init__(self) -> None:
        self._t = 0.0
        self.generation = 0
        self.playing = True

    def position(self, at: float | None = None) -> float:
        self._t += 0.05
        return self._t


class FakeController:
    """controller ปลอม: บันทึกทุกคำสั่งที่ UI เรียก"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        def rec(*args: Any) -> None:
            self.calls.append((name, args))

        return rec


def _lyrics() -> Lyrics:
    lines = [
        Line(start=float(i * 2), end=float(i * 2 + 1.5), words=[Word(f"บรรทัด{i}", i * 2.0, i * 2 + 1.5)])
        for i in range(6)
    ]
    return Lyrics(lines=lines, timing=TimingLevel.LINE, source="test", ai_transcribed=True)


def _bad(messages: list[str]) -> list[str]:
    # ข้อความของ QML (ระบุไฟล์ .qml) — ไม่นับคำเตือนของระบบฟอนต์ใน offscreen
    keys = (".qml", "ReferenceError", "TypeError", "is not defined", "Binding loop")
    return [m for m in messages
            if m.startswith(("QtWarningMsg", "QtCriticalMsg", "QtFatalMsg")) and any(k in m for k in keys)]


def _scenario() -> int:
    """ฉากทดสอบจริง (รันใน subprocess) คืน exit code"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtCore import QCoreApplication, qInstallMessageHandler
    except Exception:
        return SKIP_CODE

    from app.ui.app_window import create_ui

    messages: list[str] = []
    qInstallMessageHandler(lambda mode, ctx, msg: messages.append(f"{mode.name}: {msg} @ {ctx.file}:{ctx.line}"))

    bus = EventBus()
    controller = FakeController()
    clock = FakeClock()
    context = UiContext(
        bus=bus, get_clock=lambda: clock, controller=controller,
        settings=Settings(), shutdown=lambda: None,
    )
    try:
        app, engine = create_ui(context)
    except Exception as e:
        if "Main.qml" in str(e):
            raise  # QML พังจริง ไม่ใช่ข้าม
        print("skip:", e)
        return SKIP_CODE

    def pump(seconds: float = 0.3) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)

    refs = engine.refs
    p = refs.player
    pump(0.3)
    assert _bad(messages) == [], _bad(messages)

    bus.publish(TRACK_CHANGED, {"video_id": "abc", "track_ref": TrackRef(video_id="abc", title="ชื่อชั่วคราว")})
    bus.publish(PLAYER_STATUS, {"text": "กำลังโหลดเสียง..."})
    pump()
    assert p.property("title") == "ชื่อชั่วคราว"
    assert p.property("statusText") == "กำลังโหลดเสียง..."

    meta = TrackMeta(title="เพลงทดสอบ", artist="ศิลปินสมมติ", duration=120.0)
    bus.publish(TRACK_META_READY, {"video_id": "abc", "meta": meta, "cover_path": None, "palette": []})
    bus.publish(PLAYBACK_STATE, {"playing": True, "video_id": "abc"})
    bus.publish(LYRICS_READY, {
        "video_id": "abc", "lyrics": _lyrics(),
        "source_label": "จาก LRCLIB · ทีละบรรทัด", "candidates_count": 2,
    })
    pump(0.5)

    assert p.property("title") == "เพลงทดสอบ"
    assert p.property("artist") == "ศิลปินสมมติ"
    assert p.property("durationS") == 120.0
    assert p.property("playing") is True
    assert p.property("sourceLabel") == "จาก LRCLIB · ทีละบรรทัด"
    assert p.property("aiTranscribed") is True
    assert p.property("statusText") == ""
    assert refs.model.rowCount() == 6
    assert refs.clock.lineIndexAt(2.5) == 1

    # เหตุการณ์ของเพลงอื่นต้องถูกทิ้ง
    bus.publish(LYRICS_READY, {"video_id": "other", "lyrics": Lyrics([], TimingLevel.NONE, "x")})
    pump(0.1)
    assert refs.model.rowCount() == 6

    # ส่งจาก thread อื่น ต้องมาถึงใน UI thread
    t = threading.Thread(target=lambda: bus.publish(ERROR, {"user_message": "ข้อผิดพลาดสมมติ"}))
    t.start()
    t.join()
    pump(0.2)
    assert p.property("statusText") == "ข้อผิดพลาดสมมติ"

    # คำสั่งจาก UI -> controller
    p.playUrl("https://example.com/watch?v=abc")
    p.seek(12.5)
    p.togglePause()
    p.adjustOffset(0.1)
    p.nextCandidate()
    p.setVolume(2.0)  # clamp เป็น 1.0
    names = [c[0] for c in controller.calls]
    assert names == ["play_url", "seek", "toggle_pause", "adjust_offset", "next_lyrics_candidate", "set_volume"]
    assert controller.calls[1][1] == (12.5,)
    assert controller.calls[5][1] == (1.0,)
    assert abs(p.property("lyricsOffset") - 0.1) < 1e-9

    # เปลี่ยนเพลง -> เนื้อเพลงถูกล้าง
    bus.publish(TRACK_CHANGED, {"video_id": "def", "track_ref": TrackRef(video_id="def")})
    pump(0.2)
    assert refs.model.rowCount() == 0
    assert _bad(messages) == [], _bad(messages)

    for obj in engine.rootObjects():
        obj.close()
    pump(0.05)
    refs.adapter.close()
    return 0


def test_css_color_conversion() -> None:
    assert css_color_to_qml("#FFFFFF66") == "#66FFFFFF"  # RRGGBBAA -> AARRGGBB
    assert css_color_to_qml("#FFFFFF") == "#FFFFFF"
    assert build_look(Settings())["color_unsung"] == "#66FFFFFF"


def test_qml_loads_and_events_flow() -> None:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if r.returncode == SKIP_CODE:
        pytest.skip("ไม่มี PySide6 หรือสร้างหน้าต่าง offscreen ไม่ได้")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]


if __name__ == "__main__":
    sys.exit(_scenario())
