"""LyricsService — จุดเดียวที่ส่วนอื่นเรียกเพื่อได้เนื้อเพลง (ข้อ 4.2-4.4)

find(track) ทำตามลำดับนี้ใน asyncio loop (thread IO):
  1. cache ใน SQLite ตาม videoId (มีตัวเลือกที่ผู้ใช้เลือกไว้ -> ใช้อันนั้นเลย)
  2. แยกชื่อเพลง (title_parser) -> สร้าง LyricsQuery
  3. ค้นทุกแหล่งที่เปิดอยู่พร้อมกัน (แต่ละแหล่งมี timeout ของตัวเอง) — แหล่งพัง = ข้าม
     ผลแรกที่ผ่านเกณฑ์ส่งออกทาง on_update ทันที แล้วสลับถ้าผลที่มาทีหลังคะแนนดีกว่า
  4. ให้คะแนน (scoring) เรียงผล เก็บทุกผลลง DB (ใช้กด "ผลถัดไป")
  5. ผลที่ดีที่สุดไม่มีเวลาทีละคำ -> ใส่เวลาแบบประมาณ (timing_estimate) ภายใน 1 วิหลังกดเล่น
  6. ไม่เจอเลย -> needs_ai_transcription (เฟส 4 ส่งต่อ faster-whisper)

กดเล่นแล้วต้องมีเนื้อเพลงเสมอ ห้ามถามผู้ใช้ — การวางเนื้อเพลงเองเป็นแค่ทางสำรองในเมนู
ฐานข้อมูล: connection แยกต่อ thread (service นี้ใช้ใน thread IO เป็นหลัก)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import db as dbmod
from app.core.config import LyricsSourceSettings
from app.core.log import get_logger
from app.core.models import Lyrics, TimingLevel, TrackMeta, TrackRef
from app.lyrics import fusion, scoring
from app.lyrics.parsers.lrc import parse_plain
from app.lyrics.linebreak import split_long_lines
from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource, discover
from app.lyrics.timing_estimate import estimate_lyrics
from app.lyrics.title_parser import parse_track, swap_meta

log = get_logger("lyrics")
# สลับลำดับเพลง/ศิลปินเมื่อคะแนนดีขึ้นอย่างน้อยเท่านี้
SWAP_MARGIN = 5.0


@dataclass(slots=True)
class LyricsResult:
    chosen: Lyrics | None
    candidates: list[LyricsCandidate]
    source_label: str  # เช่น "จาก LRCLIB · ทีละคำ"
    from_cache: bool = False
    needs_ai_transcription: bool = False
    meta: TrackMeta | None = None
    final: bool = True  # False = ผลชั่วคราว (ยังมีแหล่งที่ยังไม่ตอบ)


def source_label(lyrics: Lyrics, display_name: str) -> str:
    """ข้อความเล็กๆ มุมจอ (ข้อ 4.3)"""
    level = {"word": "ทีละคำ", "line": "ทีละบรรทัด", "none": "ประมาณเวลา"}[lyrics.timing.value]
    prefix = "ถอดเสียงโดย AI" if lyrics.ai_transcribed else f"จาก {display_name}"
    return f"{prefix} · {level}"


class LyricsService:
    """ประสานงานแหล่งเนื้อเพลงทั้งหมด"""

    def __init__(
        self,
        db_path: Path | str,
        settings: LyricsSourceSettings | None = None,
        sources: dict[str, type[LyricsSource]] | None = None,
        client: Any = None,
    ) -> None:
        self.db_path = db_path
        self.settings = settings or LyricsSourceSettings()
        self._source_classes = sources if sources is not None else discover()
        self._client = client
        self._local = threading.local()

    # ---------- โครงสร้างพื้นฐาน ----------
    def _db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = dbmod.connect(self.db_path)
            self._local.conn = conn
        return conn

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(follow_redirects=True, timeout=10.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and hasattr(self._client, "aclose"):
            await self._client.aclose()

    def enabled_sources(self) -> list[LyricsSource]:
        out: list[LyricsSource] = []
        for name, cls in self._source_classes.items():
            if getattr(self.settings, f"src_{name}", True) and self.settings.enabled.get(name, cls.enabled_by_default):
                out.append(cls())
        return out

    def _display(self, name: str) -> str:
        cls = self._source_classes.get(name)
        if cls is not None:
            return cls.display_name
        return {"manual": "ที่วางเอง", fusion.SOURCE_NAME: "SyncLyrics (รวมหลายแหล่ง)"}.get(name, name)

    def _label(self, lyrics: Lyrics) -> str:
        return source_label(lyrics, self._display(lyrics.source))

    # ---------- DB ----------
    def _upsert_track(self, track: TrackRef, meta: TrackMeta | None) -> None:
        conn = self._db()
        now = time.time()
        conn.execute(
            "INSERT INTO tracks(video_id, yt_title, channel, duration_s, first_seen_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(video_id) DO UPDATE SET yt_title=excluded.yt_title, channel=excluded.channel, "
            "duration_s=COALESCE(excluded.duration_s, duration_s)",
            (track.video_id, track.title, track.channel, track.duration, now),
        )
        if meta:
            # title/artist ที่เคยแยก/แก้ไว้แล้ว (เช่น สลับลำดับตามผลเนื้อเพลง) ต้องไม่ถูกเขียนทับด้วยการเดาใหม่
            conn.execute(
                "UPDATE tracks SET title=COALESCE(title,?), artist=COALESCE(artist,?), album=COALESCE(album,?), "
                "version_tags=?, music_section=? WHERE video_id=?",
                (meta.title, meta.artist, meta.album, json.dumps(sorted(meta.version_tags)),
                 json.dumps(track.music_section, ensure_ascii=False), track.video_id),
            )

    def _stored_names(self, video_id: str) -> tuple[str, str] | None:
        r = self._db().execute("SELECT title, artist FROM tracks WHERE video_id=?", (video_id,)).fetchone()
        return (r["title"], r["artist"]) if r and r["title"] and r["artist"] is not None else None

    def _save_names(self, video_id: str, meta: TrackMeta) -> None:
        self._db().execute("UPDATE tracks SET title=?, artist=? WHERE video_id=?", (meta.title, meta.artist, video_id))

    def _store(self, video_id: str, cands: list[LyricsCandidate]) -> None:
        conn = self._db()
        now = time.time()
        for c in cands:
            ly = c.lyrics
            conn.execute(
                "INSERT INTO lyrics(video_id, source, source_id, timing, language, score, payload, fetched_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(video_id, source, source_id) DO UPDATE SET "
                "timing=excluded.timing, language=excluded.language, score=excluded.score, "
                "payload=excluded.payload, fetched_at=excluded.fetched_at",
                (video_id, ly.source, ly.source_id, ly.timing.value, ly.language, c.score,
                 json.dumps(ly.to_dict(), ensure_ascii=False), now),
            )

    def _load_cached(self, video_id: str) -> tuple[list[tuple[int, LyricsCandidate]], int | None]:
        """คืน ([(id ใน DB, candidate)] เรียงคะแนน, id ที่ผู้ใช้เลือก)"""
        conn = self._db()
        rows = conn.execute(
            "SELECT id, score, payload FROM lyrics WHERE video_id=? ORDER BY score DESC, id", (video_id,)
        ).fetchall()
        cands: list[tuple[int, LyricsCandidate]] = []
        for r in rows:
            try:
                ly = Lyrics.from_dict(json.loads(r["payload"]))
            except Exception:
                log.warning("เนื้อเพลงใน cache เสีย ข้าม", extra={"data": {"id": r["id"]}})
                continue
            cands.append((r["id"], LyricsCandidate(lyrics=ly, matched_title=ly.title or "",
                                                    matched_artist=ly.artist or "",
                                                    matched_duration=ly.duration, score=r["score"])))
        ch = conn.execute("SELECT lyrics_id FROM lyrics_choice WHERE video_id=?", (video_id,)).fetchone()
        return cands, (ch["lyrics_id"] if ch else None)

    @staticmethod
    def _fusable(cands: list[LyricsCandidate]) -> bool:
        """มีเนื้อเพลงที่ใช้ได้พอให้รวมไหม (เงื่อนไขเดียวกับ fusion.fuse) — ไม่พอ = ค้นซ้ำก็ไม่เกิดฉบับรวม"""
        n = sum(1 for c in cands if c.lyrics.source != fusion.SOURCE_NAME
                and max(0.0, float(c.score_detail.get("base", c.score))) >= scoring.CONSENSUS_VOTER_MIN
                and len(c.lyrics.lines) >= fusion.MIN_LINES)
        return n >= fusion.MIN_VOTERS

    @staticmethod
    def _is_current_fusion(c: LyricsCandidate) -> bool:
        ly = c.lyrics
        return ly.source == fusion.SOURCE_NAME and ly.source_id.startswith(f"v{fusion.FUSION_VERSION}:")

    def _set_choice(self, video_id: str, lyrics_id: int) -> None:
        self._db().execute(
            "INSERT INTO lyrics_choice(video_id, lyrics_id, chosen_at) VALUES(?,?,?) "
            "ON CONFLICT(video_id) DO UPDATE SET lyrics_id=excluded.lyrics_id, chosen_at=excluded.chosen_at",
            (video_id, lyrics_id, time.time()),
        )

    def _track_duration(self, video_id: str) -> float | None:
        r = self._db().execute("SELECT duration_s FROM tracks WHERE video_id=?", (video_id,)).fetchone()
        return r["duration_s"] if r else None

    # ---------- ผลลัพธ์ ----------
    def _present(self, cands: list[LyricsCandidate], duration: float | None, meta: TrackMeta | None,
                 pick: LyricsCandidate | None = None, from_cache: bool = False, final: bool = True) -> LyricsResult:
        ranked = sorted(cands, key=lambda c: c.score, reverse=True)
        chosen_c = pick or next((c for c in ranked if c.score >= scoring.MIN_ACCEPT_SCORE), None)
        if chosen_c is None:
            return LyricsResult(None, ranked, "ไม่พบเนื้อเพลง", from_cache,
                                needs_ai_transcription=self.settings.allow_ai_transcribe, meta=meta, final=final)
        ly = self.prepare_lyrics(chosen_c.lyrics, duration)
        label = self._label(chosen_c.lyrics)
        got = chosen_c.matched_duration or chosen_c.lyrics.duration
        diff = abs(duration - got) if duration and got else 0.0
        if diff > scoring.SOFT_DURATION_DIFF_S:  # เช่น MV มีฉากเปิดเรื่อง: เวลาอาจเลื่อน ผู้ใช้ปรับด้วย [ ] ได้
            label += f" · ความยาวต่างจากวิดีโอ {diff:.0f} วิ เวลาอาจเลื่อน"
        return LyricsResult(ly, ranked, label, from_cache, meta=meta, final=final)

    def prepare_lyrics(self, lyrics: Lyrics, duration: float | None) -> Lyrics:
        """เนื้อเพลงดิบจากแหล่ง -> พร้อมแสดง: ใส่เวลาประมาณรายคำ (ถ้ายังไม่มี) + ตัดบรรทัดยาว"""
        ly = lyrics
        if ly.timing != TimingLevel.WORD:
            ly = estimate_lyrics(ly, duration or ly.duration or 240.0)
        if getattr(self.settings, "split_long_lines", False):
            ly = split_long_lines(ly, int(self.settings.max_line_width))
        return ly

    @staticmethod
    def _reconcile_meta(track: TrackRef, meta: TrackMeta, cands: list[LyricsCandidate],
                        duration: float | None) -> TrackMeta:
        """ชื่อวิดีโอ "เพลง - ศิลปิน" ที่เราเดาลำดับผิด: ถ้าสลับแล้วผลเนื้อเพลงตรงกว่าชัดเจน ใช้ลำดับที่สลับ

        ไม่ทำเมื่อชื่อ/ศิลปินมาจากแหล่งที่เชื่อถือได้ (Music section / metadata ของ yt-dlp)
        คะแนนของผลทั้งหมดถูกคำนวณใหม่ตามลำดับที่เลือก
        """
        if not cands or (track.music_section.get("song") and track.music_section.get("artist")) or (
            track.ytdlp_meta.get("track") and track.ytdlp_meta.get("artist")
        ):
            return meta
        swapped = swap_meta(meta)
        best_orig = max(c.score_detail.get("base", c.score) for c in cands)   # เทียบคะแนนปกติ (ไม่รวมโบนัสฉันทามติ)
        copies = [LyricsCandidate(lyrics=c.lyrics, matched_title=c.matched_title, matched_artist=c.matched_artist,
                                  matched_duration=c.matched_duration) for c in cands]
        best_swap = max((scoring.score_candidate(c, swapped, duration) for c in copies), default=0.0)
        if best_swap > best_orig + SWAP_MARGIN:
            for c, new in zip(cands, copies, strict=True):
                c.score, c.score_detail = new.score, new.score_detail
            log.info("สลับลำดับ ชื่อเพลง/ศิลปิน", extra={"data": {"video_id": track.video_id,
                                                              "title": swapped.title, "artist": swapped.artist}})
            return swapped
        return meta

    # ---------- API สาธารณะ ----------
    async def find(
        self,
        track: TrackRef,
        duration: float | None,
        extras: dict[str, Any] | None = None,
        on_update: Callable[[LyricsResult], None] | None = None,
    ) -> LyricsResult:
        duration = duration or track.duration
        meta = parse_track(track)
        await asyncio.to_thread(self._upsert_track, track, meta)
        stored = await asyncio.to_thread(self._stored_names, track.video_id)
        if stored and (stored[0], stored[1]) != (meta.title, meta.artist):
            meta = dataclasses.replace(meta, title=stored[0], artist=stored[1])  # ใช้ชื่อที่เคยยืนยัน/แก้ไว้

        cached, choice_id = await asyncio.to_thread(self._load_cached, track.video_id)
        if cached:
            # ให้คะแนน cache ใหม่ด้วยเกณฑ์ปัจจุบัน (ชื่อ/ศิลปิน/ความยาวของเพลงที่เล่นอยู่ตอนนี้) — ผลที่บันทึกไว้ตอนก่อนมีเกณฑ์
            # ตรวจภาษา/ความยาวจะได้ไม่ถูกใช้ต่อ · ไม่ต้องค้นเน็ตใหม่ (ใช้ชื่อที่ตัวเองบันทึกไว้ในแต่ละฉบับ)
            for _, c in cached:
                if c.lyrics.source not in ("manual", fusion.SOURCE_NAME):
                    stored = c.score
                    scoring.score_candidate(c, meta, duration)
                    c.score_detail["stored_score"] = stored
            cands = [c for _, c in cached]
            pick = next((c for i, c in cached if i == choice_id), None)
            if pick is not None and pick.lyrics.source != "manual" and pick.score < scoring.MIN_ACCEPT_SCORE:
                pick = None        # ฉบับที่เคยถูกเลือกไว้ แต่คะแนนต่ำกว่าเกณฑ์ (เช่นเลือกตอนระบบยังไม่ตรวจภาษา/ความยาว) ไม่ใช้ซ้ำ
            # ผู้ใช้เลือกฉบับเองไว้ = เคารพการเลือกนั้น ไม่เอา fusion ไปทับ
            # ไม่ได้เลือก: ใช้ cache ได้เฉพาะเมื่อมีฉบับ fusion ของเวอร์ชันปัจจุบันอยู่แล้ว
            # (cache ที่มีแต่เนื้อดิบจากเว็บ หรือ fusion เวอร์ชันเก่า ต้องไม่จบแค่นี้ ไม่งั้นข้าม fusion ไปตลอดกาล)
            if pick is None:
                pick = next((c for c in cands if self._is_current_fusion(c)), None)
            # ไม่มีฉบับ fusion แต่รวมไม่ได้อยู่แล้วเพราะมีเนื้อที่ใช้ได้ไม่ถึง 2 ฉบับ = ค้นซ้ำก็ได้ผลเดิม ใช้ cache ต่อได้
            # (ถ้ามี >= 2 ฉบับที่ใช้ได้แต่ยังไม่มี fusion เวอร์ชันนี้ = cache เก่าก่อนมีระบบรวม ต้องรวมใหม่)
            if pick is None and not self._fusable(cands):
                pick = next((c for i, c in cached if i == choice_id), None)
                keep_cache = True
            else:
                keep_cache = pick is not None
            if keep_cache:
                result = self._present(cands, duration, meta, pick=pick, from_cache=True)
                if result.chosen is not None:
                    return result

        query = LyricsQuery(track=track, meta=meta, duration=duration, extras=extras or {})
        sources = self.enabled_sources()
        client = self._get_client()

        async def run(src: LyricsSource) -> list[LyricsCandidate]:
            try:
                return await asyncio.wait_for(src.search(query, client), timeout=src.timeout_s + 1.0)
            except Exception as e:  # แหล่งพัง/ช้า = ข้ามเงียบๆ (log ระดับ debug สำหรับแหล่งไม่เป็นทางการ)
                level = log.debug if src.unofficial else log.warning
                level("แหล่งเนื้อเพลงใช้ไม่ได้", extra={"data": {"source": src.name, "err": repr(e)}})
                return []

        tasks = [asyncio.create_task(run(s)) for s in sources]
        all_cands: list[LyricsCandidate] = []
        best_key: tuple[str, str] | None = None
        for fut in asyncio.as_completed(tasks):
            got = await fut
            for c in got:
                scoring.score_candidate(c, meta, duration)
            all_cands.extend(got)
            scoring.apply_consensus(all_cands)   # เทียบเนื้อเพลงข้ามแหล่ง: ฉบับที่ตรงกับแหล่งอื่นมากได้โบนัส
            if on_update is not None and got:
                interim = self._present(all_cands, duration, meta, final=False)
                if interim.chosen is not None:
                    top = max(all_cands, key=lambda c: c.score)
                    key = (top.lyrics.source, top.lyrics.source_id)
                    if key != best_key:  # ส่งเฉพาะตอนผลที่ดีที่สุดเปลี่ยน
                        best_key = key
                        try:
                            on_update(interim)
                        except Exception:
                            log.exception("on_update พัง")

        new_meta = self._reconcile_meta(track, meta, all_cands, duration)
        if new_meta is not meta:
            meta = new_meta
            await asyncio.to_thread(self._save_names, track.video_id, meta)
        all_cands = [c for c in all_cands if c.score > 0]
        scoring.apply_consensus(all_cands)
        fused_pick: LyricsCandidate | None = None
        try:
            got = await asyncio.to_thread(fusion.fuse, all_cands, meta, duration)
        except Exception:
            log.exception("รวมเนื้อเพลงไม่สำเร็จ ใช้ฉบับที่คะแนนสูงสุดแทน")
            got = None
        if got is not None:
            fused_pick, report = got
            all_cands.append(fused_pick)
            log.info("รวมเนื้อเพลงหลายแหล่ง", extra={"data": {
                "video_id": track.video_id, "voters": report.voters, "spine": report.spine,
                "lines": report.lines_total, "replaced": report.lines_replaced,
                "agreed": report.lines_agreed}})
        await asyncio.to_thread(self._store, track.video_id, all_cands)
        result = self._present(all_cands, duration, meta, pick=fused_pick)
        if result.chosen is not None:
            log.info("เลือกเนื้อเพลง", extra={"data": {
                "video_id": track.video_id, "label": result.source_label,
                "score": round(max(c.score for c in all_cands), 1), "n": len(all_cands)}})
        else:
            log.info("ไม่พบเนื้อเพลง", extra={"data": {"video_id": track.video_id, "n": len(all_cands)}})
        return result

    async def next_candidate(self, video_id: str) -> LyricsResult:
        """ปุ่ม "ผลถัดไป": สลับไปผลอันดับถัดไปและจำไว้ตาม videoId"""
        return await asyncio.to_thread(self._next_candidate_sync, video_id)

    def _next_candidate_sync(self, video_id: str) -> LyricsResult:
        cached, choice_id = self._load_cached(video_id)
        duration = self._track_duration(video_id)
        # เดินเฉพาะฉบับที่ผ่านเกณฑ์รับเหมือนตอนค้นหา: ฉบับคะแนน 0-40 ถูกเก็บไว้ใน cache แต่มักเป็นเพลงอื่น
        # (เดิมกรองแค่ > 0 และ pick ข้ามเกณฑ์ใน _present ทำให้ "ลองตัวถัดไป" ลงไปหาเนื้อคนละเพลงได้)
        usable = [(i, c) for i, c in cached if c.score >= scoring.MIN_ACCEPT_SCORE]
        if not usable:
            return self._present([], duration, None)
        if choice_id is None:
            # ยังไม่มีใครเลือก = ระบบกำลังแสดงฉบับที่รวมแล้ว (ถ้ามี) ให้ฉบับนั้นอยู่ต้นลำดับ
            # ไม่งั้น "ถัดไป" จากฉบับรวมจะกระโดดไปฉบับคะแนนต่ำสุดก่อน (อาจเป็นฉบับผิดเพลง)
            usable.sort(key=lambda t: 0 if self._is_current_fusion(t[1]) else 1)
        ids = [i for i, _ in usable]
        if choice_id in ids:
            idx = (ids.index(choice_id) + 1) % len(ids)
        else:  # ยังไม่เคยเลือก: อันแรกคืออันที่ระบบเลือกอยู่ ให้ไปอันถัดไป
            idx = 1 % len(ids)
        new_id, new_c = usable[idx]
        self._set_choice(video_id, new_id)
        return self._present([c for _, c in usable], duration, None, pick=new_c, from_cache=True)

    def set_manual_lyrics(self, video_id: str, text: str) -> Lyrics:
        """ทางสำรองในเมนู: ผู้ใช้วางเนื้อเพลงเอง (ได้ TimingLevel.NONE -> ประมาณเวลา + AI)"""
        ly = parse_plain(text, source="manual")
        ly.source_id = "manual"
        conn = self._db()
        conn.execute(
            "INSERT OR IGNORE INTO tracks(video_id, first_seen_at) VALUES(?,?)", (video_id, time.time())
        )
        self._store(video_id, [LyricsCandidate(lyrics=ly, score=100.0)])
        row = conn.execute(
            "SELECT id FROM lyrics WHERE video_id=? AND source='manual' AND source_id='manual'", (video_id,)
        ).fetchone()
        if row:
            self._set_choice(video_id, row["id"])
        return estimate_lyrics(ly, self._track_duration(video_id) or 240.0)
