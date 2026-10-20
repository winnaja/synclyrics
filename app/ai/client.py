"""AiClient — ฝั่ง process หลักที่เปิด/คุย/เฝ้า AI worker (ข้อ 5, 11.2)

- เปิด worker ด้วย multiprocessing (spawn) ตั้ง priority ต่ำกว่า UI/เสียง (worker ตั้งเอง)
- ส่งงานผ่าน request queue, รับผลผ่าน event queue (thread ฟังแยก) แล้วเรียก callback ของงานนั้น (ใน thread ฟัง)
- watchdog: ไม่มี heartbeat เกิน models.watchdog_timeout_s หรือ process ตาย -> kill แล้วเปิดใหม่
  งานที่ค้างอยู่ส่งใหม่ (attempts+1, เกิน 2 ครั้ง = ยอมแพ้ แจ้ง failed) เพลง/หน้าจอไม่หยุด
- ไม่มี GPU / ไม่ได้ติดตั้ง requirements-ai.txt: `available=False` ระบบทำงานแบบ "ไม่มี AI" (เวลาแบบประมาณล้วน) ห้าม crash
- ห้าม import torch ที่นี่ (process หลักต้องเบา) — แค่ตรวจว่ามีไลบรารีไหม
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import multiprocessing as mp
import queue
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ai.scheduler import Job, JobScheduler
from app.core.log import get_logger
from app.core.messages import Envelope

log = get_logger("ai")

STARTUP_TIMEOUT_S = 180.0   # import torch + เตรียม CUDA ครั้งแรกอาจนาน (ก่อนส่ง "ready" ไม่มี heartbeat)
MAX_ATTEMPTS = 2

EventHandler = Callable[[dict[str, Any]], None]


def ai_libs_present(models_config: dict[str, Any]) -> tuple[bool, str]:
    """มี torch + faster-whisper + demucs ให้ worker ใช้ไหม (ไม่ import จริง) คืน (พร้อมไหม, เหตุผลถ้าไม่พร้อม)
    ตรวจจากโฟลเดอร์จริงใน site_dir ก่อน (แน่นอนกว่า importlib) แล้วค่อยลองหาในสภาพแวดล้อมหลัก — เหตุผลที่คืนบอก path ที่ตรวจ ไว้ไล่บั๊ก"""
    site = str(models_config.get("site_dir") or "")
    for name in ("torch", "faster_whisper", "demucs"):
        if site and (Path(site) / name / "__init__.py").is_file():
            continue
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            where = f"site_dir={site!r} มีโฟลเดอร์={Path(site).is_dir() if site else False}" if site else "ไม่ได้ตั้ง site_dir ใน models.yaml"
            return False, f"ยังไม่ได้ติดตั้ง {name} ({where} · python={sys.executable})"
    return True, ""


class AiClient:
    """ใช้งาน: start() -> submit_align(...) -> รับผลผ่าน handler · stop() ตอนปิดโปรแกรม"""

    def __init__(self, models_config: dict[str, Any], stems_dir: Path | str | None = None,
                 on_status: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.models_config = models_config
        self.stems_dir = str(stems_dir or "")
        self.on_status = on_status or (lambda _s: None)
        self.scheduler = JobScheduler()
        self.available = False       # True เมื่อ worker ส่ง "ready"
        self.started = False         # True เมื่อเปิด worker แล้ว (ยังรอ ready อยู่ก็ได้) · False = ไม่มี AI ในเครื่องนี้
        self.device = ""
        self.last_error = ""
        self.degraded: list[str] = []
        self.vram_used_mb = 0
        self._ctx = mp.get_context("spawn")
        self._proc: Any = None
        self._rq: Any = None
        self._eq: Any = None
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}      # job_id -> {type, payload, handler, attempts, video_id}
        self._last_beat = 0.0
        self._started_at = 0.0
        self._ready = False
        self._starting = False
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    # วงจรชีวิต
    # ------------------------------------------------------------------
    def start(self) -> bool:
        """เปิด worker ถ้าเงื่อนไขพร้อม คืน True เมื่อเริ่มเปิดแล้ว (ยังไม่ได้แปลว่า ready — ดู available)"""
        with self._lock:
            if self.started or self._starting:
                return self.started
            self._starting = True
        try:
            return self._start()
        finally:
            self._starting = False

    def _start(self) -> bool:
        analysis_on = bool(self.models_config.get("analysis", {}).get("enabled", True))
        if not analysis_on:
            self.last_error = "ปิดการวิเคราะห์เสียงในตั้งค่า"
            return False
        ok, why = ai_libs_present(self.models_config)
        if not ok:
            self.last_error = why
            log.warning("AI ไม่พร้อม ใช้เวลาแบบประมาณ", extra={"data": {"why": why}})
            return False
        self._spawn()
        self.started = True
        self._stop.clear()
        for fn in (self._listen, self._watchdog):
            t = threading.Thread(target=fn, name=f"ai-{fn.__name__}", daemon=True)
            t.start()
            self._threads.append(t)
        return True

    def _spawn(self) -> None:
        from app.ai.worker import worker_main

        with self._lock:
            self._rq = self._ctx.Queue()
            self._eq = self._ctx.Queue()
            cfg = {"models": self.models_config, "stems_dir": self.stems_dir}
            self._proc = self._ctx.Process(target=worker_main, args=(self._rq, self._eq, cfg), name="synclyrics-ai", daemon=True)
            self._proc.start()
            self._started_at = self._last_beat = time.time()
            self._ready = False
            log.info("เปิด AI worker", extra={"data": {"pid": self._proc.pid}})

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            try:
                if self._rq is not None:
                    self._rq.put(Envelope.new("shutdown").to_dict())
            except Exception:  # noqa: BLE001
                pass
            proc = self._proc
        if proc is not None:
            proc.join(timeout=3.0)
            if proc.is_alive():
                proc.kill()
        self.available = False

    # ------------------------------------------------------------------
    # ส่งงาน
    # ------------------------------------------------------------------
    def submit_align(self, video_id: str, audio_path: str, lines: list[dict[str, Any]], language: str | None,
                     start_hint: float, handler: EventHandler) -> str:
        """ส่งงานจัดเวลาเนื้อเพลงจากเสียง (lines ว่าง = ถอดเสียงเป็นเนื้อเพลง) คืน job_id · handler รับ event ของงานนี้ทุกตัว"""
        payload = {"video_id": video_id, "audio_path": audio_path, "lines": lines, "language": language, "start_hint": start_hint}
        return self._submit("align_song", payload, handler)

    def submit_translate(self, video_id: str, lines: list[str], source_lang: str | None, target_lang: str, handler: EventHandler) -> str:
        return self._submit("translate", {"video_id": video_id, "lines": lines, "source_lang": source_lang, "target_lang": target_lang}, handler)

    def pending_types(self) -> set[str]:
        """ชนิดงานที่ยังค้างอยู่ (ส่งแล้วยังไม่จบ) — ใช้ให้งานเบื้องหลังที่ไม่เร่งด่วน (คำเน้น) รองานจัดเวลาให้เสร็จก่อน"""
        with self._lock:
            return {str(j.get("type")) for j in self._jobs.values()}

    def submit_emphasis(self, video_id: str, lines: list[str], handler: EventHandler) -> str:
        return self._submit("emphasis", {"video_id": video_id, "lines": lines}, handler)

    def _submit(self, type_: str, payload: dict[str, Any], handler: EventHandler) -> str:
        job_id = uuid.uuid4().hex[:12]
        payload = {**payload, "job_id": job_id}
        with self._lock:
            self._jobs[job_id] = {"type": type_, "payload": payload, "handler": handler, "attempts": 1, "video_id": payload.get("video_id")}
            if self._rq is not None:
                self._rq.put(Envelope.new(type_, payload).to_dict())
        return job_id

    def submit(self, job: Job) -> None:  # เข้ากันกับของเดิม (scheduler) — ตอนนี้ใช้ submit_align โดยตรง
        raise NotImplementedError("ใช้ submit_align/submit_translate")

    def cancel_video(self, video_id: str) -> None:
        """ข้ามเพลง/เปลี่ยนเพลง: ยกเลิกงานทั้งหมดของเพลงนั้น (worker หยุดที่ขอบช่วงถัดไป)"""
        with self._lock:
            ids = [j for j, v in self._jobs.items() if v.get("video_id") == video_id]
            for j in ids:
                self._jobs.pop(j, None)
            if self._rq is not None:
                self._rq.put(Envelope.new("cancel", {"video_id": video_id, "job_ids": ids}).to_dict())

    def on_seek(self, video_id: str, position_s: float) -> None:
        """ผลทยอยออกเป็นช่วงๆ เร็วพออยู่แล้ว (งานทั้งเพลง ~20-40 วิบน GPU) — ยังไม่เรียงลำดับตามตำแหน่ง seek"""

    # ------------------------------------------------------------------
    # thread ฟังผลและเฝ้า worker
    # ------------------------------------------------------------------
    def _listen(self) -> None:
        while not self._stop.is_set():
            eq = self._eq
            try:
                msg = eq.get(timeout=0.5)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                time.sleep(0.5)
                continue
            try:
                self._on_event(msg)
            except Exception:  # noqa: BLE001 — handler พัง ไม่ฆ่า thread ฟัง
                log.exception("จัดการ event ของ AI พัง")

    def _on_event(self, msg: dict[str, Any]) -> None:
        t, p = msg.get("type"), msg.get("payload", {})
        self._last_beat = time.time()
        if t == "heartbeat":
            self.vram_used_mb = int(p.get("vram_used_mb", 0))
            return
        if t == "ready":
            first = not self._ready
            self._ready = True
            self.available = True
            self.device = str(p.get("device", ""))
            self.on_status({"state": "ready", **p})
            if first:
                log.info("AI worker พร้อม", extra={"data": p})
                if self.models_config.get("preload", True) and int(p.get("vram_free_mb", 99999)) >= 3500:
                    with self._lock:   # โหลดโมเดลล่วงหน้าตอนเปิดโปรแกรม (ข้อ 5.3) เพลงแรกจะได้ไม่ต้องรอโหลด
                        if self._rq is not None:
                            self._rq.put(Envelope.new("warmup").to_dict())
            return
        if t == "degraded":
            self.degraded.append(str(p.get("action", "")))
            self.on_status({"state": "degraded", **p})
            return
        job_id = p.get("job_id")
        if t == "failed" and job_id == "setup":
            self.available = False
            self.last_error = str(p.get("error", ""))
            log.error("AI worker เตรียมไม่สำเร็จ", extra={"data": {"err": self.last_error}})
            self.on_status({"state": "unavailable", "error": self.last_error})
            return
        with self._lock:
            job = self._jobs.get(job_id) if job_id else None
        if job is None:
            return
        if t == "failed":
            self.last_error = str(p.get("error", ""))
            log.warning("งาน AI ล้มเหลว", extra={"data": {"job": job_id, "err": self.last_error}})
        job["handler"](msg)
        if t == "failed" or (t == "result" and p.get("kind", "").endswith("_final")) or (t == "progress" and p.get("cancelled")):
            with self._lock:
                self._jobs.pop(job_id, None)

    def _watchdog(self) -> None:
        timeout = float(self.models_config.get("watchdog_timeout_s", 20.0))
        while not self._stop.wait(1.0):
            proc = self._proc
            if proc is None:
                continue
            quiet = time.time() - self._last_beat
            limit = timeout if self._ready else STARTUP_TIMEOUT_S
            if proc.is_alive() and quiet <= limit:
                continue
            reason = "process ตาย" if not proc.is_alive() else f"ไม่มี heartbeat {quiet:.0f} วิ"
            log.error("AI worker ค้าง/ตาย -> เปิดใหม่", extra={"data": {"reason": reason}})
            self._restart()

    def _restart(self) -> None:
        with self._lock:
            old = self._proc
            if old is not None and old.is_alive():
                old.kill()
            self.available = False
            retry = []
            for job_id, job in list(self._jobs.items()):
                if job["attempts"] >= MAX_ATTEMPTS:
                    self._jobs.pop(job_id, None)
                    retry.append((job, False))
                else:
                    job["attempts"] += 1
                    retry.append((job, True))
        self._spawn()
        for job, again in retry:
            if again:
                with self._lock:
                    self._rq.put(Envelope.new(job["type"], job["payload"]).to_dict())
            else:
                job["handler"](Envelope.new("failed", {"job_id": job["payload"]["job_id"], "error": "AI ค้างซ้ำหลายครั้ง",
                                                       "traceback": "", "recoverable": False}).to_dict())
