"""PlayerController: ประกอบ media + decoder + engine + เนื้อเพลง (ไม่ใช้เครือข่าย/ลำโพง)"""

from __future__ import annotations

import shutil
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.audio.engine import AudioEngine, EngineConfig
from app.core.config import Settings
from app.core.events import EventBus
from app.core.io_thread import IoThread
from app.core.models import Line, Lyrics, TimingLevel, TrackRef, Word
from app.lyrics.service import LyricsResult
from app.media.youtube import DownloadResult, VideoInfo
from app.player.controller import PlayerController

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ต้องมี ffmpeg")
VID = "vid00000001"


def make_wav(path: Path, seconds: float = 3.0, sr: int = 44100) -> None:
    t = np.arange(int(seconds * sr)) / sr
    data = (np.sin(2 * np.pi * 440 * t) * 0.3 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


class FakeMedia:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def fetch_and_download(self, video_id, target_dir, on_info=None, on_progress=None):
        self.calls += 1
        if self.fail:
            from app.core.errors import MediaError

            raise MediaError("media", "วิดีโอนี้เปิดไม่ได้")
        track = TrackRef(video_id=video_id, title="Nova Waves - Midnight Drive", channel="Nova Waves", duration=3.0)
        vi = VideoInfo(track=track, duration=3.0, audio_format="251 opus 130k")
        if on_info:
            on_info(vi)
        time.sleep(0.05)
        path = Path(target_dir) / f"{video_id}.wav"
        make_wav(path)
        if on_progress:
            on_progress(1.0)
        return vi, DownloadResult(path=path, audio_format="251 opus 130k", cookie_mode="none")


class FakeLyrics:
    async def find(self, track, duration, extras=None, on_update=None):
        ly = Lyrics(lines=[Line(0, 1, [Word("hello", 0, 1)])], timing=TimingLevel.LINE, source="fake")
        return LyricsResult(ly, [], "จาก FAKE · ทีละบรรทัด")

    async def next_candidate(self, video_id):
        return await self.find(None, None)


@pytest.fixture()
def rig(app_paths):
    bus = EventBus()
    io = IoThread().start()
    engine = AudioEngine(EngineConfig())
    engine.start(open_stream=False, sample_rate=48000)
    stop = threading.Event()
    out = np.zeros((480, 2), np.float32)

    def pump() -> None:  # แทน PortAudio: เรียก callback เร็วกว่าเวลาจริงเล็กน้อย
        while not stop.is_set():
            engine._callback(out, 480, None, None)
            time.sleep(0.002)

    threading.Thread(target=pump, daemon=True).start()
    media = FakeMedia()
    ctl = PlayerController(engine, bus, FakeLyrics(), media, None, app_paths.db_file, Settings(),
                           paths=app_paths, io=io)
    events: list[tuple[str, dict]] = []
    bus.subscribe("*", lambda t, d: events.append((t, d)))
    yield SimpleNamespace(ctl=ctl, bus=bus, engine=engine, media=media, events=events, paths=app_paths, io=io)
    stop.set()
    ctl.shutdown()
    io.stop()


def wait_for(cond, timeout: float = 8.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def topics(rig) -> list[str]:
    return [t for t, _ in rig.events]


def test_play_loads_audio_and_publishes_events(rig) -> None:
    rig.ctl.play(TrackRef(video_id=VID))
    assert wait_for(lambda: rig.ctl.playing and rig.ctl.loaded)
    assert wait_for(lambda: "lyrics.ready" in topics(rig) and "track.meta_ready" in topics(rig))
    assert topics(rig).index("track.changed") < topics(rig).index("playback.state")
    # นาฬิกาเดินจริงตามที่ engine เล่น
    p1 = rig.ctl.get_clock().position()
    time.sleep(0.3)
    assert rig.ctl.get_clock().position() > p1
    assert rig.engine.stats.callback_errors == 0
    ready = next(d for t, d in rig.events if t == "lyrics.ready")
    assert ready["video_id"] == VID and ready["lyrics"] is not None


def test_second_play_uses_cache_without_media(rig) -> None:
    rig.ctl.play(TrackRef(video_id=VID))
    assert wait_for(lambda: rig.ctl.loaded)
    # รอให้ decoder จบและลงทะเบียน cache
    assert wait_for(lambda: rig.paths.audio_cache_dir.joinpath(f"{VID}.f32.meta.json").exists())
    assert wait_for(lambda: bool(rig.ctl._conn().execute("SELECT 1 FROM audio_cache WHERE video_id=?", (VID,)).fetchone()))
    assert not list(rig.paths.audio_cache_dir.glob("*.wav"))  # ไฟล์ดิบถูกลบ
    n = rig.media.calls
    rig.events.clear()
    rig.ctl.play(TrackRef(video_id=VID))
    assert wait_for(lambda: "playback.state" in topics(rig))
    assert rig.media.calls == n  # ไม่เรียก yt-dlp ซ้ำ


def test_pause_seek_and_end(rig) -> None:
    rig.ctl.play(TrackRef(video_id=VID))
    assert wait_for(lambda: rig.ctl.playing)
    rig.ctl.toggle_pause()
    assert not rig.ctl.playing
    time.sleep(0.1)
    p = rig.ctl.get_clock().position()
    time.sleep(0.2)
    assert abs(rig.ctl.get_clock().position() - p) < 0.05  # หยุดจริง
    rig.ctl.seek(2.0)
    time.sleep(0.1)
    assert rig.ctl.get_clock().position() == pytest.approx(2.0, abs=0.3)
    rig.ctl.toggle_pause()
    rig.ctl.start_background_tasks()
    # เล่นต่อถึงจบเพลง (3 วิ) -> ticker ส่ง playing=False
    assert wait_for(lambda: any(t == "playback.state" and not d["playing"] for t, d in rig.events[-5:]), 6.0)


def test_new_play_cancels_previous_and_failure_reports_error(rig) -> None:
    rig.media.fail = True
    rig.ctl.play(TrackRef(video_id=VID))
    assert wait_for(lambda: "error" in topics(rig))
    err = next(d for t, d in rig.events if t == "error")
    assert "เปิดไม่ได้" in err["user_message"] and err["recoverable"]
    assert not rig.ctl.loaded
    rig.media.fail = False
    rig.ctl.play(TrackRef(video_id="vid00000002"))
    assert wait_for(lambda: rig.ctl.loaded)
    assert rig.ctl.track.video_id == "vid00000002"


def test_play_url_invalid_and_valid(rig) -> None:
    rig.ctl.play_url("ไม่ใช่ลิงก์")
    assert any(t == "error" for t in topics(rig))
    rig.ctl.play_url("https://youtu.be/2yqYAsUpdSc?list=RD2yqYAsUpdSc")
    assert wait_for(lambda: rig.ctl.track is not None and rig.ctl.track.video_id == "2yqYAsUpdSc")
    assert wait_for(lambda: rig.ctl.loaded)


def test_offset_persists_per_track(rig) -> None:
    rig.ctl.play(TrackRef(video_id=VID))
    assert wait_for(lambda: rig.ctl.loaded and "lyrics.offset" in topics(rig))
    rig.ctl.adjust_offset(0.1)
    rig.ctl.adjust_offset(0.1)
    assert rig.ctl.lyrics_offset == pytest.approx(0.2)
    row = rig.ctl._conn().execute("SELECT lyrics_offset_s FROM tracks WHERE video_id=?", (VID,)).fetchone()
    assert row["lyrics_offset_s"] == pytest.approx(0.2)
    assert [d["offset"] for t, d in rig.events if t == "lyrics.offset"][-1] == pytest.approx(0.2)


def test_snapshot_and_restore_paused(rig) -> None:
    rig.ctl.play(TrackRef(video_id=VID))
    assert wait_for(lambda: rig.ctl.loaded)
    snap = rig.ctl.snapshot()
    assert snap["video_id"] == VID and snap["track_ref"]["video_id"] == VID
    rig.ctl.toggle_pause()
    assert rig.ctl.restore(snap)
    ok = wait_for(lambda: rig.ctl.loaded)
    errs = [d for t, d in rig.events if t == "error"]
    assert ok, f"restore ไม่สำเร็จ: {errs}"
    assert wait_for(lambda: not rig.ctl.playing), f"errors={errs}"  # กู้แล้วต้องหยุดไว้ ยังไม่เล่นเอง


def test_replaying_same_track_does_not_reload(rig) -> None:
    """กดลิงก์เดิมซ้ำขณะเพลงโหลดอยู่ = กลับต้นเพลง ไม่ดาวน์โหลด/ถอดรหัสใหม่ (กันไฟล์ memmap ถูกล็อกบน Windows)"""
    rig.ctl.play(TrackRef(video_id=VID))
    assert wait_for(lambda: rig.ctl.loaded)
    n = rig.media.calls
    time.sleep(0.5)
    before = rig.ctl.get_clock().position()
    rig.ctl.play(TrackRef(video_id=VID))
    time.sleep(0.1)
    assert rig.media.calls == n and not [d for t, d in rig.events if t == "error"]
    assert rig.ctl.get_clock().position() < before  # กลับไปต้นเพลง (pump ใน test เดินเร็วกว่าเวลาจริง)
