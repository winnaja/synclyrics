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
from app.core.clock import RemoteClock
from app.core.models import TrackRef
from app.media import cache as audio_cache
from app.player.queue import PlayQueue
from app.player.state import SAVE_INTERVAL_S, save_state

log = get_logger("player")
# PCM ที่ต้องมีก่อนเริ่มเล่น (วินาที) — decoder เร็วกว่าเล่นจริงหลายสิบเท่า จึงเริ่มได้เกือบทันที
START_BUFFER_S = 2.0
START_TIMEOUT_S = 15.0
INFO_WAIT_S = 3.0  # โหมดคู่หู: รอ yt-dlp หลังได้ oEmbed แล้วไม่เกินนี้
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
        # เฟส 2: คิว + โหมด (app = โปรแกรมเล่นเสียงเอง, companion = เล่นใน YouTube แล้วโปรแกรมแค่แสดงเนื้อเพลง)
        self.queue = PlayQueue()
        # app_audio=False (ค่าเริ่มต้น): แอปแสดงเนื้อเพลงอย่างเดียว ตามเพลงที่เล่นใน YouTube (โหมดคู่หูโหมดเดียว)
        self.mode = "app" if self._app_audio() else "companion"
        self.remote_clock = RemoteClock()
        self.volume = 1.0   # วอลลุ่มของวิดีโอในแท็บ YouTube (โหมดคู่หู) 0-1
        self.muted = False
        # ผู้ให้บริการควบคุมแท็บ YouTube ในโหมดคู่หู: tab_control(action, data) — BridgeService เป็นคนตั้ง
        self.tab_control: Any = None
        # เฟส 4: ตัวจัดเวลาเนื้อเพลงจากเสียงด้วย AI (LyricsAligner) — main ตั้งให้ · None = ไม่มี AI (ใช้เวลาแบบประมาณ/ของแหล่งล้วน)
        self.aligner: Any = None
        self.emphasizer: Any = None   # LyricsEmphasis (เลือกคำเน้นด้วยโมเดลภาษา) · None = ไม่ใช้
        self.translator: Any = None   # LyricsTranslator (แปลไทยทั้งเพลงด้วย AI) · None = ไม่แปล
        self._mismatch_tries: dict[str, int] = {}

    # ------------------------------------------------------------------
    # ตัวช่วย
    # ------------------------------------------------------------------
    def _app_audio(self) -> bool:
        """เปิดโหมดแอปเล่นเสียงเองไหม (ปิดอยู่เป็นค่าเริ่มต้น — ดู PlaybackSettings.app_audio)"""
        return bool(getattr(getattr(self.settings, "playback", None), "app_audio", False))

    def _conn(self) -> Any:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = dbmod.connect(self.db_path)
            self._local.conn = conn
        return conn

    def get_clock(self) -> Any:
        """นาฬิกาของเพลงที่แสดงอยู่ — UI เรียกทุกเฟรม (โหมดคู่หู = นาฬิกาจากส่วนขยาย)"""
        if self.mode == "companion":
            return self.remote_clock
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

        if not self._app_audio():
            self._status("โปรแกรมนี้แสดงเนื้อเพลงอย่างเดียว — เล่นเพลงใน YouTube แล้วเนื้อเพลงจะขึ้นเอง")
            return
        vid = parse_video_id(text)
        if not vid:
            self._error(MediaError("player", "ลิงก์นี้ไม่ใช่ลิงก์ YouTube", hint="วางลิงก์วิดีโอหรือ videoId"))
            return
        self.play_now(TrackRef(video_id=vid, added_from="paste"))

    def play_now(self, track: TrackRef, start_at: float = 0.0) -> None:
        """"เล่นเลย" จากส่วนขยาย/ลิงก์: เข้าโหมดแอป ใส่เพลงเป็นเพลงปัจจุบันของคิว แล้วเล่น (ปิดเมื่อ app_audio=False)"""
        if not self._app_audio():
            log.info("ข้าม play_now: แอปไม่เล่นเสียงเอง", extra={"data": {"video_id": track.video_id}})
            return
        self.set_mode("app")
        self.queue.play_now(track)
        self._publish_queue()
        self.play(track, start_at=start_at)

    def enqueue(self, tracks: list[TrackRef], position: str = "end") -> int:
        """"เข้าคิว": เพิ่มท้ายคิว (หรือถัดไป) ไม่ขัดเพลงที่เล่นอยู่ — ถ้ายังไม่มีเพลงเลยเริ่มเล่นเพลงแรก"""
        if not self._app_audio():
            return 0
        n = self.queue.add(tracks, position)
        self._publish_queue()
        if n and self.track is None and self.mode == "app":
            first = self.queue.current() or self.queue.next()
            if first is not None:
                self._publish_queue()
                self.play(first)
        return n

    def _publish_queue(self) -> None:
        snap = self.queue.snapshot()
        self.bus.publish(ev.QUEUE_CHANGED, {"items": snap["items"], "index": snap["index"]})

    def set_mode(self, mode: str) -> None:
        """สลับ app/companion · เข้า companion: หยุดเสียงของแอป (YouTube เป็นคนเล่นแทน)"""
        if mode not in ("app", "companion") or mode == self.mode:
            return
        if mode == "app" and not self._app_audio():
            return
        with self._lock:
            if mode == "companion":
                self._token += 1
                self._cancel_current()
                if self.loaded and self.playing:
                    self.engine.pause(self.active_deck)
                self.playing = False
                self.loaded = False
                self.track = None
            self.mode = mode
        self.bus.publish(ev.MODE_CHANGED, {"mode": mode})
        self._publish_playback()

    def play(self, track: TrackRef, start_at: float = 0.0, autoplay: bool = True) -> None:
        """เริ่มเล่นเพลงใหม่ (ยกเลิกงานของเพลงก่อนหน้า)"""
        with self._lock:
            if self.loaded and self.track is not None and self.track.video_id == track.video_id:
                # เพลงเดียวกันที่โหลดอยู่แล้ว (กดลิงก์ซ้ำ/กู้สถานะ): กลับไปตำแหน่งที่ขอ ไม่โหลดใหม่
                # (โหลดใหม่ชนไฟล์ PCM ที่ deck ถืออยู่ — Windows ลบ/เขียนทับไฟล์ที่ memmap อยู่ไม่ได้)
                self.engine.seek(self.active_deck, max(0.0, start_at))
                if autoplay and not self.playing:
                    self.engine.play(self.active_deck)
                elif not autoplay and self.playing:
                    self.engine.pause(self.active_deck)
                self.playing = autoplay
                self._publish_playback()
                return
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

    def _tab(self, action: str, **data: Any) -> None:
        """สั่งแท็บ YouTube ในโหมดคู่หู (play/pause/seek) ผ่านส่วนขยาย"""
        if self.tab_control is not None:
            try:
                self.tab_control(action, data)
            except Exception:
                log.exception("สั่งแท็บ YouTube ไม่สำเร็จ")

    def toggle_pause(self) -> None:
        if self.mode == "companion":
            self._tab("pause" if self.playing else "play")
            return
        if not self.loaded:
            return
        if self.playing:
            self.engine.pause(self.active_deck)
        else:
            self.engine.play(self.active_deck)
        self.playing = not self.playing
        self._publish_playback()

    def seek(self, position_s: float) -> None:
        log.info("กรอเพลง", extra={"data": {"to": round(float(position_s), 2), "mode": self.mode,
                                            "duration": round(float(self.duration or 0.0), 2),
                                            "tab": self.tab_control is not None}})
        if self.mode == "companion":
            self._tab("seek", time=max(0.0, float(position_s)))
            return
        if not self.loaded:
            return
        top = self.duration if self.duration > 0 else position_s
        self.engine.seek(self.active_deck, max(0.0, min(position_s, max(top - 0.05, 0.0))))

    def set_volume(self, volume: float) -> None:
        """ปรับวอลลุ่ม: โหมดคู่หู = สั่งตัวเล่นใน YouTube (แอปไม่เล่นเสียงเอง) · โหมดแอปเดิม = engine"""
        v = max(0.0, min(1.0, float(volume)))
        if self.mode == "companion":
            self._tab("volume", value=v)
            self._set_volume(v, self.muted and v <= 0.0)  # ลากวอลลุ่มขึ้น = เลิกปิดเสียง (ส่วนขยายทำเหมือนกัน)
            return
        self.engine.set_master_volume(v)

    def toggle_mute(self) -> None:
        """ปุ่มลำโพง: ปิด/เปิดเสียงของตัวเล่นใน YouTube"""
        if self.mode != "companion":
            return
        target = not self.muted
        self._tab("mute", value=target)
        self._set_volume(self.volume, target)

    def _set_volume(self, volume: float, muted: bool) -> None:
        if abs(volume - self.volume) < 1e-3 and muted == self.muted:
            return
        self.volume, self.muted = volume, muted
        self.bus.publish(ev.VOLUME_CHANGED, {"volume": volume, "muted": muted})

    def _feedback(self, kind: str, **data: Any) -> None:
        """บันทึกการกระทำของผู้ใช้เป็นสัญญาณ (กด "ตัวอื่น" = ฉบับเดิมไม่ถูกใจ · ปรับเวลา = เวลาไม่ตรง) ถ้าเปิดเก็บข้อมูลสอน"""
        try:
            if self.track is not None and getattr(getattr(self.settings, "ai", None), "collect_data", True):
                from app.core import dataset

                dataset.record_event(kind, self.track.video_id, position_s=round(float(self.remote_clock.position() or 0.0), 2), **data)
        except Exception:  # noqa: BLE001
            pass

    def adjust_offset(self, delta_s: float) -> None:
        """[ / ] ปรับ offset เนื้อเพลงทีละ 0.1 วิ (บวก = เนื้อเพลงช้าลง) จำตาม videoId"""
        if self.track is None:
            return
        self.lyrics_offset = round(self.lyrics_offset + delta_s, 2)
        self._feedback("offset", offset=self.lyrics_offset, delta=delta_s)
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
        self._feedback("next_candidate")

        async def run() -> None:
            try:
                res = await self.lyrics.next_candidate(vid)
                if self.track is not None and self.track.video_id == vid:
                    self._emit_lyrics(vid, res)
            except Exception as e:
                self._error(e, "lyrics")

        self.io.submit(run())

    def skip_next(self) -> None:
        """เพลงถัดไปในคิว (ไม่มี = ไม่ทำอะไร แค่แจ้งสถานะ) · โหมดคู่หู: ให้ YouTube ข้ามเอง"""
        if self.mode == "companion":
            self._tab("next")
            return
        nxt = self.queue.next()
        if nxt is None:
            self._status("ไม่มีเพลงถัดไปในคิว")
            return
        self._publish_queue()
        self.play(nxt)

    def skip_prev(self) -> None:
        """กดครั้งแรกเมื่อเล่นเกิน 3 วิ = กลับต้นเพลง · ไม่งั้นย้อนไปเพลงก่อนหน้าในคิว"""
        if self.mode == "companion":
            self._tab("prev")
            return
        try:
            pos = float(self.get_clock().position())
        except Exception:
            pos = 0.0
        prev = self.queue.prev() if pos <= 3.0 else None
        if prev is None:
            if self.loaded:
                self.seek(0.0)
            return
        self._publish_queue()
        self.play(prev)

    # ------------------------------------------------------------------
    # โหมดคู่หู (ข้อ 2.2): YouTube เล่น โปรแกรมแสดงเนื้อเพลงตามเวลาที่ส่วนขยายส่งมา
    # ------------------------------------------------------------------
    def companion_track(self, track: TrackRef) -> None:
        """เพลงในแท็บ YouTube เปลี่ยน: หาเนื้อเพลง/ปกให้เพลงนั้น (ไม่โหลดเสียง ไม่มี AI)"""
        self.set_mode("companion")
        with self._lock:
            if self.track is not None and self.track.video_id == track.video_id:
                return
            self._token += 1
            token = self._token
            self._cancel_current()
            if self.aligner is not None and self.track is not None:
                self.aligner.cancel(self.track.video_id)   # เพลงเปลี่ยน: เลิกฟังเสียงของเพลงเก่า
                if self.translator is not None:
                    self.translator.cancel(self.track.video_id)
                if self.emphasizer is not None:
                    self.emphasizer.cancel(self.track.video_id)
            # ชื่อ/ช่อง/Music section ที่ส่วนขยายส่งมาเป็นแค่ "คำใบ้" (อ่านจากหน้าเว็บ อาจเป็นของเพลงก่อนหน้าตอนเปลี่ยนเพลง)
            # จึงไม่แสดง/ไม่ใช้ค้นหา จนกว่าจะยืนยันกับ YouTube จาก videoId (oEmbed + yt-dlp) — ดู _companion_async
            self.track = TrackRef(video_id=track.video_id, added_from="companion")
            self.duration = 0.0
            self.lyrics_offset = 0.0
            self.playing = False
            self.remote_clock = RemoteClock()  # เพลงใหม่ = นาฬิกาใหม่ (ไม่ค้างเวลาของเพลงก่อน)
            self._future = self.io.submit(self._companion_async(track, token))

    @staticmethod
    def _same_title(a: str, b: str) -> bool:
        """ชื่อสองอันเป็นวิดีโอเดียวกันไหม (ไม่สนตัวพิมพ์/เว้นวรรค/เครื่องหมาย; อันหนึ่งเป็นส่วนของอีกอันก็ได้)"""
        import re

        na, nb = (re.sub(r"[\W_]+", "", x.casefold()) for x in (a or "", b or ""))
        return bool(na and nb and (na == nb or na in nb or nb in na))

    async def _resolve_companion_track(self, hint: TrackRef) -> tuple[TrackRef | None, Any]:
        """ข้อมูลเพลงที่ยืนยันแล้วจาก videoId: oEmbed (เร็ว) + yt-dlp (ละเอียด: track/artist/album/คำบรรยาย)

        คืน (TrackRef, VideoInfo|None) หรือ (None, None) ถ้าดึงอะไรไม่ได้เลย
        Music section ที่ส่วนขยายส่งมาใช้ก็ต่อเมื่อชื่อวิดีโอบนหน้าเว็บตรงกับชื่อที่ยืนยันแล้วเท่านั้น
        """
        from app.media.youtube import fetch_oembed

        vid = hint.video_id
        fetch_info = getattr(self.media, "fetch_info", None)
        vi_task = asyncio.ensure_future(asyncio.to_thread(fetch_info, vid)) if fetch_info else None
        oembed = await fetch_oembed(vid)
        vi = None
        if vi_task is not None:
            try:  # yt-dlp ช้ากว่า oEmbed — รอเพิ่มไม่เกิน INFO_WAIT_S ไม่ทันก็ไปต่อด้วยข้อมูลที่มี (เนื้อเพลงไม่ควรรอนาน)
                vi = await asyncio.wait_for(asyncio.shield(vi_task), INFO_WAIT_S)
            except Exception:  # noqa: BLE001 — หมดเวลา/พัง = ไม่มีข้อมูลละเอียด
                vi = None
                vi_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        if vi is not None:
            track = TrackRef(**vi.track.to_dict())
        elif oembed is not None:
            track = TrackRef(video_id=vid, title=oembed[0], channel=oembed[1])
        else:
            return None, None
        track.added_from = "companion"
        if hint.music_section and self._same_title(hint.title, track.title):
            track.music_section = dict(hint.music_section)
        return track, vi

    async def _companion_async(self, hint: TrackRef, token: int) -> None:
        vid = hint.video_id
        alive = lambda: token == self._token  # noqa: E731
        try:
            # ล้างเพลงเก่าออกจากหน้าจอทันที (ไม่ให้ชื่อ/ปก/เนื้อเพลงของเพลงก่อนหน้าค้างปนกับเพลงใหม่)
            self.bus.publish(ev.TRACK_CHANGED, {"video_id": vid, "track_ref": TrackRef(video_id=vid), "deck": -1})
            self._status("กำลังหาข้อมูลเพลง...")
            track, vi = await self._resolve_companion_track(hint)
            if not alive():
                return
            if track is None:
                self._status("")
                self._error(MediaError("media", "ดึงข้อมูลเพลงจาก YouTube ไม่ได้", hint="ตรวจอินเทอร์เน็ต หรือวิดีโอนี้อาจไม่เปิดเผย"))
                return
            track = await asyncio.to_thread(self._track_from_db, track)
            with self._lock:
                if not alive():
                    return
                self.track = track
                self.duration = float(vi.duration) if vi is not None and vi.duration else (track.duration or self.duration)
            self._status("")
            # แสดงชื่อ/ศิลปินทันทีที่ยืนยันแล้ว (ไม่รอผลค้นเนื้อเพลง) — ปกตามมาทีหลังใน _artwork_flow
            from app.lyrics.title_parser import parse_track

            self.bus.publish(ev.TRACK_META_READY, {"video_id": vid, "meta": parse_track(track), "cover_path": None,
                                                   "palette": []})
            await asyncio.to_thread(self._ensure_track, track)
            if vi is not None and getattr(vi, "is_live", False):
                # ถ่ายทอดสด: ไม่มีเนื้อเพลงให้ค้น (UX UI ข้อ 7.1 Unsupported Video) แต่ยังหาปกให้
                self.bus.publish(ev.LYRICS_READY, {"video_id": vid, "lyrics": None, "source_label": "", "candidates_count": 0,
                                                   "final": True, "unsupported": "ถ่ายทอดสด"})
                await self._artwork_flow(track, parse_track(track), token)
                return
            await self._side_tasks(track, vi, token)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if alive():
                self._status("")
                self._error(e)

    def companion_state(self, d: dict[str, Any]) -> None:
        """รับเวลาเล่นจากแท็บ YouTube (ส่งถี่ๆ) -> นาฬิกาของ UI"""
        if self.mode != "companion":
            return
        vid = d.get("video_id")
        if self.track is None or vid != self.track.video_id:
            # ข้อความ companion_track หาย/มาช้า: จับเพลงใหม่จากเวลาที่ส่งมาเลย (ข้อมูลเพลงดึงจาก videoId เองอยู่แล้ว)
            if isinstance(vid, str) and len(vid) == 11:
                self.companion_track(TrackRef(video_id=vid, added_from="companion"))
            else:
                return
        try:
            self.remote_clock.update(float(d.get("current_time", 0.0)), float(d.get("sent_at_ms", 0.0)),
                                     float(d.get("rate", 1.0)) or 1.0, bool(d.get("paused", True)),
                                     bool(d.get("seeked", False)))
            dur = d.get("duration")
            if isinstance(dur, (int, float)) and dur > 0:
                self.duration = float(dur)
            vol = d.get("volume")
            if isinstance(vol, (int, float)) and 0 <= vol <= 1:
                self._set_volume(float(vol), bool(d.get("muted", False)))
            playing = not bool(d.get("paused", True))
            if playing != self.playing:
                self.playing = playing
                self._publish_playback()
        except (TypeError, ValueError):
            log.warning("companion_state ผิดรูปแบบ")

    def skip_mix(self) -> None:
        """ปุ่ม "ข้ามการมิกซ์": ตัดไปเพลง B ทันทีแบบสั้น (รางวัล -0.8)"""
        raise NotImplementedError("เฟส 6")

    # ------------------------------------------------------------------
    # กู้สถานะ / บันทึกสถานะ (ข้อ 11.2)
    # ------------------------------------------------------------------
    def restore(self, state: dict[str, Any]) -> bool:
        """เปิดโปรแกรมใหม่: กลับไปเพลงเดิมตำแหน่งเดิม (หยุดไว้ ยังไม่เล่นจนกว่าผู้ใช้กด)"""
        try:
            if isinstance(state.get("queue"), dict):
                self.queue.restore(state["queue"])
                self._publish_queue()
            ref = state.get("track_ref")
            if not ref:
                return False
            track = TrackRef(**{k: v for k, v in ref.items() if k in TrackRef.__dataclass_fields__})
            if not self._app_audio() or state.get("mode") == "companion":
                # ไม่มีเสียงให้กู้ — แสดงเพลงล่าสุดแบบหยุดไว้ (ส่วนขยายจะส่งเพลงที่เล่นอยู่จริงมาแทนเมื่อเชื่อมต่อ)
                self.companion_track(track)
                return True
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
            "position_s": round(pos, 2), "playing": self.playing, "mode": self.mode,
            "queue": self.queue.snapshot(),
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
                    if self.queue.has_next():  # เพลงจบ -> เพลงถัดไปในคิว (AutoMix/ต่อเนื่องจริงจังเป็นเฟส 5-6)
                        self.skip_next()
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
        self._align_hook(video_id, res)

    def _align_hook(self, video_id: str, res: Any) -> None:
        """เนื้อเพลงสุดท้ายของเพลงนี้พร้อมแล้ว -> ให้ AI ฟังเสียงจัดเวลาจริง (หรือถอดเสียงถ้าไม่พบเนื้อเพลงเลย) ไม่บล็อกอะไร"""
        ai_cfg = getattr(self.settings, "ai", None)
        if self.aligner is None or self.io is None or not getattr(res, "final", True) or not getattr(ai_cfg, "enabled", True):
            return
        chosen = res.chosen
        if chosen is None and not getattr(getattr(self.settings, "lyrics_sources", None), "allow_ai_transcribe", True):
            return
        if chosen is not None and not chosen.lines:
            return
        try:
            ai = self.ai
            if ai is not None and not getattr(ai, "started", True):   # ผู้ใช้เพิ่งเปิด AI ในตั้งค่า (หรือยังไม่เคยเปิด): เปิด worker ตอนนี้
                self.io.loop.run_in_executor(None, ai.start)
            alts: list[Any] = []     # ฉบับอื่นของเนื้อเพลง (ให้ AI ฟังเสียงเทียบว่าฉบับไหนเข้ากับเสียงที่สุด)
            if chosen is not None and getattr(self.settings.lyrics_sources, "audio_pick", True):
                for c in list(getattr(res, "candidates", []))[:6]:
                    ly = getattr(c, "lyrics", None)
                    if ly is None or ly is chosen or len(ly.lines) < 4 or getattr(c, "score", 0.0) < 30.0:
                        continue
                    if getattr(ly, "source", None) == getattr(chosen, "source", None) and getattr(ly, "source_id", None) == getattr(chosen, "source_id", None):
                        continue
                    try:
                        alts.append((self.lyrics.prepare_lyrics(ly, self.duration or None), self.lyrics._label(ly)))
                    except Exception:  # noqa: BLE001
                        continue
                    if len(alts) >= 2:
                        break
            self.io.submit(self.aligner.start(video_id, chosen, res.source_label, self.duration or None, alts))
            if self.translator is not None and chosen is not None and getattr(ai_cfg, "translate", True):
                self.io.submit(self.translator.start(video_id, chosen))
            if self.emphasizer is not None and chosen is not None:
                self.io.submit(self.emphasizer.start(video_id, chosen))
        except Exception:
            log.exception("ส่งงานจัดเวลาด้วย AI ไม่สำเร็จ")

    def on_lyrics_retimed(self, topic: str, p: dict[str, Any]) -> None:
        """AI สร้างเนื้อเพลงชุดใหม่ที่บรรทัดต่างจากเดิม (รีมิกซ์/ถอดเสียง): คำแปลของชุดเดิมใช้ไม่ได้ ให้แปลชุดใหม่"""
        if not p.get("restructured") or not p.get("final") or self.translator is None or self.io is None:
            return
        if not getattr(getattr(self.settings, "ai", None), "translate", True):
            return
        if self.track is None or self.track.video_id != p.get("video_id"):
            return
        try:
            self.io.submit(self.translator.start(p["video_id"], p["lyrics"]))
        except Exception:
            log.exception("ส่งงานแปลเนื้อเพลงชุดใหม่ไม่สำเร็จ")

    def on_align_mismatch(self, video_id: str) -> None:
        """AI ฟังแล้วเนื้อเพลงนี้เป็นคนละเวอร์ชันกับเสียง: ลองเนื้อเพลงอันดับถัดไป (ไม่เกิน 3 ครั้งต่อเพลง กันวนไม่รู้จบ)"""
        if self.track is None or self.track.video_id != video_id:
            return
        n = self._mismatch_tries.get(video_id, 0)
        if n >= 3:
            return
        self._mismatch_tries[video_id] = n + 1
        log.info("เนื้อเพลงไม่ตรงเสียง ลองตัวถัดไป", extra={"data": {"video_id": video_id, "try": n + 1}})
        self.next_lyrics_candidate()

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

    def reset_offset(self) -> None:
        """รีเซ็ต offset เนื้อเพลงของเพลงนี้เป็น 0"""
        if self.track is not None and self.lyrics_offset:
            self.adjust_offset(-self.lyrics_offset)

    def search_lyrics(self, query: str) -> None:
        """ค้นเนื้อเพลงเอง: ล้างแคชของเพลงนี้แล้วค้นด้วยข้อความที่ผู้ใช้พิมพ์ ("ศิลปิน - ชื่อเพลง") แทนชื่อจาก YouTube"""
        if self.track is None or not query.strip():
            return
        base, token = self.track, self._token
        manual = TrackRef(video_id=base.video_id, title=query.strip(), channel="", duration=base.duration or self.duration or None,
                          added_from="manual")

        def purge() -> None:
            conn = self._conn()
            conn.execute("DELETE FROM lyrics_choice WHERE video_id=?", (base.video_id,))
            conn.execute("DELETE FROM lyrics WHERE video_id=?", (base.video_id,))

        async def run() -> None:
            try:
                await asyncio.to_thread(purge)
                await self._lyrics_flow(manual, None, token)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._error(e, "lyrics")

        self.io.submit(run())

    def refresh_lyrics(self) -> None:
        """โหลดเนื้อเพลงใหม่: ล้างแคชของเพลงนี้แล้วค้นทุกแหล่งอีกรอบ (ปุ่ม "โหลดใหม่")"""
        if self.track is None:
            return
        track, token = self.track, self._token

        def purge() -> None:
            conn = self._conn()
            conn.execute("DELETE FROM lyrics_choice WHERE video_id=?", (track.video_id,))
            conn.execute("DELETE FROM lyrics WHERE video_id=?", (track.video_id,))

        async def run() -> None:
            try:
                await asyncio.to_thread(purge)
                await self._lyrics_flow(track, None, token)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._error(e, "lyrics")

        self.io.submit(run())

    async def _lyrics_flow(self, track: TrackRef, info: Any, token: int) -> Any:
        vid = track.video_id
        self.bus.publish(ev.LYRICS_LOADING, {"video_id": vid})
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
