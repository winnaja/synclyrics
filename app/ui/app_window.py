"""สร้าง QGuiApplication + QQmlApplicationEngine และผูก object ฝั่ง Python เข้ากับ QML

- ตั้ง QSG_RHI_BACKEND (d3d11 บน Windows) เฉพาะตอน run_ui จริง (test แบบ offscreen ไม่แตะ)
- ลงทะเบียน context property: player (PlayerBridge), lyricsModel, clockBridge, look, safeMode
- create_ui() สร้างทุกอย่างแต่ไม่วน event loop (ให้ test ใช้) ส่วน run_ui() เรียก create_ui แล้ว exec
- safe_mode=True: ไม่ใช้เอฟเฟกต์ (เงา/มาสก์ของปก) ใช้ QML แบบเรียบ (ต้องใช้ได้แน่นอน ข้อ 11.2)
- กฎ: ห้าม import PySide6 ตอน import module นี้ (test_smoke_imports) — import ในฟังก์ชันเท่านั้น

ข้อตกลงกับ controller (duck-typed): play_url(text), toggle_pause(), seek(seconds),
adjust_offset(delta_s), next_lyrics_candidate(), set_volume(v)
UI เป็นคนเลื่อนเวลาเนื้อเพลงเองตาม lyricsOffset (เวลาเนื้อเพลง = เวลาเสียง - offset)
ดังนั้น controller แค่จำ offset ต่อเพลงได้ ไม่ต้องเลื่อนข้อมูลเนื้อเพลงซ้ำ
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.clock import Clock
from app.core.config import Settings
from app.core.events import (
    ERROR,
    LYRICS_OFFSET,
    LYRICS_READY,
    LYRICS_TIMING_UPDATED,
    PLAYBACK_STATE,
    TRACK_CHANGED,
    TRACK_META_READY,
    EventBus,
)
from app.core.log import get_logger
from app.ui.bus_adapter import create_bus_adapter
from app.ui.lyrics_model import make_lyrics_model_class

# หัวข้อเหตุการณ์เฉพาะของ UI: {text} ข้อความสถานะ เช่น "กำลังโหลดเสียง..."
PLAYER_STATUS = "player.status"

QML_DIR = Path(__file__).parent / "qml"

_log = get_logger("ui")


@dataclass
class UiContext:
    """สิ่งที่ UI ต้องการจากส่วนอื่นของโปรแกรม"""

    bus: EventBus
    # คืนนาฬิกาของ deck ที่กำลังเล่น — UI เรียกทุกเฟรม (object อาจเปลี่ยนระหว่างเพลง)
    get_clock: Callable[[], Clock]
    controller: Any  # ดูข้อตกลงด้านบน
    settings: Settings
    shutdown: Callable[[], None]
    # เรียกใน UI thread หลังหน้าต่างพร้อม: on_started(raise_window) — main ใช้เปิด bridge/กู้สถานะ/ดึงหน้าต่างขึ้นหน้า
    on_started: Callable[[Callable[[], None]], None] | None = None


def css_color_to_qml(value: str) -> str:
    """แปลงสี CSS แบบ #RRGGBBAA (ใน config) เป็น #AARRGGBB ที่ QML ใช้ — สีอื่นคืนตามเดิม"""
    if isinstance(value, str) and value.startswith("#") and len(value) == 9:
        return "#" + value[7:9] + value[1:7]
    return value


def resolve_font(preferred: str, fallbacks: list[str], available: Any) -> str:
    """เลือกฟอนต์ตัวแรกที่มีในเครื่อง (ไม่สนตัวพิมพ์เล็กใหญ่) ไม่มีเลยคืนตัวที่ผู้ใช้เลือก (Qt หาแทนเอง)"""
    have = {f.casefold(): f for f in available}
    for name in [preferred, *fallbacks]:
        if name.casefold() in have:
            return have[name.casefold()]
    return preferred


def build_look(settings: Settings, available_fonts: Any = None) -> dict[str, Any]:
    """ค่า lyrics_look สำหรับ QML (สีแปลงเป็นรูปแบบ QML แล้ว ฟอนต์ผ่านการเลือก fallback แล้วถ้าส่งรายการฟอนต์มา)"""
    look = settings.lyrics_look.model_dump()
    if available_fonts is not None:
        look["font_family"] = resolve_font(look["font_family"], look.get("font_fallbacks", []), available_fonts)
    for key in ("color_sung", "color_active", "color_unsung", "glow_color"):
        look[key] = css_color_to_qml(look[key])
    return look


def _file_url(path: Any) -> str:
    """path ในเครื่อง -> file:// url (ว่าง/ผิด -> "")"""
    if not path:
        return ""
    try:
        return Path(str(path)).resolve().as_uri()
    except (OSError, ValueError):
        return ""


_BRIDGES: tuple[type, type] | None = None


def make_bridge_classes() -> tuple[type, type]:
    """สร้างคลาส PlayerBridge และ ClockBridge ครั้งเดียวแล้วจำไว้ (import PySide6 แบบ lazy)"""
    global _BRIDGES
    if _BRIDGES is not None:
        return _BRIDGES

    from PySide6.QtCore import Property, QObject, Signal, Slot
    from PySide6.QtGui import QGuiApplication

    class PlayerBridge(QObject):
        """สถานะเพลง + คำสั่งจาก QML -> controller / เหตุการณ์จาก bus -> property ของ QML"""

        titleChanged = Signal()
        artistChanged = Signal()
        coverUrlChanged = Signal()
        playingChanged = Signal()
        durationSChanged = Signal()
        sourceLabelChanged = Signal()
        aiTranscribedChanged = Signal()
        statusTextChanged = Signal()
        lyricsOffsetChanged = Signal()

        def __init__(self, controller: Any, model: Any, parent: Any = None) -> None:
            super().__init__(parent)
            self._controller = controller
            self._model = model
            self._video_id = ""
            self._title = ""
            self._artist = ""
            self._cover_url = ""
            self._playing = False
            self._duration_s = 0.0
            self._source_label = ""
            self._ai = False
            self._status = ""
            self._offset = 0.0

        # ---------- property ที่ QML อ่าน ----------
        title = Property(str, lambda s: s._title, notify=titleChanged)
        artist = Property(str, lambda s: s._artist, notify=artistChanged)
        coverUrl = Property(str, lambda s: s._cover_url, notify=coverUrlChanged)
        playing = Property(bool, lambda s: s._playing, notify=playingChanged)
        durationS = Property(float, lambda s: s._duration_s, notify=durationSChanged)
        sourceLabel = Property(str, lambda s: s._source_label, notify=sourceLabelChanged)
        aiTranscribed = Property(bool, lambda s: s._ai, notify=aiTranscribedChanged)
        statusText = Property(str, lambda s: s._status, notify=statusTextChanged)
        lyricsOffset = Property(float, lambda s: s._offset, notify=lyricsOffsetChanged)

        def _set(self, attr: str, value: Any) -> None:
            """ตั้งค่า _attr แล้ว emit ...Changed เฉพาะเมื่อเปลี่ยนจริง"""
            private = "_" + attr
            if getattr(self, private) == value:
                return
            setattr(self, private, value)
            getattr(self, _SIGNALS[attr]).emit()

        # ---------- คำสั่งจาก QML ----------
        def _call(self, name: str, *args: Any) -> None:
            """เรียก controller แบบไม่ให้ UI พังถ้า controller พัง"""
            try:
                getattr(self._controller, name)(*args)
            except Exception:
                _log.exception("controller.%s พัง", name)
                self._set("status", "สั่งงานไม่สำเร็จ ลองใหม่อีกครั้ง")

        @Slot(str)
        def playUrl(self, text: str) -> None:
            text = (text or "").strip()
            if text:
                self._set("status", "กำลังเปิดลิงก์...")
                self._call("play_url", text)

        @Slot()
        def pasteAndPlay(self) -> None:
            """Ctrl+V ที่ไหนก็ได้: อ่านคลิปบอร์ดแล้วเล่น"""
            clip = QGuiApplication.clipboard()
            if clip is not None:
                self.playUrl(clip.text())

        @Slot()
        def togglePause(self) -> None:
            self._call("toggle_pause")

        @Slot(float)
        def seek(self, seconds: float) -> None:
            self._call("seek", max(0.0, float(seconds)))

        @Slot(float)
        def adjustOffset(self, delta_s: float) -> None:
            self._set("offset", round(self._offset + float(delta_s), 3))
            self._call("adjust_offset", float(delta_s))

        @Slot()
        def nextCandidate(self) -> None:
            self._call("next_lyrics_candidate")

        @Slot(float)
        def setVolume(self, v: float) -> None:
            self._call("set_volume", max(0.0, min(1.0, float(v))))

        # ---------- เหตุการณ์จาก bus (รันใน UI thread ผ่าน queued connection) ----------
        @Slot(str, object)
        def on_event(self, topic: str, payload: Any) -> None:
            try:
                self._dispatch(topic, payload if isinstance(payload, dict) else {})
            except Exception:
                _log.exception("จัดการเหตุการณ์ %s ใน UI พัง", topic)

        def _is_stale(self, payload: dict[str, Any]) -> bool:
            """เหตุการณ์ของเพลงอื่น (เช่นเพลงก่อนหน้าที่ตอบช้า) ให้ทิ้ง"""
            vid = payload.get("video_id")
            return bool(vid and self._video_id and vid != self._video_id)

        def _dispatch(self, topic: str, p: dict[str, Any]) -> None:
            if topic == TRACK_CHANGED:
                ref = p.get("track_ref")
                self._video_id = str(p.get("video_id") or getattr(ref, "video_id", "") or "")
                self._model.clear()
                self._set("title", str(getattr(ref, "title", "") or ""))
                self._set("artist", str(getattr(ref, "channel", "") or ""))
                self._set("cover_url", "")
                self._set("source_label", "")
                self._set("ai", False)
                self._set("offset", 0.0)
                self._set("duration_s", float(getattr(ref, "duration", None) or 0.0))
                self._set("status", "กำลังเตรียมเพลง...")
            elif topic == TRACK_META_READY:
                if self._is_stale(p):
                    return
                meta = p.get("meta")
                if meta is not None:
                    self._set("title", str(getattr(meta, "title", "") or self._title))
                    self._set("artist", str(getattr(meta, "artist", "") or self._artist))
                    dur = getattr(meta, "duration", None)
                    if dur:
                        self._set("duration_s", float(dur))
                self._set("cover_url", _file_url(p.get("cover_path")))
            elif topic == PLAYBACK_STATE:
                self._set("playing", bool(p.get("playing")))
            elif topic == LYRICS_READY:
                if self._is_stale(p):
                    return
                lyrics = p.get("lyrics")
                if lyrics is None:  # ไม่พบเนื้อเพลงเลย
                    self._model.clear()
                    self._set("source_label", "")
                    self._set("status", "ไม่พบเนื้อเพลงสำหรับเพลงนี้")
                    return
                self._model.set_lyrics(lyrics)
                self._set("source_label", str(p.get("source_label") or ""))
                self._set("ai", bool(getattr(lyrics, "ai_transcribed", False)))
                if not self._duration_s and getattr(lyrics, "duration", None):
                    self._set("duration_s", float(lyrics.duration))
                self._set("status", "" if lyrics.lines else "ไม่พบเนื้อเพลงสำหรับเพลงนี้")
            elif topic == LYRICS_TIMING_UPDATED:
                if self._is_stale(p):
                    return
                self._model.update_words(
                    float(p.get("start", 0.0)), float(p.get("end", 0.0)), list(p.get("words") or [])
                )
            elif topic == ERROR:
                msg = p.get("user_message") or p.get("message") or ""
                if msg:
                    self._set("status", str(msg))
            elif topic == LYRICS_OFFSET:
                if not self._is_stale(p):
                    self._set("offset", float(p.get("offset") or 0.0))
            elif topic == PLAYER_STATUS:
                self._set("status", str(p.get("text") or ""))

    # ชื่อ attr -> ชื่อ signal (ใช้ใน _set)
    _SIGNALS = {
        "title": "titleChanged",
        "artist": "artistChanged",
        "cover_url": "coverUrlChanged",
        "playing": "playingChanged",
        "duration_s": "durationSChanged",
        "source_label": "sourceLabelChanged",
        "ai": "aiTranscribedChanged",
        "status": "statusTextChanged",
        "offset": "lyricsOffsetChanged",
    }

    class ClockBridge(QObject):
        """ให้ QML อ่านเวลาจาก Clock ทุกเฟรม (เรียก Python ครั้งเดียวต่อเฟรม)"""

        def __init__(self, get_clock: Callable[[], Clock], model: Any, parent: Any = None) -> None:
            super().__init__(parent)
            self._get_clock = get_clock
            self._model = model

        @Slot(result=float)
        def position(self) -> float:
            try:
                return float(self._get_clock().position())
            except Exception:
                return 0.0

        @Slot(result=bool)
        def isPlaying(self) -> bool:
            try:
                return bool(self._get_clock().playing)
            except Exception:
                return False

        @Slot(result=int)
        def generation(self) -> int:
            try:
                return int(self._get_clock().generation)
            except Exception:
                return 0

        @Slot(float, result=int)
        def lineIndexAt(self, position: float) -> int:
            """index ของบรรทัดปัจจุบัน (bisect) -1 = ยังไม่ถึงบรรทัดแรก"""
            return int(self._model.line_index_at(position))

    _BRIDGES = (PlayerBridge, ClockBridge)
    return _BRIDGES


def create_ui(context: UiContext, safe_mode: bool = False) -> tuple[Any, Any]:
    """สร้างแอป + engine และโหลด Main.qml โดยยังไม่วน event loop คืน (app, engine)

    engine.refs เก็บ player / model / clock / adapter ไว้ (กัน garbage collect และให้ test เข้าถึง)
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv[:1])
        app.setApplicationName("SyncLyrics")

    player_cls, clock_cls = make_bridge_classes()
    model = make_lyrics_model_class()()
    player = player_cls(context.controller, model)
    clock = clock_cls(context.get_clock, model)
    adapter = create_bus_adapter(context.bus)
    adapter.connect_slot(player.on_event)

    engine = QQmlApplicationEngine()
    root = engine.rootContext()
    root.setContextProperty("player", player)
    root.setContextProperty("lyricsModel", model)
    root.setContextProperty("clockBridge", clock)
    from PySide6.QtGui import QFont, QFontDatabase

    look = build_look(context.settings, QFontDatabase.families())
    if look["font_family"] != context.settings.lyrics_look.font_family:
        _log.warning("ไม่พบฟอนต์ที่ตั้งไว้ ใช้ตัวสำรองแทน", extra={"data": {
            "wanted": context.settings.lyrics_look.font_family, "using": look["font_family"]}})
    app.setFont(QFont(look["font_family"]))  # ข้อความทั้งโปรแกรมใช้ฟอนต์เดียวกัน (ไทย+อังกฤษ)
    root.setContextProperty("look", look)
    root.setContextProperty("safeMode", bool(safe_mode))
    engine.refs = SimpleNamespace(player=player, model=model, clock=clock, adapter=adapter)

    problems: list[str] = []
    engine.warnings.connect(lambda ws: problems.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        raise RuntimeError("โหลด Main.qml ไม่สำเร็จ: " + " | ".join(problems))
    return app, engine


def run_ui(context: UiContext, safe_mode: bool = False) -> int:
    """เปิด UI และวน event loop คืน exit code"""
    if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")
    app, engine = create_ui(context, safe_mode)
    done = {"v": False}

    def _on_quit() -> None:
        if done["v"]:
            return
        done["v"] = True
        engine.refs.adapter.close()
        try:
            context.shutdown()
        except Exception:
            _log.exception("shutdown พัง")

    app.aboutToQuit.connect(_on_quit)

    def raise_window() -> None:
        """นำหน้าต่างหลักขึ้นมาด้านหน้า (เปิดโปรแกรมซ้ำ / ส่วนขยายสั่ง focus)"""
        for obj in engine.rootObjects():
            try:
                obj.showNormal() if obj.visibility() == 3 else obj.show()  # 3 = Minimized
                obj.raise_()
                obj.requestActivate()
            except Exception:
                _log.exception("ดึงหน้าต่างขึ้นหน้าไม่สำเร็จ")

    if context.on_started is not None:
        from PySide6.QtCore import QTimer

        def _started() -> None:
            try:
                context.on_started(raise_window)  # type: ignore[misc]
            except Exception:
                _log.exception("on_started พัง")

        QTimer.singleShot(0, _started)
    return int(app.exec())
