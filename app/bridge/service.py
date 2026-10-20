"""BridgeService — ตัวประมวลผลข้อความจากส่วนขยาย Chrome (ข้อ 10) แยกจาก Qt เพื่อ test ได้

รับ "bridge.message" จาก EventBus (BridgeServer เป็นคนส่งเข้ามา) แล้วสั่ง PlayerController:
  hello            -> hello_ack + selectors + status
  play_now         -> เล่นในแอป (ถ้า held=True ส่วนขยายหยุดแท็บไว้แล้ว รอสถานะ ready/failed ของเรา)
  enqueue(_playlist)/up_next -> คิว
  companion_track/state -> โหมดคู่หู
  command          -> play_pause / next / prev / seek / volume / mute / set_mode / focus ...
และส่ง status กลับให้ส่วนขยายทุกครั้งที่สถานะเปลี่ยน (phase: loading -> ready / failed)

ความปลอดภัย: ทุกอย่างที่มาจากส่วนขยายถือเป็นข้อมูลไม่น่าเชื่อ — ตรวจรูปแบบ videoId และตัดความยาวก่อนใช้
ข้อความผิดรูปแบบ log แล้วทิ้ง ห้ามทำให้โปรแกรมพัง
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core import events as ev
from app.core.log import get_logger
from app.core.messages import PROTOCOL_VERSION
from app.core.models import TrackRef

log = get_logger("bridge")

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_TEXT = 300
MAX_TRACKS_PER_MESSAGE = 300
APP_VERSION = "0.2.0"


def _text(v: Any, limit: int = MAX_TEXT) -> str:
    return v.strip()[:limit] if isinstance(v, str) else ""


def parse_track(d: Any, added_from: str = "extension") -> TrackRef | None:
    """แปลง dict จากส่วนขยายเป็น TrackRef; videoId ไม่ถูกรูปแบบ = None"""
    if not isinstance(d, dict):
        return None
    vid = d.get("video_id")
    if not isinstance(vid, str) or not VIDEO_ID_RE.match(vid):
        return None
    ms = d.get("music_section")
    music: dict[str, str] = {}
    if isinstance(ms, dict):
        for k in ("song", "artist", "album"):
            if _text(ms.get(k)):
                music[k] = _text(ms.get(k))
    dur = d.get("duration")
    return TrackRef(
        video_id=vid, title=_text(d.get("title")), channel=_text(d.get("channel")),
        duration=float(dur) if isinstance(dur, (int, float)) and 0 < dur < 24 * 3600 else None,
        music_section=music, added_from=added_from,
        thumbnail_url=_text(d.get("thumbnail_url"), 500) or None,
    )


def parse_tracks(items: Any, added_from: str) -> list[TrackRef]:
    out: list[TrackRef] = []
    if isinstance(items, list):
        for it in items[:MAX_TRACKS_PER_MESSAGE]:
            t = parse_track(it, added_from)
            if t is not None:
                out.append(t)
    return out


class BridgeService:
    """เชื่อมส่วนขยาย <-> PlayerController

    send(type, payload) = ฟังก์ชันส่งข้อความถึงส่วนขยาย (thread ใดเรียกก็ได้ — BridgeServer จัดการเอง)
    raise_window() = ดึงหน้าต่างขึ้นหน้า (ตั้งทีหลังได้เพราะ UI สร้างทีหลัง)
    """

    def __init__(self, bus: Any, controller: Any, send: Callable[[str, dict[str, Any]], None],
                 selectors_loader: Callable[[], dict[str, Any]] | None = None,
                 raise_window: Callable[[], None] | None = None, settings: Any = None,
                 show_settings: Callable[[], None] | None = None) -> None:
        self.bus = bus
        self.controller = controller
        self._send = send
        self._load_selectors = selectors_loader or (lambda: {})
        self.raise_window = raise_window
        self.show_settings = show_settings
        self.settings = settings
        self._clients: set[int] = set()
        self._phase = "idle"
        self._phase_vid: str | None = None
        controller.tab_control = self._tab_control
        bus.subscribe(ev.BRIDGE_MESSAGE, self.on_message)
        for topic in (ev.TRACK_CHANGED, ev.TRACK_META_READY, ev.PLAYBACK_STATE, ev.ERROR, ev.QUEUE_CHANGED, ev.MODE_CHANGED, ev.VOLUME_CHANGED):
            bus.subscribe(topic, self._on_app_event)

    # ---------- ส่งสถานะให้ส่วนขยาย ----------
    def status_payload(self) -> dict[str, Any]:
        c = self.controller
        track = c.track
        return {
            "phase": self._phase, "playing": bool(c.playing), "video_id": track.video_id if track else None,
            "title": track.title if track else "", "mode": c.mode, "queue_len": len(c.queue),
            "pending_video_id": self._phase_vid, "volume": float(getattr(c, "volume", 1.0)), "muted": bool(getattr(c, "muted", False)),
        }

    def push_status(self) -> None:
        if self._clients:
            self._send("status", self.status_payload())

    def _on_app_event(self, topic: str, p: dict[str, Any]) -> None:
        """เหตุการณ์ภายในแอป -> phase ของส่วนขยาย (ห้ามบล็อก/พัง)"""
        try:
            if topic == ev.TRACK_CHANGED and p.get("deck", 0) >= 0:
                self._phase, self._phase_vid = "loading", p.get("video_id")
            elif topic == ev.PLAYBACK_STATE and p.get("video_id") == self._phase_vid and self._phase == "loading":
                self._phase = "ready"
            elif topic == ev.ERROR and self._phase == "loading":
                self._phase = "failed"
            elif topic == ev.MODE_CHANGED and p.get("mode") == "companion":
                self._phase, self._phase_vid = "idle", None
            self.push_status()
        except Exception:
            log.exception("ส่งสถานะให้ส่วนขยายไม่สำเร็จ")

    def _tab_control(self, action: str, data: dict[str, Any]) -> None:
        self._send("tab_control", {"action": action, **data})

    # ---------- รับข้อความ ----------
    def on_message(self, topic: str, p: dict[str, Any]) -> None:
        """handler ของ bridge.message (รันใน UI thread — ต้องสั้น งานหนักอยู่ใน controller/IoThread)"""
        t = p.get("type")
        payload = p.get("payload") or {}
        client = p.get("client")
        try:
            handler = getattr(self, f"_h_{t}", None)
            if handler is None:
                log.warning("bridge: ไม่รู้จักข้อความ", extra={"data": {"type": str(t)[:40]}})
                return
            handler(payload, client)
        except Exception:
            log.exception("bridge: จัดการข้อความพัง", extra={"data": {"type": str(t)[:40]}})

    def _h__disconnected(self, payload: dict[str, Any], client: Any) -> None:
        if client in self._clients:
            self._clients.discard(client)
            if not self._clients:
                self.bus.publish(ev.BRIDGE_STATUS, {"connected": False, "ext_version": ""})

    def _h_hello(self, payload: dict[str, Any], client: Any) -> None:
        self._clients.add(client)
        self.bus.publish(ev.BRIDGE_STATUS, {"connected": True, "ext_version": _text(payload.get("ext_version"), 32)})
        auto = True
        try:
            auto = bool(self.settings.startup.extension_sends_current_video)
        except AttributeError:
            pass
        self._send("hello_ack", {"app_version": APP_VERSION, "protocol": PROTOCOL_VERSION,
                                 "mode": self.controller.mode, "auto_send": auto})
        self.push_status()

    def _h_ping(self, payload: dict[str, Any], client: Any) -> None:
        self._send("pong", {})

    def _h_log(self, payload: dict[str, Any], client: Any) -> None:
        level = _text(payload.get("level"), 8).lower()
        fn = log.error if level == "error" else log.warning if level == "warn" else log.info
        data = payload.get("data")
        fn("ext: " + _text(payload.get("msg"), 200),
           extra={"data": data if isinstance(data, (dict, list, str, int, float)) else {}})

    def _app_audio(self) -> bool:
        """โหมดแอปเล่นเสียงเองเปิดอยู่ไหม (ไม่มี settings = ถือว่าเปิด เพื่อ test ของโค้ดโหมดแอปเดิม)"""
        try:
            return bool(self.settings.playback.app_audio)
        except AttributeError:
            return self.settings is None

    def _h_play_now(self, payload: dict[str, Any], client: Any) -> None:
        if not self._app_audio():
            # ส่วนขยายรุ่นเก่า/ผู้ใช้สั่งเล่นเลย: แอปไม่เล่นเสียง — ไม่ทำอะไร ไม่ส่ง phase=loading (ส่วนขยายจะไม่หยุดวิดีโอค้าง)
            log.info("bridge: ข้าม play_now (แอปแสดงเนื้อเพลงอย่างเดียว)")
            return
        track = parse_track(payload.get("track"))
        if track is None:
            self._send("error", {"code": "bad_track", "message": "ข้อมูลเพลงจากส่วนขยายไม่ถูกต้อง"})
            return
        start = payload.get("start_at")
        start_at = float(start) if isinstance(start, (int, float)) and 0 <= start < 24 * 3600 else 0.0
        # ส่งสถานะ loading ทันที (ก่อนงานจริงเริ่ม) ส่วนขยายจะได้รู้ว่าแอปรับเรื่องแล้ว
        self._phase, self._phase_vid = "loading", track.video_id
        self.push_status()
        self.controller.play_now(track, start_at)
        if self.raise_window is not None:
            self.raise_window()

    def _h_enqueue(self, payload: dict[str, Any], client: Any) -> None:
        if not self._app_audio():
            return
        tracks = parse_tracks(payload.get("tracks"), "extension")
        pos = "next" if payload.get("position") == "next" else "end"
        n = self.controller.enqueue(tracks, pos)
        self._send("toast", {"text": f"เข้าคิวแล้ว {n} เพลง" if n else "เพลงนี้อยู่ในคิวแล้ว"})

    def _h_enqueue_playlist(self, payload: dict[str, Any], client: Any) -> None:
        if not self._app_audio():
            return
        tracks = parse_tracks(payload.get("tracks"), "playlist")
        n = self.controller.enqueue(tracks, "end")
        self._send("toast", {"text": f"ส่ง playlist แล้ว {n} เพลง"})

    def _h_up_next(self, payload: dict[str, Any], client: Any) -> None:
        """Up next ของหน้าที่เปิดอยู่: จำไว้เป็นเพลงที่จะเล่นต่อ (เฟส 5 ใช้ preload) ไม่ใส่คิวเอง"""
        self.up_next = parse_tracks(payload.get("tracks"), "up_next")

    up_next: list[TrackRef] = []

    def _h_companion_track(self, payload: dict[str, Any], client: Any) -> None:
        track = parse_track(payload.get("track"), "companion")
        if track is not None:
            self.controller.companion_track(track)

    def _h_companion_state(self, payload: dict[str, Any], client: Any) -> None:
        self.controller.companion_state(payload)

    def _h_command(self, payload: dict[str, Any], client: Any) -> None:
        name = payload.get("name")
        c = self.controller
        if name == "play_pause":
            c.toggle_pause()
        elif name == "next":
            c.skip_next()
        elif name == "prev":
            c.skip_prev()
        elif name == "seek":
            t = payload.get("time")
            if isinstance(t, (int, float)) and 0 <= t < 24 * 3600:
                c.seek(float(t))
        elif name == "volume":
            v = payload.get("value")
            if isinstance(v, (int, float)) and 0 <= v <= 1:
                c.set_volume(float(v))
        elif name == "mute":
            c.toggle_mute()
        elif name == "set_mode":
            mode = payload.get("mode")
            if mode in ("app", "companion"):
                c.set_mode(mode)
        elif name == "focus":
            for a in payload.get("argv", []) if isinstance(payload.get("argv"), list) else []:
                if isinstance(a, str) and not a.startswith("-"):
                    c.play_url(a)
            if self.raise_window is not None:
                self.raise_window()
        elif name == "open_settings":
            if self.show_settings is not None:
                self.show_settings()
        elif name == "automix_toggle":
            self._send("toast", {"text": "ฟีเจอร์นี้ยังไม่เปิดใช้ในเวอร์ชันนี้"})
        else:
            log.warning("bridge: command ไม่รู้จัก", extra={"data": {"name": str(name)[:40]}})


def load_selectors(user_dir: Path, default_dir: Path) -> dict[str, Any]:
    """selectors.json: ไฟล์ของผู้ใช้ (ถ้ามี) มาก่อนค่าเริ่มต้นของโปรเจกต์ — พังอ่านไม่ได้ = ใช้ค่าเริ่มต้น"""
    for base in (user_dir, default_dir):
        f = base / "selectors.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            continue
    return {}
