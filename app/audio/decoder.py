"""ถอดรหัสไฟล์เสียงเป็น PCM float32 ด้วย ffmpeg (subprocess) แบบทยอย

ffmpeg -i <ไฟล์จาก yt-dlp> -f f32le -ac 2 -ar <engine rate> pipe:1
อ่าน stdout ทีละก้อน เขียนลง PcmBuffer (memmap .f32) แล้วเพิ่ม frames_ready
-> deck เริ่มเล่นได้เมื่อมีเสียงพอ ~2 วิ ไม่ต้องรอถอดรหัสทั้งเพลง (เป้าหมาย: เริ่มภายใน 3 วิ)

ffmpeg: หา bin/ffmpeg.exe ข้างโปรแกรมก่อน (ตัวติดตั้งรวมไว้) แล้วค่อย PATH

ไฟล์ข้างเคียง: <target>.meta.json (frames, sample_rate, complete) เขียนเมื่อถอดรหัสเสร็จสมบูรณ์
เพื่อให้ครั้งถัดไปใช้ cache ซ้ำได้ด้วย open_cached() โดยไม่ต้องถอดรหัสใหม่
หมายเหตุ: memmap คงขนาดที่จองไว้ (duration + 2 วิ) — จำนวนเฟรมจริงอยู่ที่ buffer.total_frames / sidecar
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.audio.deck import PcmBuffer
from app.core.errors import MediaError
from app.core.paths import PROJECT_ROOT

CHUNK_BYTES = 65536          # ขนาดอ่านจาก stdout ต่อครั้ง
FRAME_BYTES = 8              # float32 x 2 ช่อง
PROGRESS_INTERVAL_S = 0.25   # on_progress ถี่สุดเท่านี้
_CREATE_NO_WINDOW = 0x08000000


@dataclass(slots=True)
class DecodeJob:
    source: Path | str          # ไฟล์ที่ yt-dlp โหลดมา (หรือ URL สตรีม)
    target: Path                # <cache>/audio/<videoId>.f32
    sample_rate: int
    duration_s: float           # ใช้จองขนาด memmap ล่วงหน้า (+ เผื่อ 2 วิ)
    http_headers: dict[str, str] | None = None


def find_ffmpeg() -> Path | None:
    """หา ffmpeg: bin/ ข้างโปรแกรม (PROJECT_ROOT) ก่อน แล้วค่อย PATH — ไม่พบคืน None"""
    for name in ("ffmpeg.exe", "ffmpeg"):
        local = PROJECT_ROOT / "bin" / name
        if local.is_file():
            return local
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def meta_path(target: Path) -> Path:
    """path ของไฟล์ sidecar ของ <target>"""
    return target.with_name(target.name + ".meta.json")


def open_cached(target: Path, sample_rate: int) -> PcmBuffer | None:
    """เปิดไฟล์ PCM ที่เคยถอดรหัสเสร็จแล้วกลับมาใช้ (คืน None ถ้าไม่มี/ไม่ตรง sample rate/ไฟล์เสีย)"""
    target = Path(target)
    try:
        meta = json.loads(meta_path(target).read_text(encoding="utf-8"))
        frames = int(meta["frames"])
        if not meta.get("complete") or int(meta["sample_rate"]) != sample_rate or frames <= 0:
            return None
        if not target.is_file() or target.stat().st_size < frames * FRAME_BYTES:
            return None
        buf = PcmBuffer.open_file(target, sample_rate, frames)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    buf.frames_ready = frames
    buf.total_frames = frames
    buf.complete = True
    return buf


class Decoder:
    """ตัวถอดรหัสหนึ่งงาน รันใน thread ของตัวเอง ยกเลิกได้"""

    def __init__(self, job: DecodeJob, on_progress: Callable[[int], None] | None = None) -> None:
        self.job = job
        self.on_progress = on_progress
        self.buffer: PcmBuffer | None = None
        self.error: str | None = None           # ข้อความ error (ภาษาไทย) ถ้าถอดรหัสล้มเหลว
        self.finished = threading.Event()       # ตั้งเมื่อ thread จบ (สำเร็จ ล้มเหลว หรือยกเลิก)
        self.cancelled = False
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stderr_tail = b""

    # ------------------------------------------------------------------
    @staticmethod
    def open_cached(target: Path, sample_rate: int) -> PcmBuffer | None:
        """ทางลัดไป open_cached() ระดับ module"""
        return open_cached(target, sample_rate)

    def start(self) -> PcmBuffer:
        """เริ่ม ffmpeg และคืน PcmBuffer ทันที (ข้อมูลจะทยอยมา) — raise MediaError ถ้าไม่พบ ffmpeg"""
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            raise MediaError(
                "media",
                "ไม่พบ ffmpeg สำหรับถอดรหัสเสียง",
                hint="วาง ffmpeg.exe ไว้ในโฟลเดอร์ bin ข้างโปรแกรม หรือเพิ่มลง PATH",
                recoverable=False,
            )
        job = self.job
        target = Path(job.target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # เริ่มใหม่เสมอ: ลบไฟล์/sidecar เก่า (ถ้าอยากใช้ซ้ำให้เรียก open_cached ก่อน)
        for p in (target, meta_path(target)):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                raise MediaError("media", "เขียนไฟล์ cache เสียงไม่ได้", hint=str(e)) from e

        cmd: list[str] = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin"]
        if job.http_headers:
            headers = "".join(f"{k}: {v}\r\n" for k, v in job.http_headers.items())
            cmd += ["-headers", headers]
        cmd += [
            "-i", str(job.source), "-vn", "-f", "f32le",
            "-ac", "2", "-ar", str(job.sample_rate), "pipe:1",
        ]
        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, creationflags=creationflags,
            )
        except OSError as e:
            raise MediaError("media", "เปิด ffmpeg ไม่สำเร็จ", hint=str(e)) from e

        total_frames = max(1, int((job.duration_s + 2.0) * job.sample_rate))
        self.buffer = PcmBuffer.open_file(target, job.sample_rate, total_frames)
        threading.Thread(target=self._drain_stderr, name="decoder-stderr", daemon=True).start()
        self._thread = threading.Thread(target=self._run, name="decoder", daemon=True)
        self._thread.start()
        return self.buffer

    def wait_for_frames(self, n: int, timeout: float) -> bool:
        """รอจน frames_ready >= n (หรือถอดรหัสจบสมบูรณ์ถึงเพลงสั้นกว่า n) — timeout/error คืน False"""
        buf = self.buffer
        if buf is None:
            return False
        deadline = time.monotonic() + timeout
        while True:
            if buf.frames_ready >= n:
                return True
            if self.error is not None or self.cancelled:
                return False
            if self.finished.is_set():
                return buf.complete  # จบแล้วแต่ไม่ถึง n = เพลงสั้นกว่าที่ขอ ถ้าสมบูรณ์ถือว่าพร้อมทั้งหมด
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.finished.wait(min(0.02, remaining))

    def cancel(self) -> None:
        """ฆ่า ffmpeg และลบไฟล์ที่ยังไม่สมบูรณ์ (ไฟล์ที่เสร็จแล้วไม่ถูกลบ)"""
        self.cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3.0)
        buf = self.buffer
        if buf is None or buf.complete:
            return
        target = Path(self.job.target)
        # ปล่อย memmap ก่อน ไม่งั้น Windows ลบไฟล์ไม่ได้
        buf.frames_ready = 0
        buf.data = np.zeros((0, 2), dtype=np.float32)
        gc.collect()
        for p in (target, meta_path(target)):
            try:
                p.unlink()
            except OSError:
                pass
        self.finished.set()

    # ------------------------------------------------------------------
    def _drain_stderr(self) -> None:
        """อ่าน stderr ของ ffmpeg กันท่อเต็ม เก็บท้ายๆ ไว้ใช้เป็นข้อความ error"""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                self._stderr_tail = (self._stderr_tail + chunk)[-2000:]
        except (OSError, ValueError):
            pass

    def _report(self, frames: int) -> None:
        if self.on_progress is not None:
            try:
                self.on_progress(frames)
            except Exception:  # callback ของผู้เรียกพังต้องไม่ฆ่า thread ถอดรหัส
                pass

    def _run(self) -> None:
        """thread อ่าน stdout -> เขียน buffer; ห้าม raise ออกนอก thread (เก็บใน self.error)"""
        try:
            self._read_loop()
        except Exception as e:  # noqa: BLE001 — เก็บทุกกรณีให้ player ตัดสินใจ
            if not self.cancelled:
                self.error = f"ถอดรหัสเสียงผิดพลาด: {e}"
        finally:
            self.finished.set()

    def _read_loop(self) -> None:
        proc = self._proc
        buf = self.buffer
        assert proc is not None and buf is not None and proc.stdout is not None
        capacity = buf.data.shape[0]
        written = 0
        pending = b""
        last_report = 0.0
        overflow = False

        while not self.cancelled:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            data = pending + chunk
            usable = len(data) - (len(data) % FRAME_BYTES)  # คงขอบเขต frame 8 ไบต์
            pending = data[usable:]
            frames = usable // FRAME_BYTES
            if frames == 0:
                continue
            if written + frames > capacity:  # ยาวกว่าที่ประเมินไว้ (duration ผิด): ตัดที่ขนาดที่จอง
                frames = capacity - written
                overflow = True
            if frames > 0:
                arr = np.frombuffer(data, dtype=np.float32, count=frames * 2).reshape(frames, 2)
                buf.data[written:written + frames] = arr   # เขียนข้อมูลก่อน
                written += frames
                buf.frames_ready = written                 # แล้วค่อยประกาศจำนวน (callback อ่านเฉพาะค่านี้)
            if overflow:
                try:
                    proc.kill()
                except OSError:
                    pass
                break
            now = time.monotonic()
            if now - last_report >= PROGRESS_INTERVAL_S:
                last_report = now
                self._report(written)

        if self.cancelled:
            return
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = proc.wait()
        if overflow:
            rc = 0  # เราเป็นคนฆ่าเอง ถือว่าได้เสียงครบเท่าที่จอง
        # ให้ thread stderr อ่านท้ายสุดให้เสร็จ
        time.sleep(0.01)
        if written == 0:
            tail = self._stderr_tail.decode("utf-8", errors="replace").strip().splitlines()
            detail = tail[-1] if tail else f"รหัสออก {rc}"
            self.error = f"ffmpeg ถอดรหัสไม่ได้: {detail}"
            return

        buf.total_frames = written  # จำนวนเฟรมจริง (memmap ยังใหญ่กว่านี้ ไม่ย่อไฟล์)
        buf.complete = True
        self._report(written)
        if isinstance(buf.data, np.memmap):
            buf.data.flush()
        if rc != 0:
            # ได้เสียงบางส่วนแต่ ffmpeg จบผิดปกติ: เล่นเท่าที่มีได้ แต่ไม่เก็บเป็น cache ที่เชื่อถือได้
            self.error = None
            return
        try:
            tmp = meta_path(Path(self.job.target)).with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"frames": written, "sample_rate": self.job.sample_rate, "complete": True}),
                encoding="utf-8",
            )
            os.replace(tmp, meta_path(Path(self.job.target)))
        except OSError:
            pass  # เขียน sidecar ไม่ได้แค่เสียโอกาสใช้ cache ซ้ำ
