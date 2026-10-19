"""PlayerController — ขั้นตอนตั้งแต่กดเล่นจนเสียงออกและเนื้อเพลงขึ้น (ARCHITECTURE.md §2)

play(track) (โหมดแอป):
  t=0     เปิดดู cache ใน DB (มี PCM ครบ = เล่นทันที)
  ขนาน:   [IO] yt-dlp: extract ครั้งเดียว -> ข้อมูลวิดีโอ -> (ระหว่างนั้นเริ่มงานอื่น) -> โหลดเสียง
          [IO] LyricsService.find -> เวลาแบบประมาณ -> LYRICS_READY  (ผลชั่วคราวส่งทันทีที่แหล่งแรกตอบ)
          [IO] ปกเพลง (iTunes -> thumbnail) -> TRACK_META_READY
  ~2 วิ   Decoder ถอดรหัสทยอยลง memmap  PCM พอ ~2 วิ -> engine.load + play (เป้า: เริ่มภายใน 3 วิ)
  ต่อไป   (เฟส 4) AI ช่วงแรก 20-30 วิ ฯลฯ  /  (เฟส 5) Preloader เตรียมเพลงถัดไป

ตัวเล่นห้ามรอ AI เด็ดขาด — ช่วงที่ AI ยังไม่เสร็จใช้เวลาแบบประมาณ
เฟส 1: deck เดียว (deck 0) ไม่มีคิว  เปลี่ยนเพลง = เพลงเก่าเล่นต่อจนเพลงใหม่พร้อมแล้วค่อยสลับ

เธรด: เมธอดสาธารณะเรียกได้จากทุก thread (UI) — งานจริงทำใน IoThread ทั้งหมด
ความล้มเหลว: ทุกขั้นห่อด้วย try/except แล้วส่ง ERROR ที่มีข้อความภาษาไทย เสียงที่เล่นอยู่ไม่ถูกแตะ
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from pathlib import Path
from typing import Any

from app.audio.deck import DeckState, full_program
from app.core import db as dbmod
from app.core import events as ev
from app.core.errors import MediaError, SyncLyricsError
from app.core.log import get_logger
from app.core.models import TrackRef
from app.media import cache as audio_cache
from app.player.state import SAVE_INTERVAL_S, save_state

log = get_logger("player")
# PCM ที่ต้องมีก่อนเริ่มเล่น (วินาที) — decoder เร็วกว่าเล่นจริงหลายสิบเท่า จึงเริ่มได้เกือบทันที
START_BUFFER_S = 2.0
START_TIMEOUT_S = 15.0
EVENT_POLL_S = 0.5


class PlayerController:
    """เฟส 1 (deck เดียว) -> เฟส 5 (2 deck + preload) -> เฟส 6 (AutoMix)

    พารามิเตอร์:
      db   = Path ของไฟล์ SQLite (controller เปิด connection แยกต่อ thread เอง)
      ai   = ยังไม่ใช้ในเฟส 1 (ส่ง None ได้)
      io   = IoThread ที่รันอยู่แล้ว
    """

    def __init__(self, engine: Any, bus: Any, lyrics: Any, media: Any, ai: Any, db: Path | str,
                 settings: Any, paths: Any = None, io: Any = None) -> None:
        self.engine = engine
        self.bus = bus
        self.lyrics = lyrics
        self.media = media
        self.ai = ai
        self.db_path = db
        self.settings = settings
        self.paths = paths
        self.io = io
        self.active_deck = 0

        self._lock = threading.RLock()
        self._local = threading.local()
        self._token = 0
        self._future: concurrent.futures.Future[Any] | None = None
        self._decoder: Any = None
        self.track: TrackRef | None = None
        self.duration: float = 0.0
        self.loaded = False
        self.playing = False
        self.lyrics_offset = 0.0
        self._ticker: concurrent.futures.Future[Any] | None = None

    # ------------------------------------------------------------------
    # ตัวช่วย
    # ------------------------------------------------------------------
    def _conn(self) -> Any:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = dbmod.connect(self.db_path)
            self._local.conn = conn
        return conn

    def get_clock(self) -> Any:
        """นาฬิกาของ deck ที่กำลังเล่น — UI เรียกทุกเฟรม"""
        return self.engine.clocks[self.active_deck]

    def _status(self, text: str) -> None:
        self.bus.publish(ev.PLAYER_STATUS, {"text": text})

    def _error(self, e: Exception, module: str = "player") -> None:
        if isinstance(e, SyncLyricsError):
            user = e.user_message + (f" — {e.hint}" if e.hint else "")
            log.warning("เล่นไม่สำเร็จ", extra={"data": {"err": str(e)}})
        else:
            user = "เกิดข้อผิดพลาดที่ไม่คาดคิด (ดูรายละเอียดใน log)"
            log.exception("เล่นไม่สำเร็จ")
        self.bus.publish(ev.ERROR, {"module": module, "message": str(e), "user_message": user,
                                    "recoverable": True})

    # ------------------------------------------------------------------
    # คำสั่งจาก UI / ส่วนขยาย (thread ใดก็ได้)
    # ------------------------------------------------------------------
    def play_url(self, text: str) -> None:
        """วางลิงก์ YouTube (Ctrl+V / ช่องกรอก) แล้วเล่น"""
        from app.media.youtube import parse_video_id

        vid = parse_video_id(text)
        if not vid:
            self._error(MediaError("player", "ลิงก์นี้ไม่ใช่ลิงก์ YouTube", hint="วางลิงก์วิดีโอหรือ videoId"))
            return
        self.play(TrackRef(video_id=vid, added_from="paste"))

    def play(self, track: TrackRef, start_at: float = 0.0, autoplay: bool = True) -> None:
        """เริ่มเล่นเพลงใหม่ (ยกเลิกงานของเพลงก่อนหน้า)"""
        with self._lock:
            self._token += 1
            token = self._token
            self._cancel_current()
            self.track = track
            self.duration = track.duration or 0.0
            self.loaded = False
            self.lyrics_offset = 0.0
            self._future = self.io.submit(self._play_async(track, start_at, autoplay, token))

    def _cancel_current(self) -> None:
        if self._future is not None:
            self._future.cancel()
            self._future = None
        if self._decoder is not None:
            try:
                self._decoder.cancel()
            except Exception:
                log.exception("ยกเลิก decoder ไม่สำเร็จ")
            self._decoder = None

    def toggle_pause(self) -> None:
        if not self.loaded:
            return
        if self.playing:
            self.engine.pause(self.active_deck)
        else:
            self.engine.play(self.active_deck)
        self.playing = not self.playing
        self._publish_playback()

    def seek(self, position_s: float) -> None:
        if not self.loaded:
            return
        top = self.duration if self.duration > 0 else position_s
        self.engine.seek(self.active_deck, max(0.0, min(position_s, max(top - 0.05, 0.0))))

    def set_volume(self, volume: float) -> None:
        self.engine.set_master_volume(max(0.0, min(1.0, float(volume))))

    def adjust_offset(self, delta_s: float) -> None:
        """[ / ] ปรับ offset เนื้อเพลงทีละ 0.1 วิ (บวก = เนื้อเพลงช้าลง) จำตาม videoId"""
        if self.track is None:
            return
        self.lyrics_offset = round(self.lyrics_offset + delta_s, 2)
        try:
            self._conn().execute("UPDATE tracks SET lyrics_offset_s=? WHERE video_id=?",
                                 (self.lyrics_offset, self.track.video_id))
        except Exception:
            log.exception("บันทึก offset ไม่สำเร็จ")
        self.bus.publish(ev.LYRICS_OFFSET, {"video_id": self.track.video_id, "offset": self.lyrics_offset})

    def next_lyrics_candidate(self) -> None:
        """ปุ่ม "ผลถัดไป": สลับไปเนื้อเพลงอันดับถัดไปของเพลงนี้"""
        if self.track is None:
            return
        vid = self.track.video_id

        async def run() -> None:
            try:
                res = await self.lyrics.next_candidate(vid)
                if self.track is not None and self.track.video_id == vid:
                    self._emit_lyrics(vid, res)
            except Exception as e:
                self._error(e, "lyrics")

        self.io.submit(run())

    def skip_next(self) -> None:
        raise NotImplementedError("เฟส 5")

    def skip_mix(self) -> None:
        """ปุ่ม "ข้ามการมิกซ์": ตัดไปเพลง B ทันทีแบบสั้น (รางวัล -0.8)"""
        raise NotImplementedError("เฟส 6")

    # ------------------------------------------------------------------
    # กู้สถานะ / บันทึกสถานะ (ข้อ 11.2)
    # ------------------------------------------------------------------
    def restore(self, state: dict[str, Any]) -> bool:
        """เปิดโปรแกรมใหม่: กลับไปเพลงเดิมตำแหน่งเดิม (หยุดไว้ ยังไม่เล่นจนกว่าผู้ใช้กด)"""
        try:
            ref = state.get("track_ref")
            if not ref:
                return False
            track = TrackRef(**{k: v for k, v in ref.items() if k in TrackRef.__dataclass_fields__})
            self.play(track, start_at=float(state.get("position_s") or 0.0), autoplay=False)
            return True
        except Exception:
            log.exception("กู้สถานะไม่สำเร็จ")
            return False

    def snapshot(self) -> dict[str, Any]:
        pos = 0.0
        try:
            pos = float(self.get_clock().position())
        except Exception:
            pass
        return {
            "video_id": self.track.video_id if self.track else None,
            "track_ref": self.track.to_dict() if self.track else None,
            "position_s": round(pos, 2), "playing": self.playing, "mode": "app",
        }

    def start_background_tasks(self) -> None:
        """งานคาบเวลาใน IO thread: บันทึกสถานะทุก 5 วิ และเฝ้าดูว่าเพลงจบหรือยัง"""
        if self._ticker is None:
            self._ticker = self.io.submit(self._ticker_loop())

    async def _ticker_loop(self) -> None:
        last_save = 0.0
        while True:
            await asyncio.sleep(EVENT_POLL_S)
            try:
                if self.loaded and self.playing and self.engine.decks[self.active_deck].state == DeckState.ENDED:
                    self.playing = False
                    self._publish_playback()
                now = time.monotonic()
                if self.paths is not None and now - last_save >= SAVE_INTERVAL_S and self.track is not None:
                    last_save = now
                    await asyncio.to_thread(save_state, self.paths.state_file, self.snapshot())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ticker พัง")

    def shutdown(self) -> None:
        """ปิดโปรแกรม: ยกเลิกงาน บันทึกสถานะสุดท้าย"""
        with self._lock:
            self._token += 1
            self._cancel_current()
        if self._ticker is not None:
            self._ticker.cancel()
        if self.paths is not None and self.track is not None:
            try:
                save_state(self.paths.state_file, self.snapshot())
            except Exception:
                log.exception("บันทึกสถานะสุดท้ายไม่สำเร็จ")

    # ------------------------------------------------------------------
    # งานหลักของการเล่น (รันใน IO thread)
    # ------------------------------------------------------------------
    def _publish_playback(self) -> None:
        self.bus.publish(ev.PLAYBACK_STATE, {
            "playing": self.playing, "video_id": self.track.video_id if self.track else None})

    def _emit_lyrics(self, video_id: str, res: Any) -> None:
        self.bus.publish(ev.LYRICS_READY, {
            "video_id": video_id, "lyrics": res.chosen, "source_label": res.source_label,
            "candidates_count": len(res.candidates), "final": getattr(res, "final", True),
            "needs_ai_transcription": getattr(res, "needs_ai_transcription", False),
        })

    def _audio_dir(self) -> Path:
        return self.paths.audio_cache_dir

    def _load_offset(self, video_id: str) -> float:
        try:
            row = self._conn().execute("SELECT lyrics_offset_s FROM tracks WHERE video_id=?", (video_id,)).fetchone()
            return float(row["lyrics_offset_s"]) if row else 0.0
        except Exception:
            return 0.0

    def _ensure_track(self, track: TrackRef) -> None:
        """ให้มีแถวใน tracks เสมอ (audio_cache / offset / เนื้อเพลง อ้างอิงด้วย foreign key)"""
        self._conn().execute(
            "INSERT INTO tracks(video_id, yt_title, channel, duration_s, first_seen_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(video_id) DO UPDATE SET yt_title=CASE WHEN excluded.yt_title<>'' THEN excluded.yt_title "
            "ELSE yt_title END, channel=CASE WHEN excluded.channel<>'' THEN excluded.channel ELSE channel END, "
            "duration_s=COALESCE(excluded.duration_s, duration_s), last_played_at=?, play_count=play_count+0",
            (track.video_id, track.title, track.channel, track.duration or None, time.time(), time.time()),
        )

    def _track_from_db(self, track: TrackRef) -> TrackRef:
        """ผู้ใช้วางแค่ลิงก์ = ไม่มีชื่อ: ถ้าเคยเล่นแล้วดึงข้อมูลจาก DB (เล่นจาก cache ได้โดยไม่ต้องเรียก yt-dlp)"""
        if track.title:
            return track
        row = self._conn().execute(
            "SELECT yt_title, channel, duration_s, music_section FROM tracks WHERE video_id=?", (track.video_id,)
        ).fetchone()
        if row and row["yt_title"]:
            import json

            return TrackRef(video_id=track.video_id, title=row["yt_title"], channel=row["channel"],
                            duration=row["duration_s"], added_from=track.added_from,
                            music_section=json.loads(row["music_section"] or "{}"))
        return track

    def _open_cached_pcm(self, video_id: str) -> Any:
        """PCM ที่ถอดรหัสครบแล้วใน cache (sample rate ต้องตรงกับ engine) หรือ None"""
        from app.audio.decoder import open_cached

        row = self._conn().execute(
            "SELECT path, sample_rate, complete FROM audio_cache WHERE video_id=?", (video_id,)).fetchone()
        if not row or not row["complete"] or row["sample_rate"] != self.engine.sample_rate:
            return None
        buf = open_cached(self._audio_dir() / f"{video_id}.f32", self.engine.sample_rate)
        if buf is not None:
            audio_cache.touch(self._conn(), video_id)
        return buf

    def _start_engine(self, video_id: str, buf: Any, start_at: float, autoplay: bool) -> None:
        self.engine.load(self.active_deck, video_id, full_program(buf))
        if start_at > 0:
            self.engine.seek(self.active_deck, start_at)
        if autoplay:
            self.engine.play(self.active_deck)
        self.loaded = True
        self.playing = autoplay
        self._publish_playback()

    async def _play_async(self, track: TrackRef, start_at: float, autoplay: bool, token: int) -> None:
        t0 = time.perf_counter()
        vid = track.video_id
        alive = lambda: token == self._token  # noqa: E731
        decoder: Any = None
        try:
            self.bus.publish(ev.TRACK_CHANGED, {"video_id": vid, "track_ref": track, "deck": self.active_deck})
            self._status("กำลังเตรียมเพลง...")
            track = await asyncio.to_thread(self._track_from_db, track)
            cached = await asyncio.to_thread(self._open_cached_pcm, vid)
            if cached is not None and alive():
                self.track = track
                await asyncio.to_thread(self._ensure_track, track)
                self.duration = track.duration or cached.total_frames / cached.sample_rate
                self._start_engine(vid, cached, start_at, autoplay)
                self._status("")
                log.info("เล่นจาก cache", extra={"data": {"video_id": vid, "ms": round((time.perf_counter() - t0) * 1000)}})
                await self._side_tasks(track, None, token)
                return

            # ----- ไม่มีใน cache: โหลดจาก YouTube -----
            loop = asyncio.get_running_loop()
            info_fut: asyncio.Future[Any] = loop.create_future()

            def on_info(vi: Any) -> None:
                loop.call_soon_threadsafe(lambda: info_fut.done() or info_fut.set_result(vi))

            last_pct = [-10]

            def on_progress(frac: float) -> None:
                pct = int(frac * 100)
                if pct - last_pct[0] >= 10 or pct == 100:  # ไม่ส่งถี่เกินไป
                    last_pct[0] = pct
                    self._status(f"กำลังโหลดเสียง {pct}%")

            self._status("กำลังดึงข้อมูลจาก YouTube...")
            dl_task = asyncio.create_task(asyncio.to_thread(
                self.media.fetch_and_download, vid, self._audio_dir(), on_info, on_progress))
            # ถ้าดึงข้อมูลพังก่อนมี info ให้ error ออกมาจาก dl_task
            done, _ = await asyncio.wait({info_fut, dl_task}, return_when=asyncio.FIRST_COMPLETED)
            if not info_fut.done():
                await dl_task  # โยน exception ออกมา
            vi = info_fut.result()
            if not alive():
                return
            track = vi.track if not track.title else self._merge_track(track, vi.track)
            self.track = track
            self.duration = vi.duration or track.duration or 0.0
            await asyncio.to_thread(self._ensure_track, track)
            side = asyncio.create_task(self._side_tasks(track, vi, token))

            dl_info, dl = await dl_task
            if not alive():
                side.cancel()
                return
            self._status("กำลังถอดรหัสเสียง...")
            from app.audio.decoder import DecodeJob, Decoder

            decoder = Decoder(DecodeJob(source=dl.path, target=self._audio_dir() / f"{vid}.f32",
                                        sample_rate=self.engine.sample_rate, duration_s=self.duration))
            with self._lock:
                if not alive():
                    side.cancel()
                    return
                self._decoder = decoder
            buf = decoder.start()
            ok = await asyncio.to_thread(decoder.wait_for_frames, int(START_BUFFER_S * self.engine.sample_rate),
                                         START_TIMEOUT_S)
            if not alive():
                decoder.cancel()
                side.cancel()
                return
            if not ok:
                raise MediaError("media", "ถอดรหัสเสียงไม่สำเร็จ", hint=getattr(decoder, "error", None) or "ตรวจว่ามี ffmpeg")
            self._start_engine(vid, buf, start_at, autoplay)
            self._status("")
            log.info("เริ่มเล่น", extra={"data": {"video_id": vid, "ms": round((time.perf_counter() - t0) * 1000),
                                                  "format": dl.audio_format, "cookies": dl.cookie_mode}})
            await asyncio.to_thread(self._finish_decode, decoder, vid, dl, token)
            await side
        except asyncio.CancelledError:
            if decoder is not None:
                decoder.cancel()
            raise
        except Exception as e:
            if alive():
                self._status("")
                self._error(e)

    @staticmethod
    def _merge_track(given: TrackRef, fetched: TrackRef) -> TrackRef:
        """ข้อมูลที่ส่วนขยายส่งมา (เช่น ส่วน "Music") สำคัญกว่า แต่เติมช่องที่ว่างจาก yt-dlp"""
        merged = TrackRef(**given.to_dict())
        merged.channel = merged.channel or fetched.channel
        merged.duration = merged.duration or fetched.duration
        merged.ytdlp_meta = fetched.ytdlp_meta or merged.ytdlp_meta
        merged.thumbnail_url = merged.thumbnail_url or fetched.thumbnail_url
        return merged

    def _finish_decode(self, decoder: Any, vid: str, dl: Any, token: int) -> None:
        """รอถอดรหัสจนจบ (thread ของ executor) -> ลงทะเบียน cache -> ลบไฟล์ดิบ -> จำกัดขนาด"""
        decoder.finished.wait()
        if token != self._token or getattr(decoder, "error", None):
            return
        buf = decoder.buffer
        conn = self._conn()
        try:
            audio_cache.register(conn, vid, buf.path, self._audio_dir(), buf.sample_rate,
                                 buf.total_frames, dl.audio_format, buf.complete)
            try:
                dl.path.unlink()
            except OSError:
                pass
            audio_cache.enforce_limit(conn, self._audio_dir(), self.settings.playback.cache_max_gb, protect=[vid])
        except Exception:
            log.exception("ลงทะเบียน cache ไม่สำเร็จ")

    async def _side_tasks(self, track: TrackRef, info: Any, token: int) -> None:
        """เนื้อเพลง แล้วต่อด้วยปก (ปกต้องรู้ชื่อเพลง/ศิลปินที่ยืนยันจากผลเนื้อเพลงก่อน) ขนานกับการโหลดเสียง"""
        try:
            meta = await self._lyrics_flow(track, info, token)
            if token == self._token:
                await self._artwork_flow(track, meta, token)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("งานเสริมพัง", extra={"data": {"err": repr(e)}})

    async def _lyrics_flow(self, track: TrackRef, info: Any, token: int) -> Any:
        vid = track.video_id
        self.lyrics_offset = await asyncio.to_thread(self._load_offset, vid)
        self.bus.publish(ev.LYRICS_OFFSET, {"video_id": vid, "offset": self.lyrics_offset})
        extras = {"subtitles": info.subtitles} if info is not None else {}

        def on_update(res: Any) -> None:
            if token == self._token:
                self._emit_lyrics(vid, res)

        try:
            res = await self.lyrics.find(track, track.duration or self.duration or None, extras, on_update)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._error(e, "lyrics")
            return None
        if token == self._token:
            self._emit_lyrics(vid, res)
            return res.meta
        return None

    async def _artwork_flow(self, track: TrackRef, meta: Any, token: int) -> None:
        from app.lyrics.title_parser import parse_track
        from app.media.artwork import fetch_artwork

        meta = meta or parse_track(track)
        self.bus.publish(ev.TRACK_META_READY, {"video_id": track.video_id, "meta": meta, "cover_path": None,
                                               "palette": []})
        try:
            art = await fetch_artwork(track, meta, self.paths.art_cache_dir)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("หาปกไม่สำเร็จ")
            return
        if art is not None and token == self._token:
            self.bus.publish(ev.TRACK_META_READY, {"video_id": track.video_id, "meta": meta,
                                                   "cover_path": str(art.path), "palette": art.palette})
