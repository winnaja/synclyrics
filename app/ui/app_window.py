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
    BRIDGE_STATUS,
    ERROR,
    HEALTH_REPORT,
    LYRICS_LOADING,
    LYRICS_OFFSET,
    LYRICS_READY,
    LYRICS_RETIMED,
    LYRICS_TIMING_UPDATED,
    MODE_CHANGED,
    PLAYBACK_STATE,
    QUEUE_CHANGED,
    TRACK_CHANGED,
    TRACK_META_READY,
    EMPHASIS_READY,
    TRANSLATION_READY,
    VOLUME_CHANGED,
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
    on_started: Callable[..., None] | None = None  # on_started(raise_window, show_settings)
    # คำสั่งพิเศษที่ UI เรียกได้ เช่น {"install_extension": () -> str(ข้อความบอกผู้ใช้)}
    actions: dict[str, Callable[..., Any]] | None = None
    # เฟส 2 (UX UI): บันทึกตั้งค่า / โฟลเดอร์ข้อมูล / ออกจากโปรแกรม / เปิดคีย์ลัดทั้งระบบ (ปิดใน test)
    save_settings: Callable[[], None] | None = None
    data_dir: str = ""
    quit_app: Callable[[], None] | None = None
    global_hotkeys: bool = False


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
_DEFAULT_PALETTE = ["#2a2f3d", "#343947", "#232733", "#2e3340"]
_LANG_NAMES = {"th": "ไทย", "en": "อังกฤษ", "zh": "จีน", "ja": "ญี่ปุ่น", "ko": "เกาหลี"}


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
        bridgeConnectedChanged = Signal()
        modeChanged = Signal()
        queueChanged = Signal()
        healthTextChanged = Signal()
        translationChanged = Signal()
        lyricsLoadingChanged = Signal()
        timingApproxChanged = Signal()
        everConnectedChanged = Signal()
        unsupportedChanged = Signal()
        paletteChanged = Signal()
        edgeGapsChanged = Signal()
        volumeChanged = Signal()

        def __init__(self, controller: Any, model: Any, parent: Any = None, actions: Any = None) -> None:
            super().__init__(parent)
            self._actions = actions or {}
            self._bridge_connected = False
            self._mode = "app"
            self._queue_text = ""
            self._health = ""
            self._lyrics_loading = False
            self._timing_approx = False
            self._ever_connected = False
            self._unsupported = ""
            self._palette = list(_DEFAULT_PALETTE)
            self._edge_gaps: list[float] = [0.0, 0.0, 0.0, 0.0]   # [อินโทรเริ่ม, จบ, เอาท์โทรเริ่ม, จบ] จาก AI (0 = ไม่มี)
            self._volume = 1.0
            self._muted = False
            self._has_translation = False
            self._show_translation = False
            self._translation_lang = ""
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
        bridgeConnected = Property(bool, lambda s: s._bridge_connected, notify=bridgeConnectedChanged)
        mode = Property(str, lambda s: s._mode, notify=modeChanged)
        queueText = Property(str, lambda s: s._queue_text, notify=queueChanged)
        healthText = Property(str, lambda s: s._health, notify=healthTextChanged)
        lyricsLoading = Property(bool, lambda s: s._lyrics_loading, notify=lyricsLoadingChanged)
        # เวลาทีละคำเป็นการประมาณ (ข้อมูลเวลาแค่ระดับบรรทัด) — UX UI ข้อ 4.4: ต้องไม่อ้างว่าแม่นยำ
        timingApprox = Property(bool, lambda s: s._timing_approx, notify=timingApproxChanged)
        everConnected = Property(bool, lambda s: s._ever_connected, notify=everConnectedChanged)
        unsupportedReason = Property(str, lambda s: s._unsupported, notify=unsupportedChanged)
        # สีเด่น 4 สีของปกเพลงปัจจุบัน ("#RRGGBB") ใช้กับพื้นหลัง fluid ของหน้าต่างโหมดเต็ม
        palette = Property("QVariantList", lambda s: s._palette, notify=paletteChanged)
        # ช่วงดนตรีก่อนบรรทัดแรก/หลังบรรทัดสุดท้ายที่ AI ฟังแล้วไม่มีเสียงร้อง [introStart, introEnd, outroStart, outroEnd] (วินาที เวลาเนื้อเพลง)
        edgeGaps = Property("QVariantList", lambda s: s._edge_gaps, notify=edgeGapsChanged)
        # วอลลุ่มของตัวเล่นใน YouTube (0-1) และสถานะปิดเสียง — สั่งผ่านส่วนขยาย
        volume = Property(float, lambda s: s._volume, notify=volumeChanged)
        muted = Property(bool, lambda s: s._muted, notify=volumeChanged)
        hasTranslation = Property(bool, lambda s: s._has_translation, notify=translationChanged)
        showTranslation = Property(bool, lambda s: s._show_translation, notify=translationChanged)
        translationLang = Property(str, lambda s: s._translation_lang, notify=translationChanged)

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

        @Slot(str)
        def searchLyrics(self, query: str) -> None:
            """ค้นเนื้อเพลงเอง (UX UI ข้อ 7.5): พิมพ์ "ศิลปิน - ชื่อเพลง" แล้วค้นใหม่ทุกแหล่ง"""
            if (query or "").strip():
                self._call("search_lyrics", query.strip())

        @Slot()
        def reconnectYouTube(self) -> None:
            """ปุ่ม "เชื่อมต่อใหม่": สั่งส่วนขยายรีโหลดตัวเองแล้วต่อ host ใหม่"""
            fn = self._actions.get("reconnect_youtube")
            if fn is not None:
                try:
                    fn()
                except Exception:
                    _log.exception("เชื่อมต่อ YouTube ใหม่ไม่สำเร็จ")

        @Slot()
        def resetOffset(self) -> None:
            self._set("offset", 0.0)
            self._call("reset_offset")

        @Slot()
        def refreshLyrics(self) -> None:
            self._call("refresh_lyrics")

        @Slot()
        def toggleTranslation(self) -> None:
            self._show_translation = not self._show_translation
            self.translationChanged.emit()

        @Slot()
        def toggleMute(self) -> None:
            self._call("toggle_mute")

        @Slot()
        def skipNext(self) -> None:
            self._call("skip_next")

        @Slot()
        def skipPrev(self) -> None:
            self._call("skip_prev")

        @Slot(str)
        def setMode(self, mode: str) -> None:
            self._call("set_mode", mode)

        @Slot()
        def installExtension(self) -> None:
            """ปุ่ม "ติดตั้งส่วนขยาย": คัดลอกไฟล์ ลงทะเบียน host ใส่ path ใน clipboard เปิด chrome://extensions"""
            fn = self._actions.get("install_extension")
            if fn is None:
                return
            try:
                self._set("status", str(fn()))
            except Exception:
                _log.exception("ติดตั้งส่วนขยายพัง")
                self._set("status", "ติดตั้งส่วนขยายไม่สำเร็จ (ดู log)")

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

        def _set_timing_approx(self, on: bool) -> None:
            if self._timing_approx != on:
                self._timing_approx = on
                self.timingApproxChanged.emit()

        def _set_unsupported(self, reason: str) -> None:
            if self._unsupported != reason:
                self._unsupported = reason
                self.unsupportedChanged.emit()

        def _set_edge_gaps(self, intro: Any, outro: Any) -> None:
            vals = [float(intro[0]), float(intro[1])] if intro else [0.0, 0.0]
            vals += [float(outro[0]), float(outro[1])] if outro else [0.0, 0.0]
            if vals != self._edge_gaps:
                self._edge_gaps = vals
                self.edgeGapsChanged.emit()

        def _set_palette(self, colors: Any) -> None:
            cols = [str(c) for c in list(colors)[:4]]
            while len(cols) < 4:
                cols.append(cols[-1] if cols else _DEFAULT_PALETTE[0])
            if cols != self._palette:
                self._palette = cols
                self.paletteChanged.emit()

        def _set_lyrics_loading(self, on: bool) -> None:
            if self._lyrics_loading != on:
                self._lyrics_loading = on
                self.lyricsLoadingChanged.emit()

        def _set_translation(self, lyrics: Any) -> None:
            """มีคำแปลไหม + เป็นภาษาอะไร: แสดงเองเฉพาะคำแปลภาษาไทย (ผู้ใช้อ่านภาษาอื่นไม่ออก) ภาษาอื่นมีปุ่มเปิดเอง"""
            from app.lyrics.thai import detect_language

            texts = [ln.translation for ln in (getattr(lyrics, "lines", None) or []) if getattr(ln, "translation", None)]
            lang = detect_language(" ".join(texts[:40])) if texts else None
            self._has_translation = bool(texts)
            self._translation_lang = _LANG_NAMES.get(lang or "", "")
            # คำแปลไม่แสดงเอง (ผู้ใช้สั่ง 2026-10-20): ต้องกดปุ่มแปลก่อน · ค่าที่กดไว้คงอยู่ข้ามเพลงในรอบการใช้งานนี้
            self.translationChanged.emit()

        def _is_stale(self, payload: dict[str, Any]) -> bool:
            """เหตุการณ์ของเพลงอื่น (เช่นเพลงก่อนหน้าที่ตอบช้า) ให้ทิ้ง"""
            vid = payload.get("video_id")
            return bool(vid and self._video_id and vid != self._video_id)

        def _dispatch(self, topic: str, p: dict[str, Any]) -> None:
            if topic == TRACK_CHANGED:
                ref = p.get("track_ref")
                self._video_id = str(p.get("video_id") or getattr(ref, "video_id", "") or "")
                self._model.clear()
                self._set_edge_gaps(None, None)
                self._set("title", str(getattr(ref, "title", "") or ""))
                self._set("artist", str(getattr(ref, "channel", "") or ""))
                self._set("cover_url", "")
                self._set("source_label", "")
                self._set("ai", False)
                self._set("offset", 0.0)
                self._set_translation(None)
                self._set_lyrics_loading(True)
                self._set_timing_approx(False)
                self._set_unsupported("")
                self._set_palette(_DEFAULT_PALETTE)
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
                if p.get("palette"):
                    self._set_palette(p["palette"])
            elif topic == PLAYBACK_STATE:
                self._set("playing", bool(p.get("playing")))
            elif topic == LYRICS_LOADING:
                if not self._is_stale(p):
                    self._set_lyrics_loading(True)
            elif topic == LYRICS_READY:
                if self._is_stale(p):
                    return
                if p.get("final", True):
                    self._set_lyrics_loading(False)
                lyrics = p.get("lyrics")
                self._set_unsupported(str(p.get("unsupported") or ""))
                if lyrics is not None:
                    from app.core.models import TimingLevel

                    self._set_timing_approx(getattr(lyrics, "timing", None) != TimingLevel.WORD)
                if lyrics is None:  # ไม่พบเนื้อเพลงเลย
                    self._model.clear()
                    self._set("source_label", "")
                    self._set("status", "ไม่พบเนื้อเพลงสำหรับเพลงนี้")
                    return
                self._model.set_lyrics(lyrics)
                self._set_translation(lyrics)
                self._set("source_label", str(p.get("source_label") or ""))
                self._set("ai", bool(getattr(lyrics, "ai_transcribed", False)))
                if not self._duration_s and getattr(lyrics, "duration", None):
                    self._set("duration_s", float(lyrics.duration))
                self._set("status", "" if lyrics.lines else "ไม่พบเนื้อเพลงสำหรับเพลงนี้")
            elif topic == LYRICS_RETIMED:
                # AI ฟังเสียงแล้วจัดเวลาใหม่ (ทยอยทีละช่วง/ผลสุดท้าย): แก้เวลาแทนที่ ไม่รีเซ็ตเนื้อเพลงที่กำลังแสดง
                if self._is_stale(p):
                    return
                lyrics = p.get("lyrics")
                if lyrics is None or not lyrics.lines:
                    return
                from app.core.models import TimingLevel

                from app.ui.lyrics_model import edge_gaps

                # gaps ที่ AI ส่งมา: [] = ฟังแล้ว "ไม่มีช่วงดนตรีเลย" (เช่นแร็พ/ดูเอ็ตร้องต่อเนื่อง) ต้องไม่ใช้ช่องว่างจากเวลาเนื้อเพลงมาแสดงจุดทับตอนมีคนร้องอยู่
                # ไม่มีคีย์ gaps = ผลชั่วคราวระหว่างฟัง (ยังไม่รู้) ก็ไม่แสดงจุดเช่นกัน
                gaps = [(float(a), float(b)) for a, b in (p.get("gaps") or [])]
                self._model.retime(lyrics, gaps)
                intro, outro = edge_gaps(lyrics, gaps, float(getattr(lyrics, "duration", 0.0) or 0.0))
                self._set_edge_gaps(intro, outro)
                self._set_timing_approx(getattr(lyrics, "timing", None) != TimingLevel.WORD)
                self._set("source_label", str(p.get("source_label") or ""))
                self._set("ai", bool(getattr(lyrics, "ai_transcribed", False)))
                if p.get("final", True):
                    self._set_lyrics_loading(False)
            elif topic == TRANSLATION_READY:
                if self._is_stale(p):
                    return
                tr = [str(x or "") for x in (p.get("translations") or [])]
                if self._model.set_translations(tr) and any(tr):
                    self._has_translation = True
                    self._translation_lang = _LANG_NAMES.get(str(p.get("lang") or "th"), "")
                    self.translationChanged.emit()
            elif topic == EMPHASIS_READY:
                if self._is_stale(p):
                    return
                self._model.apply_emphasis({str(k): str(v) for k, v in (p.get("emphasis") or {}).items()})
            elif topic == LYRICS_TIMING_UPDATED:
                if self._is_stale(p):
                    return
                self._model.update_words(
                    float(p.get("start", 0.0)), float(p.get("end", 0.0)), list(p.get("words") or [])
                )
            elif topic == ERROR:
                self._set_lyrics_loading(False)
                msg = p.get("user_message") or p.get("message") or ""
                if msg:
                    self._set("status", str(msg))
            elif topic == LYRICS_OFFSET:
                if not self._is_stale(p):
                    self._set("offset", float(p.get("offset") or 0.0))
            elif topic == PLAYER_STATUS:
                self._set("status", str(p.get("text") or ""))
            elif topic == VOLUME_CHANGED:
                self._volume = float(p.get("volume", 1.0))
                self._muted = bool(p.get("muted", False))
                self.volumeChanged.emit()
            elif topic == BRIDGE_STATUS:
                self._set("bridge_connected", bool(p.get("connected")))
                if p.get("connected") and not self._ever_connected:
                    self._ever_connected = True
                    self.everConnectedChanged.emit()
            elif topic == MODE_CHANGED:
                self._set("mode", str(p.get("mode") or "app"))
            elif topic == QUEUE_CHANGED:
                items = p.get("items") or []
                idx = int(p.get("index", -1))
                self._set("queue_text", f"คิว {idx + 1}/{len(items)}" if len(items) > 1 else "")
            elif topic == HEALTH_REPORT:
                self._set("health", str(p.get("text") or ""))

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
        "bridge_connected": "bridgeConnectedChanged",
        "mode": "modeChanged",
        "queue_text": "queueChanged",
        "health": "healthTextChanged",
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

        @Slot(int, float, result="QVariantList")
        def groupRange(self, i: int, gapS: float) -> list:
            """[บรรทัดแรก, บรรทัดสุดท้าย] ของท่อนที่ร้องต่อเนื่องกับบรรทัด i"""
            lo, hi = self._model.group_range(int(i), float(gapS))
            return [lo, hi]

        @Slot(float, result=int)
        def lineIndexAt(self, position: float) -> int:
            """index ของบรรทัดปัจจุบัน (bisect) -1 = ยังไม่ถึงบรรทัดแรก"""
            return int(self._model.line_index_at(position))

        @Slot(float, float, result=int)
        def lineIndexAtLead(self, position: float, lead: float) -> int:
            """เหมือน lineIndexAt แต่ขึ้นบรรทัดถัดไปล่วงหน้า lead วินาทีเมื่อบรรทัดก่อนหน้าจบแล้ว"""
            return int(self._model.line_index_at(position, lead))

    _BRIDGES = (PlayerBridge, ClockBridge)
    return _BRIDGES


def _wire_side_effects(engine: Any, context: UiContext, store: Any, bridge: Any, player: Any) -> None:
    """ผูกการตั้งค่ากับของที่อยู่นอก QML: เปิดพร้อม Windows, คีย์ลัดทั้งระบบ (+ การกระทำของคีย์ลัด)"""
    from app.ui import startup
    from app.ui.settings_bridge import HOTKEY_NAMES

    def rebind() -> None:  # แทนที่ด้านล่างเมื่อเปิดคีย์ลัดทั้งระบบ
        return None

    def on_setting(key: str, value: Any) -> None:
        if key == "st_launch_with_windows":
            if not startup.set_launch_with_windows(bool(value)):
                _log.warning("ตั้งค่าเปิดพร้อม Windows ไม่สำเร็จ")
        elif key.startswith("hk_") and key != "hk_status":
            rebind()

    bridge.add_side_effect(on_setting)
    if not context.global_hotkeys:
        return

    from PySide6.QtCore import QObject, Signal

    from app.ui.hotkeys import HotkeyManager

    class _Signals(QObject):
        fired = Signal(str)

    sig = _Signals()

    def act(name: str) -> None:
        g = bridge.get
        if name == "show_hide":
            bridge.set_from_python("ov_visible", not g("ov_visible"))
        elif name == "click_through":
            bridge.set_from_python("ov_click_through", not g("ov_click_through"))
        elif name == "lock":
            bridge.set_from_python("ov_locked", not g("ov_locked"))
        elif name == "full_toggle":
            bridge.set_from_python("fw_open", not g("fw_open"))  # เปิด/ปิดหน้าต่างโหมดเต็ม
        elif name == "translation":
            player.toggleTranslation()
        elif name == "font_up":
            bridge.set_from_python("ov_font_size", min(120, g("ov_font_size") + 2))
        elif name == "font_down":
            bridge.set_from_python("ov_font_size", max(12, g("ov_font_size") - 2))
        elif name == "offset_later":
            player.adjustOffset(0.1)
        elif name == "offset_earlier":
            player.adjustOffset(-0.1)
        elif name == "offset_reset":
            player.resetOffset()

    sig.fired.connect(act)  # emit จากเธรดคีย์ลัด -> ทำงานใน UI thread
    manager = HotkeyManager(lambda name: sig.fired.emit(name))

    def rebind() -> None:
        bindings = {n: str(store.get(f"hk_{n}")) for n in HOTKEY_NAMES}
        errors = manager.set_bindings(bindings)
        bridge.set_status("hk_status", " · ".join(errors.values()))

    engine.refs.hotkeys = manager
    engine.refs.hotkey_signals = sig
    rebind()


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
    player = player_cls(context.controller, model, actions=context.actions)
    clock = clock_cls(context.get_clock, model)
    adapter = create_bus_adapter(context.bus)
    adapter.connect_slot(player.on_event)

    from app.ui.settings_bridge import make_settings_bridge_class
    from app.ui.settings_store import SettingsStore

    store = SettingsStore(context.settings)
    settings_bridge = make_settings_bridge_class()(store, save=context.save_settings, data_dir=context.data_dir,
                                                   on_quit=context.quit_app)

    engine = QQmlApplicationEngine()
    root = engine.rootContext()
    root.setContextProperty("player", player)
    root.setContextProperty("lyricsModel", model)
    root.setContextProperty("clockBridge", clock)
    root.setContextProperty("cfg", settings_bridge.cfg)
    root.setContextProperty("settingsBridge", settings_bridge)
    from PySide6.QtGui import QFont, QFontDatabase

    # ฟอนต์หลัก (SF Thonburi) ไม่มีในเครื่อง = แสดงด้วยตัวสำรองแต่ไม่แก้ค่าที่ผู้ใช้ตั้งไว้ในไฟล์
    wanted = context.settings.lyrics_look.font_family
    resolved = resolve_font(wanted, context.settings.lyrics_look.font_fallbacks, QFontDatabase.families())
    if resolved != wanted:
        _log.warning("ไม่พบฟอนต์ที่ตั้งไว้ ใช้ตัวสำรองแทน", extra={"data": {"wanted": wanted, "using": resolved}})
        settings_bridge.cfg.insert("look_font_family", resolved)
    app.setFont(QFont(resolved))  # ข้อความทั้งโปรแกรมใช้ฟอนต์เดียวกัน (ไทย+อังกฤษ)
    root.setContextProperty("safeMode", bool(safe_mode))
    engine.refs = SimpleNamespace(player=player, model=model, clock=clock, adapter=adapter,
                                  settings_bridge=settings_bridge, store=store, hotkeys=None)

    _wire_side_effects(engine, context, store, settings_bridge, player)

    def _overlay_window() -> Any:
        roots = engine.rootObjects()
        return roots[0].property("overlay") if roots else None

    settings_bridge.set_window_provider(_overlay_window)

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
            engine.refs.settings_bridge.flush()  # บันทึกการตั้งค่าที่ยังรอ debounce
            if engine.refs.hotkeys is not None:
                engine.refs.hotkeys.stop()
        except Exception:
            _log.exception("ปิดตัวจัดการตั้งค่า/คีย์ลัดไม่สำเร็จ")
        try:
            context.shutdown()
        except Exception:
            _log.exception("shutdown พัง")

    app.aboutToQuit.connect(_on_quit)

    def raise_window() -> None:
        """นำหน้าต่างหลักขึ้นมาด้านหน้า (เปิดโปรแกรมซ้ำ / ส่วนขยายสั่ง focus)"""
        from PySide6.QtCore import QMetaObject

        for obj in engine.rootObjects():
            try:
                QMetaObject.invokeMethod(obj, "showOverlay")
            except Exception:
                _log.exception("ดึงหน้าต่างเนื้อเพลงขึ้นหน้าไม่สำเร็จ")

    def show_settings() -> None:
        from PySide6.QtCore import QMetaObject

        for obj in engine.rootObjects():
            try:
                QMetaObject.invokeMethod(obj, "showSettings")
            except Exception:
                _log.exception("เปิดหน้าตั้งค่าไม่สำเร็จ")

    if context.on_started is not None:
        from PySide6.QtCore import QTimer

        def _started() -> None:
            try:
                context.on_started(raise_window, show_settings)  # type: ignore[misc]
            except Exception:
                _log.exception("on_started พัง")

        QTimer.singleShot(0, _started)
    return int(app.exec())
