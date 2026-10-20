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

    # AI จัดเวลาใหม่จากเสียง (เลื่อนทั้งเพลง 10 วิ) + คำแปลไทย: แก้ model แทนที่ ไม่รีเซ็ต
    from app.core.events import LYRICS_RETIMED, TRANSLATION_READY

    shifted = _lyrics()
    for ln in shifted.lines:
        ln.start += 10.0
        ln.end += 10.0
        for w in ln.words:
            w.start += 10.0
            w.end += 10.0
    shifted.duration = 60.0
    bus.publish(LYRICS_RETIMED, {"video_id": "abc", "lyrics": shifted, "source_label": "จาก LRCLIB · จัดเวลาจากเสียงแล้ว",
                                 "final": True, "gaps": [[0.0, 10.0], [21.5, 40.0]]})
    pump(0.2)
    assert list(p.property("edgeGaps")) == [0.0, 10.0, 21.5, 40.0]
    role = {bytes(v).decode(): k for k, v in refs.model.roleNames().items()}
    assert refs.model.data(refs.model.index(0, 0), role["start"]) == 10.0 and refs.model.rowCount() == 6
    assert p.property("sourceLabel").endswith("จัดเวลาจากเสียงแล้ว")
    bus.publish(TRANSLATION_READY, {"video_id": "abc", "translations": [f"แปล{i}" for i in range(6)], "lang": "th"})
    pump(0.2)
    assert refs.model.data(refs.model.index(2, 0), role["translation"]) == "แปล2"
    bus.publish(LYRICS_RETIMED, {"video_id": "other", "lyrics": _lyrics(), "source_label": "x", "final": True})   # เพลงอื่นถูกทิ้ง
    pump(0.1)
    assert refs.model.data(refs.model.index(0, 0), role["start"]) == 10.0

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

    # ---------- หน้าต่างเนื้อเพลงลอย + โหมดเต็ม + ตั้งค่า (UX UI) ----------
    root = engine.rootObjects()[0]
    overlay, settings_win, full_win = root.property("overlay"), root.property("settingsWin"), root.property("fullWin")
    sb = refs.settings_bridge
    assert overlay.property("objectName") == "overlay" and overlay.property("mode") == "focus"
    assert overlay.property("width") == sb.store.settings.overlay.w_focus
    # ตั้งค่าจากฝั่ง Python/QML: ผ่านการตรวจ -> เข้า cfg และหน้าต่างตามทันที (ไม่ต้องเปิดใหม่)
    sb.set_from_python("ov_mode", "minimal")
    pump(0.2)
    assert sb.cfg.value("ov_mode") == "minimal" and overlay.property("mode") == "minimal"
    assert overlay.property("height") == sb.store.settings.overlay.h_minimal
    sb.set_from_python("ov_mode", "focus")
    pump(0.1)
    # จำนวนบรรทัดของโหมดโฟกัส -> ความสูงหน้าต่างเปลี่ยนตาม (เคยมีตัวตั้งค่าแต่ไม่ต่อสาย)
    h3 = overlay.property("height")
    sb.set_from_python("ov_visible_lines", 6)
    pump(0.2)
    assert overlay.property("height") > h3
    sb.set_from_python("ov_visible_lines", 3)
    # เลือกธีม -> สีเปลี่ยนตาม · ค่าผิดถูกปฏิเสธและ cfg คงค่าเดิม
    sb.set_from_python("ov_theme", "light")
    assert sb.cfg.value("ov_text_color") == "#1C1C1E"
    sb.set_from_python("ov_font_size", 9999)
    assert sb.cfg.value("ov_font_size") == 34
    sb.set_from_python("ov_theme", "soft_dark")
    # ซ่อน/แสดงด้วย cfg · หน้าตั้งค่าเปิดได้
    sb.set_from_python("ov_visible", False)
    pump(0.1)
    assert overlay.property("visible") is False
    sb.set_from_python("ov_visible", True)
    from PySide6.QtCore import QMetaObject
    QMetaObject.invokeMethod(root, "showSettings")
    pump(0.3)
    assert settings_win.property("visible") is True
    p.resetOffset()
    p.refreshLyrics()
    p.searchLyrics("NewJeans - OMG")
    p.reconnectYouTube()
    assert [c[0] for c in controller.calls[-3:]] == ["reset_offset", "refresh_lyrics", "search_lyrics"]
    assert controller.calls[-1][1] == ("NewJeans - OMG",)

    # ---------- หน้าต่างโหมดเต็ม (แบบ Apple Music) ----------
    assert full_win.property("objectName") == "fullWindow"
    assert full_win.property("visible") is True   # โหมดเต็มเป็นหน้าแรกตอนเปิดโปรแกรม (cfg.fw_start_full)
    sb.set_from_python("fw_open", False)
    pump(0.3)
    assert full_win.property("visible") is False
    palette = list(p.property("palette"))
    assert len(palette) == 4 and all(c.startswith("#") for c in palette)
    bus.publish(TRACK_META_READY, {"video_id": "def", "meta": None, "cover_path": None,  # เพลงปัจจุบันของฉากนี้
                                   "palette": ["#112233", "#445566", "#778899", "#AABBCC"]})
    pump(0.1)
    assert list(p.property("palette")) == ["#112233", "#445566", "#778899", "#AABBCC"]
    sb.set_from_python("fw_open", True)
    pump(0.4)
    assert full_win.property("visible") is True and overlay.property("visible") is False  # เปิดโหมดเต็ม = ซ่อนหน้าต่างลอย
    sb.set_from_python("fw_fullscreen", True)
    pump(0.4)
    assert full_win.property("fs") is True
    sb.set_from_python("fw_fullscreen", False)
    pump(0.4)
    assert full_win.property("fs") is False
    for bg in ("solid", "fluid"):
        sb.set_from_python("fw_background", bg)
        pump(0.1)
    sb.set_from_python("fw_font_scale", 1.5)
    pump(0.1)
    full_win.close()  # ปุ่มปิดของหน้าต่าง = ซ่อน (ไม่ปิดโปรแกรม) และหน้าต่างลอยกลับมา
    pump(0.3)
    assert sb.cfg.value("fw_open") is False and full_win.property("visible") is False
    assert overlay.property("visible") is True
    sb.set_from_python("fw_open", False)

    # ---------- ปรับแต่งแอนิเมชัน: ชุดสำเร็จรูป + ค่าละเอียดทุกตัวไม่ทำให้ QML มีคำเตือน ----------
    sb.set_from_python("ov_anim_preset", "bouncy")
    assert sb.cfg.value("ov_wave_ms") == 60 and sb.cfg.value("look_spring_stiffness") == 260.0
    sb.set_from_python("ov_blur", 0.6)
    assert sb.cfg.value("ov_anim_preset") == "custom"
    for preset in ("smooth", "balanced", "bouncy", "snappy", "none"):
        sb.set_from_python("ov_anim_preset", preset)
        pump(0.08)
    for k, v in (("ov_anim_speed", 2.5), ("ov_wave_ms", 120), ("ov_blur", 1.0), ("ov_falloff", 0.28), ("ov_idle_scale", 0.65),
                 ("ov_lift_px", 7), ("ov_weight_boost", 200), ("ov_window_opacity", 0.8)):
        sb.set_from_python(k, v)
        pump(0.05)
    # โหมดทุกแบบ/ทุกธีมไม่ทำให้ QML มีคำเตือน
    for mode in ("minimal", "focus"):
        for theme in ("pure_black", "frosted", "minimal_transparent", "light", "soft_dark"):
            sb.set_from_python("ov_mode", mode)
            sb.set_from_python("ov_theme", theme)
            pump(0.05)
    for wa in ("none", "word", "char"):
        for ease in ("smooth", "gentle", "spring", "linear"):
            sb.set_from_python("ov_word_anim", wa)
            sb.set_from_python("ov_word_ease", ease)
            pump(0.03)
    for k, v in (("ov_emph_min_s", 0.4), ("ov_emph_glow", 1.0), ("fw_edge_fade", 0.3), ("fw_edge_fade", 0.0), ("fw_edge_fade", 0.14)):
        sb.set_from_python(k, v)
        pump(0.05)
    sb.set_from_python("fw_lyrics_visible", False)   # โหมดดูแต่ปก
    sb.set_from_python("fw_open", True)
    pump(0.4)
    sb.set_from_python("fw_lyrics_visible", True)
    sb.set_from_python("fw_idle_hide_s", 1.0)
    pump(0.2)
    sb.set_from_python("fw_open", False)
    for hl in ("fill", "word", "glow", "line"):
        for anim in ("fade_move", "fade", "move", "scale"):
            sb.set_from_python("ov_highlight", hl)
            sb.set_from_python("ov_animation", anim)
            pump(0.03)
    sb.set_from_python("ov_reduced_motion", True)
    pump(0.1)

    # ---------- ปุ่ม ↺ รายตัว + ชุดการตั้งค่าที่ตั้งชื่อไว้ ----------
    sb.resetAll()
    pump(0.1)
    assert sb.isDefault("ov_anim_speed", sb.cfg.value("ov_anim_speed")) is True
    sb.set_from_python("ov_anim_speed", 2.0)
    pump(0.1)
    assert sb.isDefault("ov_anim_speed", sb.cfg.value("ov_anim_speed")) is False
    from PySide6.QtCore import QObject
    settings_win.setProperty("page", 6)       # หมวดแอนิเมชัน + โหมดละเอียด (ความเร็วเป็นตัวเลือกขั้นสูง)
    settings_win.setProperty("advanced", True)
    pump(0.3)
    all_buttons = settings_win.findChildren(QObject, "resetKeyButton")
    buttons = [b for b in all_buttons if b.property("visible")]
    assert buttons, f"ปุ่ม ↺ ต้องโผล่ข้างตัวเลือกที่ปรับแล้ว (พบปุ่มทั้งหมด {len(all_buttons)})"
    assert len(buttons) <= 3, "หลังรีเซ็ตทั้งหมดมีแค่ตัวที่ปรับไว้ที่ควรมีปุ่ม"
    sb.resetKey("ov_anim_speed")
    pump(0.1)
    assert sb.cfg.value("ov_anim_speed") == 1.0
    assert sb.savePreset("   ") != ""                     # ชื่อว่างไม่ได้
    sb.set_from_python("ov_font_size", 55)
    sb.set_from_python("fw_font_scale", 1.4)
    assert sb.savePreset("ชุดทดสอบ") == ""
    assert list(sb.property("presetNames")) == ["ชุดทดสอบ"]
    sb.resetAll()
    assert sb.cfg.value("ov_font_size") != 55
    assert sb.loadPreset("ชุดทดสอบ") is True
    pump(0.1)
    assert sb.cfg.value("ov_font_size") == 55 and sb.cfg.value("fw_font_scale") == 1.4
    assert sb.loadPreset("ไม่มีชุดนี้") is False
    sb.deletePreset("ชุดทดสอบ")
    assert list(sb.property("presetNames")) == []
    pump(0.1)
    assert _bad(messages) == [], _bad(messages)

    # ปิดโปรแกรมต้องไม่ถูกหน้าตั้งค่าขวาง (เคยค้าง: หน้าต่างที่ซ่อนลงถาดปฏิเสธการปิด)
    assert sb.property("quitting") is False
    sb.quit()
    assert sb.property("quitting") is True
    for w in (settings_win, overlay, full_win):
        w.close()
    pump(0.1)
    assert settings_win.property("visible") is False
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
