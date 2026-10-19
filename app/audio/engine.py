"""AudioEngine — หัวใจของโปรแกรม: เสียงห้ามสะดุดเด็ดขาด (ARCHITECTURE.md §3)

โครงสร้าง thread:
  - PortAudio callback thread (sounddevice, WASAPI shared): เรียก _callback ทุก ~10-20ms
  - engine control thread: จัดการ underrun (เปิด stream ใหม่ด้วย buffer ใหญ่ขึ้น), log สถิติ
  - ฝั่งอื่น (player, UI) เรียกเมธอดสาธารณะได้จากทุก thread — เมธอดเหล่านี้แค่ใส่คำสั่งลง deque

กฎเหล็กของ _callback (ห้ามละเมิด — ละเมิดแล้วเสียงกระตุกแบบหาสาเหตุยาก):
  1. ห้าม lock / ห้าม I/O / ห้าม log / ห้ามเรียก DB / ห้ามรอ queue แบบบล็อก
  2. ห้ามจอง numpy array ใหม่ — ใช้ scratch buffer ที่จองไว้ตอนเปิด stream และ out= ทุกครั้ง
  3. คำสั่งจากภายนอกอ่านจาก collections.deque ด้วย popleft() (atomic ใน CPython ไม่ต้อง lock)
  4. exception ใน callback: ส่งความเงียบ + เพิ่มตัวนับ error (control thread เป็นคน log)
  5. งานที่หนักกว่า "ก็อป PCM + คูณ gain + filter ต่อ block" ต้องทำล่วงหน้านอก callback

GIL: AI อยู่คนละ process แล้ว งาน CPU ใน process หลักต้องแบ่งเป็นชิ้นสั้น (<5ms ต่อชิ้น)
engine ตั้ง sys.setswitchinterval(0.001) ให้ callback ได้ GIL เร็ว — ดู docs/DECISIONS.md

sample rate ของ engine = sample rate เริ่มต้นของอุปกรณ์เสียง (มักเป็น 48000)
decoder resample ให้ตรงตั้งแต่ถอดรหัส callback จึงไม่ต้อง resample

การทดสอบโดยไม่มีอุปกรณ์เสียง: start(open_stream=False) แล้วเรียก _callback(outdata, frames, None, None)
เองใน loop (หรือ render(frames)) — พฤติกรรมเหมือน stream จริงทุกอย่าง ยกเว้นไม่มี PortAudio
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from math import ceil
from typing import Any

import numpy as np

from app.audio.automation import AutomationLane, Param
from app.audio.deck import Deck, DeckState, Segment
from app.audio.dsp import Limiter
from app.core.clock import MediaClock
from app.core.errors import AudioDeviceError

log = logging.getLogger(__name__)

CHANNELS = 2
STALL_TIMEOUT_S = 1.5   # callback หยุดเรียกนานเท่านี้ = stream ค้าง
REPORT_EVERY_S = 5.0
DTYPE = "float32"
MAX_BLOCK = 8192               # ขนาด block สูงสุดที่ scratch รองรับ (frame)
DEFAULT_SAMPLE_RATE = 48000    # ใช้ก่อน start() / โหมดทดสอบไม่เปิดอุปกรณ์
FADE_S = 0.005                 # fade สั้นตอน pause/resume/seek กันเสียงคลิก
VOLUME_RAMP_S = 0.02           # ramp ของ master volume

# สถานะผลการก็อป PCM ของ deck ใน block (ใช้ภายใน _render_deck)
_OK, _STARVED, _ENDED = 0, 1, 2


@dataclass(slots=True)
class EngineStats:
    """สถิติสำหรับหน้า debug (callback เขียนเฉพาะตัวเลข)"""

    callbacks: int = 0
    underruns: int = 0          # output_underflow จากอุปกรณ์
    starvations: int = 0        # เล่นถึงส่วนที่ decoder ยังถอดรหัสไม่ถึง
    callback_errors: int = 0
    max_callback_ms: float = 0.0
    limiter_gain_reduction_db: float = 0.0
    blocksize: int = 0
    latency_ms: float = 0.0
    sample_rate: int = 0
    buffer_ms: int = 0          # buffer ที่ใช้อยู่จริง (เพิ่มได้เมื่อ underrun ซ้ำ)
    last_error: str = ""        # ข้อความ exception ล่าสุดใน callback (control thread เอาไป log)


@dataclass(slots=True)
class EngineConfig:
    device: str | int | None = None  # None = อุปกรณ์เริ่มต้นของ Windows
    buffer_ms: int = 30              # เริ่มต้น 30ms (PROMPT ข้อ 7.4 บอก 10-20 แต่ UI หนักทำให้ callback สะดุดได้ถึง ~28ms — ดู DECISIONS)
    max_buffer_ms: int = 120         # underrun ซ้ำๆ เพิ่มได้ถึงเท่านี้
    master_volume: float = 1.0
    limiter_ceiling_db: float = -1.0


class _DeckRuntime:
    """สถานะของ deck ที่ใช้ภายใน callback เท่านั้น (fade, play_at, seek ที่รอ fade-out) — ไม่ใช่ API"""

    __slots__ = (
        "play_at", "gain", "target", "resume", "seek_pending", "seek_s",
        "status", "played", "starved", "pub_pos", "anchor_off", "anchor_pos",
    )

    def __init__(self) -> None:
        self.play_at = -1          # เวลา engine (frame) ที่จะเริ่มเล่น; -1 = ไม่มีนัด
        self.gain = 1.0            # gain จาก fade ปัจจุบัน (0..1)
        self.target = 1.0          # gain เป้าหมายของ fade (0 = กำลังพัก/รอ seek)
        self.resume = False        # หลัง seek เสร็จให้ fade-in เล่นต่อหรือไม่
        self.seek_pending = False  # seek ที่รอ fade-out ให้จบก่อน
        self.seek_s = 0.0
        self.status = _OK
        self.played = False        # block นี้ได้ก็อปเสียงจริงหรือไม่ (ใช้ตัดสิน playing ของนาฬิกา)
        self.starved = False
        self.pub_pos = 0.0         # ตำแหน่งเพลง ณ sample แรกของ block (เวลา media)
        self.anchor_off = -1       # ตำแหน่งใน block ที่เกิด play-start/jump (-1 = ไม่มี)
        self.anchor_pos = 0.0      # ตำแหน่งเพลง ณ จุด anchor

    def reset(self) -> None:
        self.play_at = -1
        self.gain = 1.0
        self.target = 1.0
        self.resume = False
        self.seek_pending = False
        self.anchor_off = -1


class AudioEngine:
    """เครื่องเล่น 2 deck — API ทุกตัว thread-safe และไม่บล็อก"""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.decks: tuple[Deck, Deck] = (Deck(0), Deck(1))
        # นาฬิกาแยกต่อ deck: ระหว่างมิกซ์มีสองเพลงพร้อมกัน UI อ่านของ deck ที่กำลังแสดงเนื้อเพลง
        self.clocks: tuple[MediaClock, MediaClock] = (MediaClock(), MediaClock())
        self.stats = EngineStats()
        self.frames_rendered: int = 0  # เวลา engine (frame) — automation และ play(at_frame) อ้างอิงค่านี้
        self._commands: deque[tuple[str, Any]] = deque()
        self._stream: Any = None
        # scratch จองครั้งเดียว (ห้ามจองใน callback): mix รวม, buffer ต่อ deck, ramp gain
        self._scratch: np.ndarray | None = np.zeros((MAX_BLOCK, CHANNELS), dtype=np.float32)
        self._dbuf = np.zeros((MAX_BLOCK, CHANNELS), dtype=np.float32)
        self._ramp = np.zeros((MAX_BLOCK, 1), dtype=np.float32)
        self._idx = np.arange(MAX_BLOCK, dtype=np.float32).reshape(-1, 1)
        self._rt: tuple[_DeckRuntime, _DeckRuntime] = (_DeckRuntime(), _DeckRuntime())
        self._sr = DEFAULT_SAMPLE_RATE
        self._fade_frames = max(1, int(self._sr * FADE_S))
        self._latency_s = 0.0
        self._limiter = Limiter(self._sr, config.limiter_ceiling_db, MAX_BLOCK)
        self._vol = float(config.master_volume)
        self._vol_target = self._vol
        self._vol_step = 0.0
        self._vol_left = 0
        self._buffer_ms = config.buffer_ms
        self._life = threading.Lock()  # ป้องกัน start/stop/reopen ชนกัน (ไม่ใช้ใน callback)
        self._stop_evt = threading.Event()
        self._control: threading.Thread | None = None
        self._started = False
        sys.setswitchinterval(0.001)

    # ------------------------------------------------------------------
    # วงจรชีวิต
    # ------------------------------------------------------------------
    def start(self, open_stream: bool = True, sample_rate: int | None = None) -> None:
        """เริ่ม engine

        open_stream=True: เปิด output stream (WASAPI shared ถ้ามี) + control thread
        open_stream=False: ไม่แตะอุปกรณ์เสียง (ใช้ใน test — เรียก _callback เอง) ใช้ sample_rate ที่ส่งมา
        (ค่าเริ่มต้น 48000)  raise AudioDeviceError ถ้าเปิดอุปกรณ์ไม่ได้
        """
        with self._life:
            if self._started:
                return
            self._stop_evt.clear()
            self._buffer_ms = self.config.buffer_ms
            if open_stream:
                self._open_stream(self._buffer_ms)
                self._control = threading.Thread(target=self._control_loop, name="engine-control", daemon=True)
                self._control.start()
            else:
                self._configure_rate(sample_rate or DEFAULT_SAMPLE_RATE)
                self.stats.blocksize = 0
                self.stats.buffer_ms = self._buffer_ms
            self._started = True

    def stop(self) -> None:
        """ปิด stream และ control thread (เรียกซ้ำได้)"""
        self._stop_evt.set()
        ctl = self._control
        if ctl is not None and ctl is not threading.current_thread():
            ctl.join(timeout=2.0)
        with self._life:
            self._close_stream()
            self._control = None
            self._started = False

    def set_device(self, device: str | int | None) -> None:
        """เปลี่ยนอุปกรณ์เสียงขาออก (เปิด stream ใหม่ เสียงขาดสั้นๆ ยอมรับได้)

        ถ้า sample rate ของอุปกรณ์ใหม่ต่างจากเดิม เพลงที่ถอดรหัสไว้ด้วย rate เก่าต้องถอดรหัสใหม่
        (ผู้เรียกดู engine.sample_rate หลังเปลี่ยน)
        """
        with self._life:
            self.config.device = device
            if self._stream is not None:
                self._close_stream()
                self._open_stream(self._buffer_ms)

    @property
    def sample_rate(self) -> int:
        return self.stats.sample_rate

    # ------------------------------------------------------------------
    # stream (ทั้งหมดนี้เรียกนอก callback เท่านั้น และถือ self._life)
    # ------------------------------------------------------------------
    def _configure_rate(self, sample_rate: int) -> None:
        """ตั้งค่าที่ขึ้นกับ sample rate (เรียกตอน stream หยุดอยู่เท่านั้น)"""
        self._sr = int(sample_rate)
        self._fade_frames = max(1, int(self._sr * FADE_S))
        self._limiter = Limiter(self._sr, self.config.limiter_ceiling_db, MAX_BLOCK)
        self.stats.sample_rate = self._sr

    def _resolve_device(self, sd: Any) -> int | str | None:
        """เลือกอุปกรณ์: ที่ผู้ใช้ตั้ง > WASAPI เริ่มต้น (Windows) > เริ่มต้นของระบบ"""
        if self.config.device is not None:
            return self.config.device
        try:
            for api in sd.query_hostapis():
                if "WASAPI" in str(api.get("name", "")):
                    dev = int(api.get("default_output_device", -1))
                    if dev >= 0:
                        return dev
            dev = int(sd.default.device[1])
            return dev if dev >= 0 else None
        except Exception:  # noqa: BLE001 — ถอยไปใช้ค่าเริ่มต้นของ sounddevice
            return None

    def _open_stream(self, buffer_ms: int) -> None:
        """เปิด OutputStream ตาม device/ buffer_ms ที่กำหนด — raise AudioDeviceError ถ้าไม่ได้"""
        try:
            import sounddevice as sd  # นำเข้าตอนใช้ (แอปต้อง import ได้แม้ไม่มี PortAudio)
        except Exception as e:  # noqa: BLE001
            raise AudioDeviceError("audio", "โหลดไลบรารีเสียง (sounddevice) ไม่ได้", hint=str(e)) from e

        last: Exception | None = None
        candidates = [self._resolve_device(sd)]
        if self.config.device is not None:
            candidates.append(None)  # อุปกรณ์ที่ตั้งไว้เปิดไม่ได้ -> ลองอุปกรณ์เริ่มต้น
        for dev in candidates:
            try:
                info = sd.query_devices(dev, "output")
                sr = int(info["default_samplerate"])
                blocksize = max(64, min(MAX_BLOCK, int(round(sr * buffer_ms / 1000.0))))
                stream = sd.OutputStream(
                    device=dev, samplerate=sr, channels=CHANNELS, dtype=DTYPE,
                    blocksize=blocksize, latency=buffer_ms / 1000.0, callback=self._callback,
                )
                self._configure_rate(sr)
                stream.start()
            except Exception as e:  # noqa: BLE001
                last = e
                continue
            self._stream = stream
            self.stats.blocksize = blocksize
            self.stats.buffer_ms = buffer_ms
            self._latency_s = float(stream.latency) if np.isscalar(stream.latency) else float(stream.latency[1])
            self.stats.latency_ms = self._latency_s * 1000.0
            return
        raise AudioDeviceError("audio", "เปิดอุปกรณ์เสียงไม่ได้", hint=str(last)) from last

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                log.exception("ปิด output stream ไม่สำเร็จ")

    def _control_loop(self) -> None:
        """thread ควบคุม: underrun ซ้ำ (>=3 ใน 5 วินาที) -> เปิด stream ใหม่ด้วย buffer ใหญ่ขึ้น"""
        events: deque[tuple[float, int]] = deque()
        last_underruns = self.stats.underruns
        last_errors = 0
        # watchdog: stream ค้าง (callback หยุดเรียก) เช่น อุปกรณ์เสียงถูกถอด/เปลี่ยน/ถูกโปรแกรมอื่นแย่ง -> เปิด stream ใหม่
        last_cb = self.stats.callbacks
        last_cb_change = time.monotonic()
        last_report = time.monotonic()
        report_base = (self.stats.starvations, self.stats.underruns, self.stats.callback_errors)
        while not self._stop_evt.wait(0.25):
            now = time.monotonic()
            if self.stats.callbacks != last_cb:
                last_cb, last_cb_change = self.stats.callbacks, now
            elif now - last_cb_change > STALL_TIMEOUT_S and self._stream is not None:
                log.error("audio stream ค้าง (callback หยุด %.1f วิ) เปิด stream ใหม่", now - last_cb_change)
                last_cb_change = now
                with self._life:
                    if self._stop_evt.is_set():
                        break
                    self._close_stream()
                    try:
                        self._open_stream(self._buffer_ms)
                    except AudioDeviceError:
                        log.exception("เปิด stream ใหม่หลังค้างไม่ได้")
            if now - last_report >= REPORT_EVERY_S:
                last_report = now
                cur = (self.stats.starvations, self.stats.underruns, self.stats.callback_errors)
                if cur != report_base:  # log เฉพาะเมื่อมีสิ่งผิดปกติเพิ่มขึ้น (ไว้ไล่บั๊กเสียงสะดุด/หาย)
                    log.warning("สถิติเสียง starvation=%d underrun=%d error=%d max_callback=%.1fms",
                                *cur, self.stats.max_callback_ms)
                    report_base = cur
            u = self.stats.underruns
            if u > last_underruns:
                events.append((now, u - last_underruns))
                last_underruns = u
            while events and now - events[0][0] > 5.0:
                events.popleft()
            errs = self.stats.callback_errors
            if errs != last_errors:
                last_errors = errs
                log.error("audio callback error x%d: %s", errs, self.stats.last_error)
            if sum(c for _, c in events) >= 3 and self._buffer_ms < self.config.max_buffer_ms:
                events.clear()
                new_ms = min(self.config.max_buffer_ms, max(self._buffer_ms + 10, int(self._buffer_ms * 2)))
                log.warning("underrun ซ้ำ: เพิ่ม buffer %d -> %d ms", self._buffer_ms, new_ms)
                with self._life:
                    if self._stop_evt.is_set():
                        break
                    self._close_stream()
                    try:
                        self._buffer_ms = new_ms
                        self._open_stream(new_ms)
                    except AudioDeviceError:
                        log.exception("เปิด stream ใหม่หลัง underrun ไม่ได้")

    # ------------------------------------------------------------------
    # คำสั่ง (ใส่คิว — callback ทำตามที่ต้น block ถัดไป)
    # ------------------------------------------------------------------
    def load(self, deck_id: int, video_id: str, program: list[Segment]) -> None:
        """โหลดเพลงลง deck (ยังไม่เล่น)"""
        self._commands.append(("load", (deck_id, video_id, program)))

    def play(self, deck_id: int, at_frame: int | None = None) -> None:
        """เริ่มเล่นทันที หรือ ณ เวลา engine at_frame (แม่นระดับ sample — ใช้ตอนมิกซ์)"""
        self._commands.append(("play", (deck_id, at_frame)))

    def pause(self, deck_id: int) -> None:
        self._commands.append(("pause", deck_id))

    def seek(self, deck_id: int, media_time_s: float) -> None:
        """กระโดดไปเวลาเพลง (fade สั้น 5ms กันคลิก) generation ของนาฬิกา +1"""
        self._commands.append(("seek", (deck_id, media_time_s)))

    def set_lanes(self, deck_id: int, lanes: list[AutomationLane]) -> None:
        """ติดตั้ง automation ที่คำนวณไว้ล่วงหน้า (แทนที่ lane เดิมของพารามิเตอร์เดียวกัน)"""
        self._commands.append(("lanes", (deck_id, lanes)))

    def clear_deck(self, deck_id: int) -> None:
        """ล้าง deck หลังมิกซ์จบ (รอเพลงถัดไป)"""
        self._commands.append(("clear", deck_id))

    def set_master_volume(self, volume: float) -> None:
        """ระดับเสียงรวม (ramp 20ms กันคลิก)"""
        self._commands.append(("volume", float(volume)))

    def render(self, frames: int) -> np.ndarray:
        """เรนเดอร์ N frame ออกมาเป็น array ใหม่ (ใช้ใน test/offline — ห้ามเรียกจาก callback)"""
        out = np.zeros((frames, CHANNELS), dtype=np.float32)
        self._callback(out, frames, None, None)
        return out

    # ------------------------------------------------------------------
    # ตัวช่วยใน callback (ทุกตัวเคารพกฎเหล็ก: ไม่ lock, ไม่ I/O, ไม่จอง array)
    # ------------------------------------------------------------------
    def _apply_ramp(self, block: np.ndarray, n: int, g0: float, g1: float) -> None:
        """คูณ block[:n] ด้วย gain ที่ไล่เส้นตรง g0 -> g1 (in-place)"""
        ramp = self._ramp[:n]
        np.multiply(self._idx[:n], (g1 - g0) / n, out=ramp)
        np.add(ramp, g0, out=ramp)
        np.multiply(block[:n], ramp, out=block[:n])

    def _drain_commands(self) -> None:
        cmds = self._commands
        while True:
            try:
                name, arg = cmds.popleft()
            except IndexError:
                return
            try:
                self._handle(name, arg)
            except Exception as e:  # noqa: BLE001 — คำสั่งเสียหนึ่งคำสั่งต้องไม่ล้ม callback ทั้งอัน
                self.stats.callback_errors += 1
                self.stats.last_error = f"command {name}: {e!r}"

    def _handle(self, name: str, arg: Any) -> None:
        if name == "volume":
            self._vol_target = max(0.0, arg)
            self._vol_left = max(1, int(self._sr * VOLUME_RAMP_S))
            self._vol_step = (self._vol_target - self._vol) / self._vol_left
            return
        deck_id = arg[0] if isinstance(arg, tuple) else arg
        d = self.decks[deck_id]
        rt = self._rt[deck_id]
        if name == "load":
            _, video_id, program = arg
            d.video_id = video_id
            d.program = program
            d.seg_index = 0
            d.seg_pos = 0
            d.generation += 1
            d.lanes.clear()
            d.static.clear()
            d.state = DeckState.READY if program else DeckState.EMPTY
            rt.reset()
        elif name == "clear":
            d.video_id = None
            d.program = []
            d.seg_index = 0
            d.seg_pos = 0
            d.generation += 1
            d.lanes.clear()
            d.static.clear()
            d.state = DeckState.EMPTY
            rt.reset()
        elif name == "play":
            self._cmd_play(d, rt, arg[1])
        elif name == "pause":
            rt.play_at = -1
            if d.state is DeckState.PLAYING:
                rt.target = 0.0
                rt.resume = False
        elif name == "seek":
            self._cmd_seek(d, rt, arg[1])
        elif name == "lanes":
            for lane in arg[1]:
                d.lanes[lane.param] = lane

    def _cmd_play(self, d: Deck, rt: _DeckRuntime, at_frame: int | None) -> None:
        if not d.program or d.state is DeckState.EMPTY:
            return
        if d.state is DeckState.PLAYING:
            # กำลังเล่น/กำลัง fade-out เพราะ pause: ยกเลิกการหยุด (ถ้ารอ seek อยู่ ให้เล่นต่อหลัง seek)
            if rt.seek_pending:
                rt.resume = True
            else:
                rt.target = 1.0
            return
        if d.state is DeckState.ENDED:
            self._jump(d, rt, 0.0, -1)  # เล่นซ้ำจากต้นโปรแกรม
        if at_frame is not None and at_frame > self.frames_rendered:
            rt.play_at = int(at_frame)  # นัดเริ่ม ณ sample ที่กำหนด (เริ่มกลาง block ได้)
            return
        rt.play_at = -1
        rt.target = 1.0
        d.state = DeckState.PLAYING
        rt.anchor_off = 0
        rt.anchor_pos = d.media_position()

    def _cmd_seek(self, d: Deck, rt: _DeckRuntime, t: float) -> None:
        if not d.program:
            return
        if d.state is DeckState.PLAYING:
            # กำลังเล่น: fade-out ~5ms ก่อนกระโดด แล้ว fade-in (ทำใน _render_deck)
            rt.seek_pending = True
            rt.seek_s = t
            rt.target = 0.0
            rt.resume = True
        else:
            self._jump(d, rt, t, -1)
            if d.state is DeckState.ENDED:
                d.state = DeckState.PAUSED

    def _jump(self, d: Deck, rt: _DeckRuntime, t: float, offset: int) -> None:
        """ย้ายตำแหน่งไปเวลาเพลง t (วินาที) + generation +1; offset = ตำแหน่งใน block (-1 = ต้น block)"""
        prog = d.program
        if prog:
            sr = prog[0].buffer.sample_rate
            placed = False
            for i, seg in enumerate(prog):
                length = seg.src_end - seg.src_start
                if length <= 0:
                    continue
                rate = seg.media_rate if seg.media_rate > 0 else 1.0
                if t < seg.media_start_s + (length / sr) * rate:
                    pos = int(round(max(0.0, t - seg.media_start_s) / rate * sr))
                    d.seg_index = i
                    d.seg_pos = min(max(pos, 0), length)
                    placed = True
                    break
            if not placed:  # เลยจุดจบโปรแกรม
                d.seg_index = len(prog) - 1
                d.seg_pos = max(0, prog[-1].src_end - prog[-1].src_start)
        d.generation += 1
        if offset >= 0:
            rt.anchor_off = offset
            rt.anchor_pos = d.media_position()

    def _copy(self, d: Deck, rt: _DeckRuntime, out: np.ndarray, a: int, n: int) -> int:
        """ก็อป PCM n frame จาก program เข้า out[a:] คืนจำนวนที่ก็อปได้ (ตั้ง rt.status เมื่อไม่ครบ)

        ไม่เดินเลย frames_ready (starve = เงียบ + ไม่ขยับตำแหน่ง) และจบโปรแกรม = _ENDED
        """
        prog = d.program
        copied = 0
        rt.status = _OK
        while copied < n:
            seg = prog[d.seg_index]
            buf = seg.buffer
            end = seg.src_end
            if buf.complete and buf.total_frames < end:
                end = buf.total_frames  # decoder ได้เฟรมน้อยกว่าที่ประเมินไว้
            src = seg.src_start + d.seg_pos
            left = end - src
            if left <= 0:
                if d.seg_index + 1 < len(prog):
                    d.seg_index += 1
                    d.seg_pos = 0
                    continue
                rt.status = _ENDED
                break
            avail = buf.frames_ready - src
            if avail <= 0:
                rt.status = _STARVED
                break
            k = min(n - copied, left, avail)
            out[a + copied:a + copied + k] = buf.data[src:src + k]
            d.seg_pos += k
            copied += k
        else:
            # ก็อปครบพอดี: ถ้าถึงปลายเซกเมนต์สุดท้ายพอดี ให้จบทันที (ไม่ต้องรอ block ถัดไป)
            seg = prog[d.seg_index]
            end = seg.src_end
            if seg.buffer.complete and seg.buffer.total_frames < end:
                end = seg.buffer.total_frames
            if d.seg_index + 1 >= len(prog) and seg.src_start + d.seg_pos >= end:
                rt.status = _ENDED
        return copied

    def _render_deck(self, d: Deck, rt: _DeckRuntime, buf: np.ndarray, n: int, t0: int, base: int) -> None:
        """เรนเดอร์ deck หนึ่ง n frame (t0 = เวลา engine ของ sample แรก, base = ตำแหน่งของ chunk ใน callback)"""
        pos = 0
        fade = self._fade_frames
        while pos < n:
            if d.state is not DeckState.PLAYING:
                if rt.play_at >= 0:
                    wait = rt.play_at - (t0 + pos)
                    if wait > 0:
                        pos += min(wait, n - pos)  # ยังไม่ถึงเวลานัด: เงียบ
                        continue
                    # ถึงเวลานัด ณ sample นี้พอดี
                    rt.play_at = -1
                    rt.target = 1.0
                    d.state = DeckState.PLAYING
                    rt.anchor_off = base + pos
                    rt.anchor_pos = d.media_position()
                    continue
                return
            span = n - pos
            g, tgt = rt.gain, rt.target
            need = 0
            if g != tgt:
                need = max(1, ceil(abs(tgt - g) * fade))
                span = min(span, need)
            copied = self._copy(d, rt, buf[pos:], 0, span)
            if copied > 0:
                rt.played = True
                if g != tgt:
                    if copied >= need:
                        g1 = tgt
                    else:
                        g1 = g + (copied / fade if tgt > g else -copied / fade)
                    self._apply_ramp(buf[pos:], copied, g, g1)
                    rt.gain = g1
                elif g != 1.0:
                    np.multiply(buf[pos:pos + copied], g, out=buf[pos:pos + copied])
            pos += copied
            if rt.status == _ENDED:
                d.state = DeckState.ENDED
                return
            if copied < span:  # starve: เงียบที่เหลือ ตำแหน่งไม่ขยับ
                if not rt.starved:
                    rt.starved = True
                    self.stats.starvations += 1
                return
            if rt.gain <= 0.0 and rt.target <= 0.0:  # fade-out เสร็จ
                if rt.seek_pending:
                    rt.seek_pending = False
                    self._jump(d, rt, rt.seek_s, base + pos)
                if rt.resume:
                    rt.target = 1.0
                    rt.resume = False
                    rt.anchor_off = base + pos
                    rt.anchor_pos = d.media_position()
                else:
                    d.state = DeckState.PAUSED
                    return

    def _render_chunk(self, out: np.ndarray, n: int, t0: int, base: int) -> None:
        """mix 2 deck -> master volume -> limiter ลง out (n <= MAX_BLOCK)"""
        out.fill(0.0)
        for i in (0, 1):
            d = self.decks[i]
            rt = self._rt[i]
            if d.state is not DeckState.PLAYING and rt.play_at < 0:
                continue
            dbuf = self._dbuf[:n]
            dbuf.fill(0.0)
            self._render_deck(d, rt, dbuf, n, t0, base)
            lane = d.lanes.get(Param.GAIN)
            if lane is not None:
                a0 = lane.value_at(t0)
                a1 = lane.value_at(t0 + n)
                if a0 != 1.0 or a1 != 1.0:
                    self._apply_ramp(dbuf, n, a0, a1)
            else:
                sg = d.static.get(Param.GAIN, 1.0)
                if sg != 1.0:
                    np.multiply(dbuf, sg, out=dbuf)
            np.add(out, dbuf, out=out)
        # master volume (ramp 20ms)
        if self._vol_left > 0:
            m = min(n, self._vol_left)
            v0 = self._vol
            v1 = self._vol_target if m == self._vol_left else v0 + self._vol_step * m
            self._apply_ramp(out, m, v0, v1)
            if m < n and v1 != 1.0:
                np.multiply(out[m:n], v1, out=out[m:n])
            self._vol = v1
            self._vol_left -= m
        elif self._vol != 1.0:
            np.multiply(out, self._vol, out=out)
        self._limiter.process(out)

    # ------------------------------------------------------------------
    # callback (ดูกฎด้านบน)
    # ------------------------------------------------------------------
    def _callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """mix 2 deck -> master gain -> limiter -> outdata  (เฟส 1: deck เดียว, เฟส 5: 2 deck)

        ลำดับในแต่ละ block:
          1. ทำคำสั่งที่ค้างใน deque
          2. ต่อ deck: ก็อป PCM ตาม program -> automation (gain ramp ต่อ sample, EQ/filter ต่อ block)
          3. รวมสอง deck -> master volume -> limiter
          4. publish นาฬิกาของแต่ละ deck: host_time = perf_counter() + output latency
          5. frames_rendered += frames
        """
        t_start = time.perf_counter()
        stats = self.stats
        t0 = self.frames_rendered
        try:
            if status is not None and status.output_underflow:
                stats.underruns += 1
            self._drain_commands()
            rts = self._rt
            for i in (0, 1):
                rt = rts[i]
                rt.pub_pos = self.decks[i].media_position()
                rt.played = False
                rt.starved = False
            # (rt.anchor_off ที่ตั้งจากคำสั่ง play เมื่อกี้คือ offset 0 — คงไว้ ไม่ล้าง)
            done = 0
            while done < frames:
                n = min(MAX_BLOCK, frames - done)
                self._render_chunk(outdata[done:done + n], n, t0 + done, done)
                done += n
            stats.limiter_gain_reduction_db = self._limiter.gain_reduction_db
            host_time = t_start + self._latency_s
            sr = self._sr
            for i in (0, 1):
                d = self.decks[i]
                rt = rts[i]
                if d.program:
                    seg = d.program[min(d.seg_index, len(d.program) - 1)]
                    rate = seg.media_rate
                else:
                    rate = 1.0
                pos = rt.pub_pos
                if rt.anchor_off >= 0:
                    pos = rt.anchor_pos - (rt.anchor_off / sr) * rate
                    rt.anchor_off = -1
                playing = d.state is DeckState.PLAYING and rt.played
                self.clocks[i].publish(pos, host_time, rate, playing, d.generation)
        except Exception as e:  # noqa: BLE001 — กฎข้อ 4: ความเงียบ + นับ error
            outdata.fill(0.0)
            stats.callback_errors += 1
            stats.last_error = repr(e)
        finally:
            self.frames_rendered = t0 + frames
            stats.callbacks += 1
            ms = (time.perf_counter() - t_start) * 1000.0
            if ms > stats.max_callback_ms:
                stats.max_callback_ms = ms


@dataclass(slots=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    default_samplerate: float
    is_default: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def list_output_devices() -> list[DeviceInfo]:
    """รายชื่ออุปกรณ์เสียงขาออก (ทุก host API; is_default = ค่าเริ่มต้นของ WASAPI/ระบบ) — error คืน []"""
    try:
        import sounddevice as sd

        apis = sd.query_hostapis()
        default_idx = -1
        for api in apis:
            if "WASAPI" in str(api.get("name", "")):
                default_idx = int(api.get("default_output_device", -1))
        if default_idx < 0:
            default_idx = int(sd.default.device[1])
        result: list[DeviceInfo] = []
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev["max_output_channels"]) <= 0:
                continue
            result.append(DeviceInfo(
                index=idx,
                name=str(dev["name"]),
                hostapi=str(apis[int(dev["hostapi"])]["name"]),
                default_samplerate=float(dev["default_samplerate"]),
                is_default=(idx == default_idx),
                extra={"max_output_channels": int(dev["max_output_channels"])},
            ))
        return result
    except Exception:  # noqa: BLE001 — ไม่มี PortAudio/ไม่มีอุปกรณ์ -> ว่าง
        return []
