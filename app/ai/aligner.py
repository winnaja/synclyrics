"""LyricsAligner — ตัวประสานฝั่ง process หลัก: เอาเนื้อเพลงที่ได้ ไปให้ AI "ฟังเสียงจริง" แล้วจัดเวลาใหม่ (เฟส 4)

ลำดับ (แอปไม่เล่นเสียง — โหลดเสียงมาวิเคราะห์เบื้องหลังอย่างเดียว):
  1. มีผลที่เคยจัดไว้ใน DB (ai_results) สำหรับเนื้อเพลงชุดนี้ -> ใช้ทันที ไม่เรียก AI
  2. ไม่งั้นรอ AI worker พร้อม (หน้าจอใช้เวลาแบบประมาณไปก่อน) -> โหลดเสียง (ข้ามถ้ามี transcript ใน cache) -> ส่งงาน align_song
  3. worker ส่งผลทยอยทีละช่วง ~30 วิ -> สร้าง Lyrics ใหม่ที่เวลาถูกแล้ว -> EventBus LYRICS_RETIMED (UI อัปเดตแบบไม่รีเซ็ตการเลื่อน)
  4. จบแล้วเก็บลง DB + เก็บช่วงเสียงร้อง (ไว้โชว์จุด 3 จุดในช่วงดนตรี) + ลบไฟล์เสียงที่โหลดมาชั่วคราว
ไม่มีเนื้อเพลงเลย: ถอดเสียงเป็นเนื้อเพลง (ติดป้าย "ถอดเสียงโดย AI อาจมีคำผิด")
เนื้อเพลงจับคู่กับเสียงได้น้อยมาก (คนละเวอร์ชัน): ไม่แตะเวลาเดิม แจ้งที่ป้าย และเรียก on_mismatch ให้ลองเนื้อเพลงตัวถัดไป
ทุกอย่างที่นี่ล้มเหลวได้เงียบๆ — หน้าจอยังมีเวลาแบบประมาณ (ข้อ 11.2)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ai import cache as ai_cache
from app.ai.pipeline.vocal_activity import instrumental_gaps
from app.core import db as dbmod
from app.core import events as ev
from app.core.log import get_logger
from app.core.models import Line, Lyrics, TimingLevel, Voice, Word, WordTimingSource

log = get_logger("ai")

WAIT_AI_S = 120.0       # รอ worker พร้อมไม่เกินนี้ (เปิดโปรแกรมใหม่ๆ ต้อง import torch)
EMPHASIS_LAST_WORD_S = 0.7
GAP_MIN_S = 4.0


# ---------------------------------------------------------------------------
# ฟังก์ชันล้วน (ทดสอบได้ ไม่พึ่ง AI)
# ---------------------------------------------------------------------------
def lyrics_key(lyrics: Lyrics) -> str:
    """ระบุเนื้อเพลงชุดหนึ่ง: แหล่ง + id + ข้อความทุกบรรทัด (เวลาไม่นับ — ผล AI ผูกกับ "ข้อความ")"""
    h = hashlib.sha1()
    h.update(f"{lyrics.source}|{lyrics.source_id}|".encode())
    for ln in lyrics.lines:
        h.update(ln.text.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:20]


def lyrics_to_input(lyrics: Lyrics) -> list[dict[str, Any]]:
    """เนื้อเพลง -> บรรทัดสำหรับส่ง worker (ข้อความรายคำ + เวลาต้นฉบับถ้ามี)"""
    has_times = lyrics.timing != TimingLevel.NONE
    out: list[dict[str, Any]] = []
    for ln in lyrics.lines:
        out.append({"words": [w.text for w in ln.words], "start": ln.start if has_times else None,
                    "end": ln.end if has_times else None,
                    "word_times": [[w.start, w.end] for w in ln.words] if has_times else None})
    return out


def apply_result(base: Lyrics, result_lines: list[dict[str, Any]], resolved_only: bool = False) -> Lyrics:
    """สร้างเนื้อเพลงชุดใหม่ที่เวลาตามผล AI (บรรทัดไม่อยู่ในผล = คงเดิม) · ข้อความ/คำแปล/เสียงของบรรทัดเหมือนเดิม"""
    by_idx = {int(r["i"]): r for r in result_lines}
    lines: list[Line] = []
    for i, ln in enumerate(base.lines):
        r = by_idx.get(i)
        if r is None or (resolved_only and not r.get("resolved")) or len(r.get("words", [])) != len(ln.words):
            lines.append(ln)
            continue
        resolved = bool(r.get("resolved"))
        words: list[Word] = []
        n = len(ln.words)
        for wi, (w, (s, e, conf)) in enumerate(zip(ln.words, r["words"])):
            dur = float(e) - float(s)
            emph = resolved and wi == n - 1 and dur >= EMPHASIS_LAST_WORD_S and conf >= 0.5
            words.append(Word(text=w.text, start=float(s), end=float(e), confidence=float(conf),
                              timing=WordTimingSource.ALIGNED if resolved else WordTimingSource.ESTIMATED,
                              trailing_space=w.trailing_space, emphasis=emph or w.emphasis))
        lines.append(Line(start=float(r["start"]), end=float(r["end"]), words=words, voice=ln.voice,
                          translation=ln.translation, romanization=ln.romanization))
    timing = TimingLevel.WORD if any(w.timing == WordTimingSource.ALIGNED for ln in lines for w in ln.words) else base.timing
    return Lyrics(lines=lines, timing=timing, source=base.source, source_id=base.source_id, language=base.language,
                  has_translation=base.has_translation, ai_transcribed=base.ai_transcribed, title=base.title, artist=base.artist,
                  duration=base.duration)


def regroup_tokens(texts: list[str], times: list[Any], segment: Callable[[str], list[str]]) -> tuple[list[str], list[tuple[float, float, float]]]:
    """Whisper ให้ภาษาไทยเป็นชิ้นย่อย (พยางค์/ตัวอักษร) — รวมเป็นข้อความบรรทัดแล้วตัดคำจริง (pythainlp) ให้เวลาคำ = ช่วงของตัวอักษรที่คำนั้นครอบ
    เพื่อให้ UI วาดสระ/วรรณยุกต์ไทยถูกตำแหน่ง (ห้ามแยกเป็นคนละคำกับพยัญชนะ)"""
    chars: list[tuple[float, float, float]] = []
    for t, (s0, e0, c) in zip(texts, times):
        n = max(1, len(t))
        for k in range(len(t)):
            chars.append((s0 + (e0 - s0) * k / n, s0 + (e0 - s0) * (k + 1) / n, c))
    text = "".join(texts)
    words: list[str] = []
    out: list[tuple[float, float, float]] = []
    pos = 0
    for w in segment(text):
        if not w.strip():
            pos += len(w)
            continue
        seg = chars[pos:pos + len(w)]
        pos += len(w)
        if not seg:
            continue
        words.append(w)
        out.append((seg[0][0], seg[-1][1], sum(x[2] for x in seg) / len(seg)))
    return words, out


def _thai_segment(text: str) -> list[str]:
    from app.lyrics import thai

    return thai.tokenize(text)


def lyrics_from_transcript(result_lines: list[dict[str, Any]], language: str | None, duration: float | None) -> Lyrics:
    """ผลถอดเสียงล้วน (ไม่มีเนื้อเพลงให้เทียบ) -> Lyrics ที่ติดป้าย AI"""
    lines: list[Line] = []
    for r in result_lines:
        texts = r.get("text_words") or []
        times = r.get("words") or []
        if not texts or len(texts) != len(times):
            continue
        if language == "th":
            texts, times = regroup_tokens(texts, times, _thai_segment)
            if not texts:
                continue
        words = []
        for k, (t, (s, e, conf)) in enumerate(zip(texts, times)):
            words.append(Word(text=t, start=float(s), end=float(e), confidence=float(conf), timing=WordTimingSource.ALIGNED,
                              trailing_space=k < len(texts) - 1 and _spaced(language)))
        lines.append(Line(start=words[0].start, end=words[-1].end, words=words, voice=Voice.MAIN))
    return Lyrics(lines=lines, timing=TimingLevel.WORD, source="ai_transcribe", source_id="whisper", language=language,
                  ai_transcribed=True, duration=duration)


def lyrics_from_reconstruct(base: Lyrics, result_lines: list[dict[str, Any]], language: str | None, duration: float | None) -> Lyrics:
    """รีมิกซ์/โครงสร้างต่างจากเนื้อเพลง: บรรทัดตามลำดับที่ร้องจริง · บรรทัดที่ตรงกับเนื้อเพลงสำเร็จรูปใช้ข้อความ/การเว้นวรรคของมัน
    บรรทัดอื่นใช้ข้อความที่ AI ฟังได้ (ติดป้ายว่าถอดเสียงถ้ามีสัดส่วนมาก)"""
    lines: list[Line] = []
    from_ai = 0
    for r in result_lines:
        times = r.get("words") or []
        texts = r.get("text_words") or []
        if not times or len(times) != len(texts):
            continue
        src = r.get("src")
        words: list[Word] = []
        if src:
            flat: list[Word] = []
            for k, idx in enumerate(src):
                ws = base.lines[idx].words
                flat.extend(ws[:-1] + [Word(ws[-1].text, ws[-1].start, ws[-1].end, trailing_space=k < len(src) - 1)] if ws else [])
            if len(flat) != len(times):
                flat = []
            for k, (s0, e0, conf) in enumerate(times):
                tw = flat[k] if flat else None
                words.append(Word(text=tw.text if tw else texts[k], start=float(s0), end=float(e0), confidence=float(conf),
                                  timing=WordTimingSource.ALIGNED, trailing_space=tw.trailing_space if tw else k < len(times) - 1 and _spaced(language)))
        else:
            from_ai += 1
            if language == "th":
                texts, times = regroup_tokens(texts, times, _thai_segment)
                if not texts:
                    continue
            for k, (s0, e0, conf) in enumerate(times):
                words.append(Word(text=texts[k], start=float(s0), end=float(e0), confidence=float(conf), timing=WordTimingSource.ALIGNED,
                                  trailing_space=k < len(times) - 1 and _spaced(language)))
        for k, w in enumerate(words):   # เน้นคำท้ายบรรทัดที่ลากเสียง (เหมือนโหมดปกติ)
            if k == len(words) - 1 and w.end - w.start >= EMPHASIS_LAST_WORD_S and w.confidence >= 0.5:
                w.emphasis = True
        lines.append(Line(start=words[0].start, end=words[-1].end, words=words, voice=Voice.MAIN))
    return Lyrics(lines=lines, timing=TimingLevel.WORD, source=base.source, source_id=base.source_id, language=base.language or language,
                  ai_transcribed=bool(lines) and from_ai / len(lines) > 0.3, title=base.title, artist=base.artist, duration=duration or base.duration)


def clean_label(label: str) -> str:
    """ป้ายแหล่งเนื้อเพลงหลังจัดเวลาจากเสียงแล้ว: ตัดคำเตือน "ความยาวต่างจากวิดีโอ ... เวลาอาจเลื่อน" ออก (แก้แล้ว) และ "จัดเวลาจากเสียง N%" ค้าง"""
    parts = [p for p in label.split(" · ") if p and "ความยาวต่างจากวิดีโอ" not in p and "เวลาอาจเลื่อน" not in p and "จัดเวลาจากเสียง" not in p]
    return " · ".join(parts)


def _spaced(language: str | None) -> bool:
    """ภาษาที่เขียนเว้นวรรคระหว่างคำ (ไทย/ญี่ปุ่น/จีน ไม่เว้น)"""
    return (language or "en") not in ("th", "ja", "zh", "yue", "lo", "km", "my")


def gaps_from_vocals(vocal_segments: list[list[float]], duration: float, min_gap_s: float = GAP_MIN_S) -> list[list[float]]:
    return [list(g) for g in instrumental_gaps([(a, b) for a, b in vocal_segments], duration, min_gap_s)]


# ---------------------------------------------------------------------------
# ตัวประสาน
# ---------------------------------------------------------------------------
class LyricsAligner:
    def __init__(self, ai: Any, bus: Any, db_path: Path | str, paths: Any, media: Any, models_config: dict[str, Any],
                 position_fn: Callable[[], float] | None = None, on_mismatch: Callable[[str], None] | None = None) -> None:
        self.ai = ai
        self.bus = bus
        self.db_path = db_path
        self.paths = paths
        self.media = media
        self.cfg = models_config
        self.position_fn = position_fn or (lambda: 0.0)
        self.on_mismatch = on_mismatch
        self.algo = int(models_config.get("analysis", {}).get("algo_version", 1))
        self._base: dict[str, tuple[Lyrics, str]] = {}       # video_id -> (เนื้อเพลงฐานที่กำลังจัด, ป้ายแหล่ง)
        self._jobs: dict[str, str] = {}                      # video_id -> job_id ปัจจุบัน

    # ---------- DB ----------
    def _conn(self) -> Any:
        return dbmod.connect(self.db_path)

    def _load_cached(self, video_id: str, key: str) -> dict[str, Any] | None:
        try:
            conn = self._conn()
            row = conn.execute("SELECT version, payload FROM ai_results WHERE video_id=? AND kind='align' AND lyrics_key=?",
                               (video_id, key)).fetchone()
            conn.close()
            if row and int(row["version"]) == self.algo:
                return json.loads(row["payload"])
        except Exception:  # noqa: BLE001
            log.exception("อ่านผล AI จาก DB ไม่ได้")
        return None

    def _save(self, video_id: str, key: str, data: dict[str, Any]) -> None:
        try:
            conn = self._conn()
            conn.execute("INSERT OR REPLACE INTO ai_results(video_id, kind, lyrics_key, version, payload, created_at) VALUES(?,?,?,?,?,?)",
                         (video_id, "align", key, self.algo, json.dumps(data, ensure_ascii=False), time.time()))
            conn.commit()
            conn.close()
        except Exception:  # noqa: BLE001
            log.exception("บันทึกผล AI ลง DB ไม่ได้")

    # ---------- ควบคุม ----------
    def cancel(self, video_id: str | None = None) -> None:
        """เปลี่ยนเพลง/ข้ามเพลง: ยกเลิกงานของเพลงที่ระบุ (หรือทั้งหมด)"""
        vids = [video_id] if video_id else list(self._jobs)
        for v in vids:
            self._jobs.pop(v, None)
            self._base.pop(v, None)
            try:
                self.ai.cancel_video(v)
            except Exception:  # noqa: BLE001
                pass

    def _publish(self, video_id: str, lyrics: Lyrics, label: str, final: bool, **extra: Any) -> None:
        self.bus.publish(ev.LYRICS_RETIMED, {"video_id": video_id, "lyrics": lyrics, "source_label": label, "final": final, **extra})

    async def start(self, video_id: str, lyrics: Lyrics | None, source_label: str, duration: float | None) -> None:
        """เรียกเมื่อได้เนื้อเพลงสุดท้ายของเพลงนี้ (lyrics=None = ไม่พบเลย -> ถอดเสียงเป็นเนื้อเพลง)"""
        try:
            await self._start(video_id, lyrics, source_label, duration)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — AI พังไม่กระทบเนื้อเพลงที่แสดงอยู่
            log.exception("จัดเวลาด้วย AI ไม่สำเร็จ")

    async def _start(self, video_id: str, lyrics: Lyrics | None, source_label: str, duration: float | None) -> None:
        self.cancel(video_id)
        key = lyrics_key(lyrics) if lyrics is not None and lyrics.lines else "transcribe"
        if lyrics is not None and not lyrics.lines:
            return
        # 1) ผลที่เคยทำไว้
        cached = await asyncio.to_thread(self._load_cached, video_id, key)
        if cached is not None:
            self._finish(video_id, lyrics, source_label, cached, from_cache=True)
            return
        # 2) รอ AI พร้อม
        waited = 0.0
        while not getattr(self.ai, "available", False):
            if waited >= WAIT_AI_S or (waited >= 3.0 and not getattr(self.ai, "started", True) and not getattr(self.ai, "_starting", False)):
                return
            await asyncio.sleep(0.5)
            waited += 0.5
        stems_dir = Path(self.paths.stems_cache_dir) / video_id
        have_transcript = await asyncio.to_thread(
            lambda: ai_cache.load_transcript(stems_dir / "transcript.json", ai_cache.transcript_key(self.cfg)) is not None)
        audio_path = ""
        tmp_dir: Path | None = None
        if not have_transcript:
            tmp_dir = Path(self.paths.cache_dir) / "analysis" / video_id
            self.bus.publish(ev.AI_STATUS, {"video_id": video_id, "state": "downloading", "text": "กำลังโหลดเสียงเพื่อวิเคราะห์"})
            audio_path = await asyncio.to_thread(self._download, video_id, tmp_dir)
            if not audio_path:
                return
        # 3) ส่งงาน
        self._base[video_id] = (lyrics, source_label) if lyrics is not None else (None, source_label)  # type: ignore[assignment]
        lines = lyrics_to_input(lyrics) if lyrics is not None else []
        language = lyrics.language if lyrics is not None else None
        hint = float(self.position_fn() or 0.0)

        def handler(msg: dict[str, Any]) -> None:
            self._on_event(video_id, key, msg, tmp_dir, duration)

        self._jobs[video_id] = "pending"   # ตั้งก่อนส่ง: ผลที่กลับมาเร็วมาก (cache) ต้องไม่ถูกทิ้งเพราะยังไม่มี job
        self._jobs[video_id] = self.ai.submit_align(video_id, audio_path, lines, language, hint, handler)
        self.bus.publish(ev.AI_STATUS, {"video_id": video_id, "state": "analyzing", "text": "AI กำลังฟังเสียงเพื่อจัดเวลา"})

    def _download(self, video_id: str, target: Path) -> str:
        try:
            _info, dl = self.media.fetch_and_download(video_id, target)
            return str(dl.path)
        except Exception as e:  # noqa: BLE001
            log.warning("โหลดเสียงเพื่อวิเคราะห์ไม่ได้", extra={"data": {"video_id": video_id, "err": str(e)[:200]}})
            return ""

    # ---------- รับผลจาก worker (เรียกใน thread ของ AiClient) ----------
    def _on_event(self, video_id: str, key: str, msg: dict[str, Any], tmp_dir: Path | None, duration: float | None) -> None:
        if video_id not in self._jobs:     # ถูกยกเลิก/เปลี่ยนเพลงไปแล้ว
            return
        t, p = msg.get("type"), msg.get("payload", {})
        base, label = self._base.get(video_id, (None, ""))
        if t == "failed":
            self._cleanup(video_id, tmp_dir)
            self.bus.publish(ev.AI_STATUS, {"video_id": video_id, "state": "failed", "text": ""})
            return
        if t != "result":
            return
        data = p.get("data", {})
        if p.get("kind") == "align_partial" and base is not None:
            total = max(1, int(data.get("windows_total", 1)))
            done = int(data.get("windows_done", 0))
            lyr = apply_result(base, data.get("lines", []), resolved_only=True)
            self._publish(video_id, lyr, f"{label} · จัดเวลาจากเสียง {done * 100 // total}%", False, coverage=data.get("coverage"))
        elif p.get("kind") == "align_final":
            self._cleanup(video_id, tmp_dir)
            data["duration"] = data.get("duration") or duration
            if data.get("mode") == "match" and not data.get("version_mismatch"):
                self._save(video_id, key, data)
            elif data.get("mode") in ("transcribe", "reconstruct"):
                self._save(video_id, key, data)
            self._finish(video_id, base, label, data, from_cache=False)

    def _finish(self, video_id: str, base: Lyrics | None, label: str, data: dict[str, Any], from_cache: bool) -> None:
        dur = float(data.get("duration") or 0.0)
        gaps = gaps_from_vocals(data.get("vocal_segments", []), dur) if dur else []
        if data.get("mode") == "transcribe" or base is None:
            lyr = lyrics_from_transcript(data.get("lines", []), data.get("language"), dur or None)
            if not lyr.lines:
                return
            self._publish(video_id, lyr, "ถอดเสียงโดย AI · อาจมีคำผิด", True, coverage=1.0, gaps=gaps, restructured=True)
        elif data.get("mode") == "reconstruct":
            lyr = lyrics_from_reconstruct(base, data.get("lines", []), data.get("language"), dur or None)
            if not lyr.lines:
                return
            self._publish(video_id, lyr, f"{clean_label(label)} · จัดตามเสียงจริง (โครงสร้างเพลงต่างจากเนื้อเพลง)", True, coverage=data.get("coverage"), gaps=gaps,
                          restructured=True)
        elif data.get("version_mismatch"):
            # จับคู่กับเสียงได้น้อยมาก: เนื้อเพลงน่าจะเป็นคนละเวอร์ชัน — ไม่แตะเวลาเดิม แจ้งผู้ใช้ และให้ controller ลองตัวถัดไป
            self._publish(video_id, base, f"{label} · เนื้อเพลงอาจเป็นคนละเวอร์ชันกับเสียง", True, coverage=data.get("coverage"), gaps=gaps)
            if self.on_mismatch is not None and not from_cache:
                self.on_mismatch(video_id)
        else:
            lyr = apply_result(base, data.get("lines", []), resolved_only=False)
            cov = int(round(float(data.get("coverage", 0.0)) * 100))
            self._publish(video_id, lyr, f"{clean_label(label)} · จัดเวลาจากเสียงแล้ว", True, coverage=data.get("coverage"), gaps=gaps)
            log.info("จัดเวลาจากเสียงเสร็จ", extra={"data": {"video_id": video_id, "coverage_pct": cov, "cached": from_cache,
                                                           "offset_s": data.get("offset_s")}})
        self._jobs.pop(video_id, None)
        self.bus.publish(ev.AI_STATUS, {"video_id": video_id, "state": "idle", "text": ""})

    def _cleanup(self, video_id: str, tmp_dir: Path | None) -> None:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        try:
            ai_cache.enforce_limit(Path(self.paths.stems_cache_dir))
        except Exception:  # noqa: BLE001
            pass
