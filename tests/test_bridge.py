"""ทดสอบ bridge ฝั่งโปรแกรม: host (ส่งต่อ), registry, คิว, BridgeService + controller (ไม่ต้องมี Chrome/Qt)"""

from __future__ import annotations

import io
import json
import os
import struct
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.bridge import host as hostmod
from app.bridge import registry
from app.bridge.service import BridgeService, parse_track, parse_tracks
from app.core import events as ev
from app.core.events import EventBus
from app.core.models import TrackRef
from app.player.queue import PlayQueue


def frame(d: dict[str, Any]) -> bytes:
    b = json.dumps(d).encode()
    return struct.pack("<I", len(b)) + b


def T(vid: str, **kw: Any) -> TrackRef:
    return TrackRef(video_id=vid.ljust(11, "x")[:11], **kw)


# ---------------------------------------------------------------------------
# queue
# ---------------------------------------------------------------------------
def test_queue_play_now_inserts_after_current_and_jumps_if_exists() -> None:
    q = PlayQueue()
    a, b, c = T("a"), T("b"), T("c")
    q.play_now(a)
    q.add([b, c])
    assert [t.video_id[0] for t in q.items()] == ["a", "b", "c"]
    q.play_now(T("z"))  # แทรกถัดจากเพลงปัจจุบัน
    assert [t.video_id[0] for t in q.items()] == ["a", "z", "b", "c"] and q.index == 1
    q.play_now(T("c"))  # อยู่ในคิวแล้ว = กระโดดไปเลย ไม่เพิ่มซ้ำ
    assert len(q) == 4 and q.current().video_id[0] == "c"


def test_queue_add_skips_duplicates_ahead_and_current() -> None:
    q = PlayQueue()
    q.play_now(T("a"))
    assert q.add([T("a"), T("b"), T("b"), T("c")]) == 2
    assert q.add([T("b")]) == 0
    assert q.add([T("n")], "next") == 1
    assert [t.video_id[0] for t in q.items()] == ["a", "n", "b", "c"]


def test_queue_next_prev_remove_move() -> None:
    q = PlayQueue()
    q.play_now(T("a"))
    q.add([T("b"), T("c")])
    assert q.next().video_id[0] == "b" and q.prev().video_id[0] == "a" and q.prev() is None
    q.next()
    q.move(0, 2)  # a ไปท้าย ตำแหน่งปัจจุบันต้องยังเป็น b
    assert q.current().video_id[0] == "b"
    q.remove(0)  # ลบ b ที่อยู่ก่อนหน้า... (หลัง move: b,c,a -> ลบ b = ปัจจุบัน)
    assert q.current() is not None


def test_queue_snapshot_restore_survives_garbage() -> None:
    q = PlayQueue()
    q.play_now(T("a", title="เพลง"))
    q.add([T("b")])
    snap = q.snapshot()
    snap["items"].append({"video_id": 123, "bogus": 1})
    q2 = PlayQueue()
    q2.restore(snap)
    assert len(q2) >= 2 and q2.current().title == "เพลง"
    q3 = PlayQueue()
    q3.restore({"items": "ไม่ใช่ list", "index": "x"})
    assert len(q3) == 0


# ---------------------------------------------------------------------------
# parse_track (ข้อมูลจากส่วนขยายไม่น่าเชื่อ)
# ---------------------------------------------------------------------------
def test_parse_track_validates_and_truncates() -> None:
    assert parse_track({"video_id": "../../etc/passwd"}) is None
    assert parse_track({"video_id": "abc"}) is None
    assert parse_track("x") is None
    t = parse_track({"video_id": "dQw4w9WgXcQ", "title": "ก" * 1000, "duration": -5,
                     "music_section": {"song": "S", "artist": "A", "evil": "x"}})
    assert t is not None and len(t.title) == 300 and t.duration is None
    assert t.music_section == {"song": "S", "artist": "A"} and t.added_from == "extension"
    assert len(parse_tracks([{"video_id": "dQw4w9WgXcQ"}] * 1000, "up_next")) == 300


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
def test_extension_id_matches_manifest_key() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = root / "extension" / "manifest.json"
    assert manifest.exists()
    ext_id = registry.extension_id_from_manifest(manifest)
    assert len(ext_id) == 32 and set(ext_id) <= set("abcdefghijklmnop")
    # id ที่บันทึกไว้ใน README/คำแนะนำต้องตรงกับ key (กัน key เปลี่ยนโดยไม่ตั้งใจ)
    assert ext_id == "jjafolpgjdghgjadopngdolglpllbhod"


def test_host_manifest_has_only_our_origin(tmp_path: Path) -> None:
    mp = registry.write_host_manifest(tmp_path / "m.json", Path("C:/x/host.bat"), "a" * 32)
    d = json.loads(mp.read_text(encoding="utf-8"))
    assert d["name"] == "com.synclyrics.host" and d["type"] == "stdio"
    assert d["allowed_origins"] == [f"chrome-extension://{'a' * 32}/"]


# ---------------------------------------------------------------------------
# host (HostBridge) — ใช้ os.pipe แทน stdin/stdout/named pipe (PeekNamedPipe ใช้กับ anonymous pipe ได้)
# ---------------------------------------------------------------------------
class Fx:
    """ชุดทดสอบ: Chrome ฝั่งส่ง/รับ + pipe ปลอมของโปรแกรมหลัก"""

    def __init__(self) -> None:
        # Chrome -> host (stdin)
        r, w = os.pipe()
        self.stdin_r, self.chrome_w = os.fdopen(r, "rb", buffering=0), os.fdopen(w, "wb", buffering=0)
        # host -> Chrome (stdout)
        r, w = os.pipe()
        self.chrome_r, self.stdout_w = os.fdopen(r, "rb", buffering=0), os.fdopen(w, "wb", buffering=0)
        # app -> host / host -> app : ใช้ผ่านคลาส PipeEnd ที่รวมอ่าน+เขียน
        r1, w1 = os.pipe()  # app เขียน host อ่าน
        r2, w2 = os.pipe()  # host เขียน app อ่าน
        self.app_w = os.fdopen(w1, "wb", buffering=0)
        self.app_r = os.fdopen(r2, "rb", buffering=0)
        self.host_end = _End(os.fdopen(r1, "rb", buffering=0), os.fdopen(w2, "wb", buffering=0))
        self.pipe_available = threading.Event()
        self.launched = 0

    def open_pipe(self) -> Any:
        return self.host_end if self.pipe_available.is_set() else None

    def launch(self) -> bool:
        self.launched += 1
        return True

    def start(self) -> hostmod.HostBridge:
        hb = hostmod.HostBridge(self.stdin_r, self.stdout_w, self.open_pipe, self.launch, poll_s=0.02)
        threading.Thread(target=hb.run, daemon=True).start()
        return hb

    def read(self, f: Any, timeout: float = 3.0) -> dict[str, Any]:
        """อ่าน 1 ข้อความจาก fd พร้อม timeout"""
        out: list[Any] = []

        def go() -> None:
            head = f.read(4)
            (n,) = struct.unpack("<I", head)
            out.append(json.loads(f.read(n)))

        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(timeout)
        assert out, "ไม่ได้รับข้อความภายในเวลา"
        return out[0]


class _End:
    """ปลายเดียวของ pipe ที่มีทั้ง read/write/fileno (ให้ PeekNamedPipe ถามฝั่งอ่าน)"""

    def __init__(self, r: Any, w: Any) -> None:
        self._r, self._w = r, w

    def fileno(self) -> int:
        return self._r.fileno()

    def read(self, n: int) -> bytes:
        return self._r.read(n)

    def write(self, b: bytes) -> int:
        return self._w.write(b)

    def flush(self) -> None:
        self._w.flush()

    def close(self) -> None:
        self._w.close()  # ปิดฝั่งเขียน = app เห็นว่าหลุด (ไม่ได้ใช้ในเทสต์ส่วนใหญ่)


@pytest.mark.skipif(os.name != "nt", reason="PeekNamedPipe เฉพาะ Windows")
def test_host_waits_without_launching_then_relays_both_ways() -> None:
    fx = Fx()
    fx.start()
    # ยังไม่มี pipe: ส่งข้อความธรรมดา = ได้ error app_not_running และ "ไม่เปิดโปรแกรมเอง"
    fx.chrome_w.write(frame({"type": "ping"}))
    assert fx.read(fx.chrome_r)["payload"]["code"] == "app_not_running"
    assert fx.launched == 0
    # launch_app = host จัดการเอง (ไม่ส่งต่อ)
    fx.chrome_w.write(frame({"type": "launch_app"}))
    deadline = time.time() + 2
    while fx.launched == 0 and time.time() < deadline:
        time.sleep(0.01)
    assert fx.launched == 1
    # โปรแกรมเปิดแล้ว: host แจ้ง host_connected
    fx.pipe_available.set()
    assert fx.read(fx.chrome_r)["type"] == "host_connected"
    # Chrome -> app
    fx.chrome_w.write(frame({"v": 1, "type": "hello", "id": "", "payload": {"ext_version": "1"}}))
    head = fx.app_r.read(4)
    (n,) = struct.unpack("<I", head)
    assert json.loads(fx.app_r.read(n))["type"] == "hello"
    # app -> Chrome (ข้อความยาวเกินก้อนเดียวก็ต้องครบ)
    big = {"v": 1, "type": "status", "id": "", "payload": {"title": "ก" * 5000}}
    fx.app_w.write(frame(big))
    got = fx.read(fx.chrome_r)
    assert got["type"] == "status" and len(got["payload"]["title"]) == 5000


# ---------------------------------------------------------------------------
# BridgeService + controller (controller ปลอม)
# ---------------------------------------------------------------------------
class FakeController:
    def __init__(self) -> None:
        self.mode = "app"
        self.track: TrackRef | None = None
        self.playing = False
        self.queue = PlayQueue()
        self.tab_control = None
        self.calls: list[tuple[str, Any]] = []

    def play_now(self, track: TrackRef, start_at: float = 0.0) -> None:
        self.calls.append(("play_now", (track.video_id, start_at)))
        self.track = track

    def enqueue(self, tracks: list[TrackRef], position: str = "end") -> int:
        self.calls.append(("enqueue", ([t.video_id for t in tracks], position)))
        return len(tracks)

    def companion_track(self, t: TrackRef) -> None:
        self.calls.append(("companion_track", t.video_id))

    def companion_state(self, d: dict[str, Any]) -> None:
        self.calls.append(("companion_state", d["current_time"]))

    def toggle_pause(self) -> None:
        self.calls.append(("pause", None))

    def skip_next(self) -> None:
        self.calls.append(("next", None))

    def skip_prev(self) -> None:
        self.calls.append(("prev", None))

    def set_mode(self, m: str) -> None:
        self.calls.append(("set_mode", m))
        self.mode = m

    def play_url(self, u: str) -> None:
        self.calls.append(("play_url", u))


def make_service() -> tuple[BridgeService, FakeController, list[tuple[str, dict[str, Any]]], EventBus]:
    bus, ctl, sent = EventBus(), FakeController(), []
    svc = BridgeService(bus, ctl, lambda t, p: sent.append((t, p)), lambda: {"version": 1})
    return svc, ctl, sent, bus


def msg(bus: EventBus, type_: str, payload: dict[str, Any] | None = None, client: int = 1) -> None:
    bus.publish(ev.BRIDGE_MESSAGE, {"type": type_, "payload": payload or {}, "id": "", "client": client})


def test_service_hello_then_play_now_flow() -> None:
    svc, ctl, sent, bus = make_service()
    msg(bus, "hello", {"ext_version": "0.2.0"})
    types = [t for t, _ in sent]
    assert types[:2] == ["hello_ack", "status"]
    sent.clear()
    msg(bus, "play_now", {"track": {"video_id": "dQw4w9WgXcQ", "title": "x"}, "start_at": 12.5, "held": True})
    assert ctl.calls[-1] == ("play_now", ("dQw4w9WgXcQ", 12.5))
    assert sent[0][0] == "status" and sent[0][1]["phase"] == "loading"
    # แอปเริ่มเล่นจริง -> ready
    sent.clear()
    bus.publish(ev.TRACK_CHANGED, {"video_id": "dQw4w9WgXcQ", "track_ref": None, "deck": 0})
    bus.publish(ev.PLAYBACK_STATE, {"playing": True, "video_id": "dQw4w9WgXcQ"})
    assert sent[-1][1]["phase"] == "ready"
    # ล้มเหลวระหว่างโหลด -> failed (ส่วนขยายจะปล่อยให้ YouTube เล่นต่อ)
    sent.clear()
    bus.publish(ev.TRACK_CHANGED, {"video_id": "AAAAAAAAAAA", "track_ref": None, "deck": 0})
    bus.publish(ev.ERROR, {"module": "player", "message": "x", "user_message": "x", "recoverable": True})
    assert sent[-1][1]["phase"] == "failed"


def test_service_bad_messages_do_not_crash() -> None:
    svc, ctl, sent, bus = make_service()
    msg(bus, "play_now", {"track": {"video_id": "bad"}})
    assert sent[-1][0] == "error" and not ctl.calls
    msg(bus, "rm_rf", {"x": 1})  # ไม่รู้จัก -> ข้าม
    msg(bus, "companion_state", {"video_id": None})  # controller ปลอมไม่พัง
    msg(bus, "command", {"name": "drop_tables"})


def test_service_commands_and_queue_and_disconnect() -> None:
    svc, ctl, sent, bus = make_service()
    msg(bus, "hello", {})
    for name, expect in (("play_pause", "pause"), ("next", "next"), ("prev", "prev")):
        msg(bus, "command", {"name": name})
        assert ctl.calls[-1][0] == expect
    msg(bus, "command", {"name": "set_mode", "mode": "companion"})
    assert ctl.calls[-1] == ("set_mode", "companion")
    msg(bus, "command", {"name": "set_mode", "mode": "evil"})
    assert ctl.calls[-1] == ("set_mode", "companion")  # ไม่เปลี่ยน
    msg(bus, "enqueue", {"tracks": [{"video_id": "dQw4w9WgXcQ"}, {"video_id": "bad"}], "position": "next"})
    assert ctl.calls[-1] == ("enqueue", (["dQw4w9WgXcQ"], "next"))
    assert sent[-1][0] == "toast"
    statuses: list[dict[str, Any]] = []
    bus.subscribe(ev.BRIDGE_STATUS, lambda t, p: statuses.append(p))
    msg(bus, "_disconnected", {}, client=1)
    assert statuses and statuses[-1]["connected"] is False


def test_service_tab_control_goes_to_extension() -> None:
    svc, ctl, sent, bus = make_service()
    ctl.tab_control("seek", {"time": 30.0})
    assert sent[-1] == ("tab_control", {"action": "seek", "time": 30.0})


def test_service_seek_command_validates_time() -> None:
    svc, ctl, sent, bus = make_service()
    ctl.seek = lambda t: ctl.calls.append(("seek", t))  # type: ignore[attr-defined]
    msg(bus, "command", {"name": "seek", "time": 83.5})
    assert ctl.calls[-1] == ("seek", 83.5)
    for bad in ("x", -5, 10**9, None):
        n = len(ctl.calls)
        msg(bus, "command", {"name": "seek", "time": bad})
        assert len(ctl.calls) == n  # ค่าผิดไม่ถูกส่งต่อ
