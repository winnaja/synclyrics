"""ทดสอบ Decoder ด้วย ffmpeg จริง (ข้ามถ้าไม่มี) และ ffmpeg ปลอมสำหรับกรณี cancel/argv"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.audio import decoder as dec
from app.audio.decoder import DecodeJob, Decoder, find_ffmpeg, meta_path, open_cached
from app.core.errors import MediaError

FFMPEG = find_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ไม่มี ffmpeg")
SR = 48000


def make_wav(tmp_path: Path, seconds: float = 3.0, rate: int = 44100) -> Path:
    wav = tmp_path / "in.wav"
    subprocess.run(
        [str(FFMPEG), "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}", "-ar", str(rate), "-ac", "1", str(wav)],
        check=True,
    )
    return wav


def test_find_ffmpeg_prefers_project_bin_then_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dec.shutil, "which", lambda name: None)
    monkeypatch.setattr(dec, "PROJECT_ROOT", tmp_path)
    assert find_ffmpeg() is None
    monkeypatch.setattr(dec.shutil, "which", lambda name: str(tmp_path / "onpath.exe"))
    assert find_ffmpeg() == tmp_path / "onpath.exe"
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "ffmpeg.exe").write_bytes(b"")
    assert find_ffmpeg() == tmp_path / "bin" / "ffmpeg.exe"


def test_start_without_ffmpeg_raises_media_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dec, "find_ffmpeg", lambda: None)
    d = Decoder(DecodeJob("x.wav", tmp_path / "a.f32", SR, 1.0))
    with pytest.raises(MediaError) as ei:
        d.start()
    assert ei.value.module == "media" and "ffmpeg" in ei.value.user_message


def test_command_line_headers_and_no_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict = {}

    def fake_popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        raise OSError("stop here")

    monkeypatch.setattr(dec, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(dec.subprocess, "Popen", fake_popen)
    job = DecodeJob("http://x/y", tmp_path / "a.f32", 44100, 1.0, http_headers={"User-Agent": "UA"})
    with pytest.raises(MediaError):
        Decoder(job).start()
    cmd = seen["cmd"]
    assert cmd[cmd.index("-ar") + 1] == "44100" and cmd[-1] == "pipe:1"
    assert "f32le" in cmd and cmd[cmd.index("-ac") + 1] == "2"
    assert cmd[cmd.index("-headers") + 1] == "User-Agent: UA\r\n"
    assert cmd.index("-headers") < cmd.index("-i")
    if sys.platform == "win32":
        assert seen["kw"]["creationflags"] == 0x08000000


@needs_ffmpeg
def test_decode_sine_complete_and_cache_reuse(tmp_path: Path) -> None:
    wav = make_wav(tmp_path, 3.0)
    target = tmp_path / "cache" / "v.f32"
    progress: list[int] = []
    d = Decoder(DecodeJob(wav, target, SR, 3.0), on_progress=progress.append)
    buf = d.start()
    assert buf.sample_rate == SR and not buf.complete or buf.complete
    seen: list[int] = []
    deadline = time.monotonic() + 20
    while not d.finished.is_set() and time.monotonic() < deadline:
        seen.append(buf.frames_ready)
        time.sleep(0.005)
    assert d.finished.wait(5)
    assert d.error is None and buf.complete
    assert seen == sorted(seen)  # ไม่ถอยหลัง
    assert abs(buf.total_frames - 3 * SR) < 0.03 * 3 * SR
    assert buf.frames_ready == buf.total_frames
    assert buf.data.shape[0] == int(5.0 * SR)  # memmap คงขนาดที่จอง
    peak = float(abs(buf.data[:buf.total_frames]).max())
    assert 0.05 < peak < 0.4  # ไซน์ ~0.125
    assert (buf.data[:1000, 0] == buf.data[:1000, 1]).all()  # mono -> สองช่องเหมือนกัน
    assert progress and progress[-1] == buf.total_frames and progress == sorted(progress)
    assert d.wait_for_frames(2 * SR, 0.1) is True
    assert meta_path(target).is_file()

    frames = buf.total_frames
    del buf, d
    cached = open_cached(target, SR)
    assert cached is not None and cached.complete and cached.total_frames == frames
    assert cached.frames_ready == frames
    assert float(abs(cached.data[:frames]).max()) > 0.05
    assert open_cached(target, 44100) is None  # sample rate ไม่ตรง
    assert Decoder.open_cached(target, SR) is not None
    del cached
    meta_path(target).unlink()
    assert open_cached(target, SR) is None  # ไม่มี sidecar


@needs_ffmpeg
def test_wait_for_frames_returns_early_before_complete(tmp_path: Path) -> None:
    wav = make_wav(tmp_path, 3.0)
    d = Decoder(DecodeJob(wav, tmp_path / "w.f32", SR, 3.0))
    buf = d.start()
    assert d.wait_for_frames(SR // 2, 15.0) is True
    assert buf.frames_ready >= SR // 2
    d.finished.wait(10)
    # ขอมากกว่าที่เพลงมี: จบแล้วสมบูรณ์ -> True
    assert d.wait_for_frames(10 * SR, 1.0) is True
    del buf


@needs_ffmpeg
def test_bad_source_sets_error_without_raising(tmp_path: Path) -> None:
    d = Decoder(DecodeJob(tmp_path / "missing.wav", tmp_path / "bad.f32", SR, 1.0))
    d.start()
    assert d.wait_for_frames(SR, 15.0) is False
    assert d.finished.wait(5)
    assert d.error and "ffmpeg" in d.error
    assert not d.buffer.complete
    assert not meta_path(tmp_path / "bad.f32").exists()


def make_slow_fake(tmp_path: Path) -> Path:
    """ffmpeg ปลอม (.cmd -> python) ที่ส่งเสียงศูนย์ช้าๆ เพื่อทดสอบ cancel"""
    script = tmp_path / "slow.py"
    script.write_text(
        "import sys, time\n"
        "out = sys.stdout.buffer\n"
        "chunk = b'\\x00' * 65536\n"
        "try:\n"
        "    for _ in range(100):\n"
        "        out.write(chunk); out.flush(); time.sleep(0.2)\n"
        "except Exception:\n"
        "    pass\n",
        encoding="utf-8",
    )
    cmd = tmp_path / "fakeffmpeg.cmd"
    cmd.write_text(f'@echo off\r\n"{sys.executable}" "{script}"\r\n', encoding="utf-8")
    return cmd


@pytest.mark.skipif(sys.platform != "win32", reason="ffmpeg ปลอมแบบ .cmd ใช้ได้เฉพาะ Windows")
def test_cancel_removes_incomplete_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dec, "find_ffmpeg", lambda: make_slow_fake(tmp_path))
    target = tmp_path / "c" / "x.f32"
    d = Decoder(DecodeJob("ignored", target, SR, 600.0))
    buf = d.start()
    assert d.wait_for_frames(8192, 20.0)  # ได้ข้อมูลบางส่วนแล้ว แต่ยังไม่จบ
    assert not buf.complete
    assert target.exists()
    d.cancel()
    assert d.finished.is_set()
    assert not target.exists() and not meta_path(target).exists()
    assert d.wait_for_frames(10**9, 0.1) is False
    assert d.error is None  # ยกเลิกไม่ใช่ error
