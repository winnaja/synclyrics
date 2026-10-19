"""test ของสัญญากลางที่เขียนจริงแล้วในเฟส 0: นาฬิกา, ข้อความ, คิวงาน AI, การแบ่งช่วง, curve, model"""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest

from app.ai.scheduler import Job, JobScheduler, Priority, plan_chunks
from app.audio.automation import CURVES, AutomationLane, Param
from app.bridge.registry import extension_id_from_key
from app.core.clock import MediaClock, RemoteClock
from app.core.events import EventBus
from app.core.messages import EXT_TO_APP, Envelope, FrameDecoder, MessageError, encode_frame
from app.core.models import Line, Lyrics, TimingLevel, Voice, Word, WordTimingSource
from app.media.youtube import parse_video_id
from app.player.state import load_state, save_state


# ---------------- นาฬิกา ----------------
def test_media_clock_extrapolates_and_pauses() -> None:
    c = MediaClock()
    c.publish(media_pos=10.0, host_time=100.0, rate=1.0, playing=True, generation=1)
    assert c.position(at=100.5) == pytest.approx(10.5)
    c.publish(media_pos=10.5, host_time=100.5, rate=1.0, playing=False, generation=1)
    assert c.position(at=200.0) == pytest.approx(10.5)
    assert not c.playing


def test_media_clock_never_jitters_backwards_within_generation() -> None:
    c = MediaClock()
    c.publish(10.0, 100.0, 1.0, True, 1)
    first = c.position(at=100.02)
    # callback ถัดไปมาช้ากว่าที่ extrapolate ไว้นิดหน่อย -> ห้ามถอย
    c.publish(10.01, 100.0, 1.0, True, 1)
    assert c.position(at=100.0) >= first


def test_media_clock_seek_can_go_backwards() -> None:
    c = MediaClock()
    c.publish(60.0, 100.0, 1.0, True, 1)
    c.position(at=100.0)
    c.publish(5.0, 100.0, 1.0, True, 2)  # seek ย้อน = generation ใหม่
    assert c.position(at=100.0) == pytest.approx(5.0)
    assert c.generation == 2


def test_remote_clock_latency_and_slew() -> None:
    rc = RemoteClock()
    rc.update(media_time=30.0, sent_at_epoch_ms=1_000_000.0, rate=1.0, paused=False,
              now_host=50.0, now_epoch=1000.1)  # latency 0.1 วิ
    assert rc.position(50.0) == pytest.approx(30.1)
    assert rc.position(51.0) == pytest.approx(31.1)
    gen = rc.generation
    # คลาดเล็กน้อย (0.1 วิ) -> ไม่กระโดด ค่อยๆ ไล่
    rc.update(31.2, 1_001_000.0, 1.0, False, now_host=51.0, now_epoch=1001.0)
    assert rc.generation == gen
    assert rc.position(51.0) == pytest.approx(31.1)
    assert rc.position(51.5) == pytest.approx(31.7, abs=1e-6)  # ไล่ทันภายใน 0.5 วิ
    # คลาดมาก -> snap + generation ใหม่
    rc.update(90.0, 1_002_000.0, 1.0, False, now_host=52.0, now_epoch=1002.0)
    assert rc.position(52.0) == pytest.approx(90.0)
    assert rc.generation == gen + 1


# ---------------- ข้อความ ----------------
def test_frame_roundtrip_thai_and_split_chunks() -> None:
    msg = Envelope.new("play_now", {"track": {"video_id": "abcdefghijk", "title": "เพลงทดสอบ"}})
    frame = encode_frame(msg)
    assert struct.unpack("<I", frame[:4])[0] == len(frame) - 4
    dec = FrameDecoder()
    out = []
    for i in range(0, len(frame) * 2, 3):  # ส่งสองข้อความ ตัดเป็นชิ้นละ 3 ไบต์
        out += dec.feed((frame + frame)[i : i + 3])
    assert len(out) == 2
    env = Envelope.from_dict(out[0], EXT_TO_APP)
    assert env.payload["track"]["title"] == "เพลงทดสอบ"


def test_envelope_rejects_unknown_and_future() -> None:
    with pytest.raises(MessageError):
        Envelope.from_dict({"type": "rm_rf"}, EXT_TO_APP)
    with pytest.raises(MessageError):
        Envelope.from_dict({"type": "ping", "v": 99}, EXT_TO_APP)
    with pytest.raises(MessageError):
        Envelope.from_dict({"type": "ping", "payload": []}, EXT_TO_APP)


# ---------------- คิวงาน AI ----------------
def test_scheduler_priority_cancel_promote() -> None:
    s = JobScheduler()
    s.push(Job("n1", "align_chunk", "next", Priority.NEXT_TRACK, 0, 20))
    s.push(Job("c2", "align_chunk", "cur", Priority.CURRENT_REST, 40, 60))
    s.push(Job("c1", "align_chunk", "cur", Priority.CURRENT_REST, 20, 40))
    s.push(Job("c3", "align_chunk", "cur", Priority.CURRENT_REST, 120, 140))
    assert s.promote("cur", around_s=125, window_s=10) == 1  # seek ไป 125 วิ
    assert [s.pop().job_id for _ in range(2)] == ["c3", "c1"]
    assert s.cancel_video("next") == ["n1"]
    assert s.pop().job_id == "c2"
    assert s.pop() is None


def test_plan_chunks_never_cut_lines() -> None:
    lines = [(i * 4.0 + 1.0, i * 4.0 + 4.5) for i in range(49)]  # บรรทัดละ 3.5 วิ ทุก 4 วิ
    chunks = plan_chunks(lines, duration=200.0, first_chunk_s=25, chunk_s=20, overlap_s=2.5)
    assert chunks[0][0] == 0.0 and chunks[-1][1] == 200.0
    for (s0, e0), (s1, e1) in zip(chunks, chunks[1:]):
        assert s1 < e0, "ช่วงติดกันต้องซ้อนกัน"
        assert s1 > s0
    for ls, le in lines:
        assert any(s <= ls and le <= e for s, e in chunks), f"บรรทัด {ls}-{le} ถูกตัด"
    assert chunks[0][1] - chunks[0][0] <= 30  # ช่วงแรก 20-30 วิ


def test_plan_chunks_edge_cases() -> None:
    assert plan_chunks([], 0) == []
    assert plan_chunks([], 10.0) == [(0.0, 10.0)]


# ---------------- automation ----------------
def test_curves_are_monotonic_and_bounded() -> None:
    x = np.linspace(0, 1, 101)
    for name, f in CURVES.items():
        y = f(x)
        assert y[0] == pytest.approx(0) and y[-1] == pytest.approx(1), name
        assert np.all(np.diff(y) >= -1e-12), name
    eq = CURVES["equal_power"]
    assert np.allclose(eq(x) ** 2 + eq(1 - x) ** 2, 1.0)  # พลังงานคงที่


def test_lane_holds_edges() -> None:
    lane = AutomationLane.ramp(Param.GAIN, start_frame=1000, length_frames=48000, v0=1.0, v1=0.0, curve="s_curve")
    assert lane.value_at(0) == 1.0
    assert lane.value_at(10**9) == 0.0
    assert 0.0 < lane.value_at(25000) < 1.0


# ---------------- models / อื่นๆ ----------------
def test_lyrics_json_roundtrip() -> None:
    ly = Lyrics(
        lines=[Line(1.0, 3.0, [Word("สวัสดี", 1.0, 2.0, timing=WordTimingSource.ESTIMATED),
                               Word("world", 2.0, 3.0, trailing_space=True)], voice=Voice.SECOND,
                    translation="hello")],
        timing=TimingLevel.WORD, source="test", ai_transcribed=True,
    )
    back = Lyrics.from_dict(json.loads(json.dumps(ly.to_dict(), ensure_ascii=False)))
    assert back == ly
    assert back.lines[0].text == "สวัสดีworld"


def test_parse_video_id() -> None:
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=x") == "dQw4w9WgXcQ"
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ?t=3") == "dQw4w9WgXcQ"
    assert parse_video_id("https://music.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("hello world") is None


def test_extension_id_from_key_format() -> None:
    import base64

    ext_id = extension_id_from_key(base64.b64encode(b"any-der-bytes").decode())
    assert len(ext_id) == 32 and set(ext_id) <= set("abcdefghijklmnop")


def test_event_bus_handler_crash_isolated() -> None:
    bus = EventBus()
    got = []
    bus.subscribe("x", lambda t, d: 1 / 0)
    bus.subscribe("x", lambda t, d: got.append(d))
    bus.publish("x", {"a": 1})
    assert got == [{"a": 1}]


def test_state_atomic_save_and_corrupt_load(tmp_path) -> None:
    p = tmp_path / "state.json"
    save_state(p, {"video_id": "abcdefghijk", "position_s": 12.5})
    assert load_state(p)["position_s"] == 12.5
    p.write_text("{broken", encoding="utf-8")
    assert load_state(p) is None
