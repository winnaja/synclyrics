"""จุดเริ่มของ AI worker process (ข้อ 5.3)

worker_main(requests, events, config) รันใน process แยก (multiprocessing spawn):
  1. ตั้ง priority ต่ำ, ต่อ site-packages ของ AI (env.py), เลือก device (cuda/cpu), torch.inference_mode, cudnn.benchmark
  2. โหลดโมเดลตอนใช้ครั้งแรก (หรือเมื่อได้ "warmup") และค้างไว้ตาม models.yaml แล้วส่ง "ready"
  3. วนรับงานทีละงาน ส่ง "progress"/"result"/"failed" · งานยาวตรวจคำสั่ง "cancel" ระหว่างช่วง
  4. heartbeat ทุก 1 วิ จาก thread แยก (watchdog ฝั่ง client ใช้)
  5. VRAM ใกล้งบ: ลดขนาดโมเดล (whisper -> int8_float16) แล้วส่ง "degraded"
  6. จบแต่ละเพลง: torch.cuda.empty_cache()

งานหลัก `align_song` (ทยอยทีละช่วง ~30 วิ): ถอดรหัสเสียง -> Demucs แยกเสียงร้อง -> Whisper ฟังคำ+เวลา
  -> match.py จับคู่กับเนื้อเพลงสำเร็จรูป -> ส่งผลบางส่วน (kind=align_partial) ทุกช่วง แล้วผลสุดท้าย (align_final)
  ไม่มีเนื้อเพลงเลย = ใช้ transcript เป็นเนื้อเพลง · เสียงร้อง/transcript เก็บไว้ใน cache/stems/<videoId> ใช้ซ้ำตอนสลับเนื้อเพลง

กฎ: worker ไม่แตะ SQLite, ไม่ถือ state สำคัญ (ฆ่าทิ้งได้ทุกเมื่อ)
ห้าม import ไฟล์นี้จาก process หลัก (ยกเว้นส่งชื่อฟังก์ชันให้ multiprocessing) — torch import ได้ที่นี่ที่เดียว
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any

from app.core.messages import Envelope


class _Cancelled(Exception):
    """งานถูกยกเลิก (ข้ามเพลง/เปลี่ยนเพลง)"""


class Worker:
    def __init__(self, requests: Any, events: Any, config: dict[str, Any]) -> None:
        self.rq = requests
        self.ev = events
        self.cfg = config
        self.mcfg: dict[str, Any] = config.get("models", {})
        self.pending: deque[dict[str, Any]] = deque()
        self.cancel_jobs: set[str] = set()
        self.busy: str | None = None
        self.stop = False
        self.device = "cpu"
        self._torch: Any = None
        self._demucs: Any = None
        self._whisper: Any = None
        self._whisper_ctype = ""
        self._nllb: Any = None
        self._mms: Any = None
        self._mms_failed = False

    # ------------------------------------------------------------------
    # ช่องทางข้อความ
    # ------------------------------------------------------------------
    def emit(self, type_: str, payload: dict[str, Any]) -> None:
        self.ev.put(Envelope.new(type_, payload).to_dict())

    def _drain(self) -> None:
        """อ่านคำสั่งที่รออยู่ทั้งหมด: cancel/shutdown ทำทันที งานอื่นต่อคิว"""
        while True:
            try:
                msg = self.rq.get_nowait()
            except queue.Empty:
                return
            except (EOFError, OSError):
                self.stop = True
                return
            t, p = msg.get("type"), msg.get("payload", {})
            if t == "cancel":
                # ยกเลิกตาม job_id เท่านั้น (ไม่จำ video_id ถาวร: งานใหม่ของเพลงเดิมที่ส่งตามมาต้องไม่ถูกยกเลิกไปด้วย)
                self.cancel_jobs.update(p.get("job_ids") or [])
                vid = p.get("video_id")
                self.pending = deque(m for m in self.pending
                                     if m.get("payload", {}).get("job_id") not in self.cancel_jobs
                                     and not (vid and m.get("payload", {}).get("video_id") == vid and m.get("payload", {}).get("job_id") in (p.get("job_ids") or [])))
            elif t == "shutdown":
                self.stop = True
            else:
                self.pending.append(msg)

    def _is_cancelled(self, p: dict[str, Any]) -> bool:
        return p.get("job_id") in self.cancel_jobs

    def _check_cancel(self, p: dict[str, Any]) -> None:
        self._drain()
        if self.stop or self._is_cancelled(p):
            raise _Cancelled

    # ------------------------------------------------------------------
    # โมเดลและ GPU
    # ------------------------------------------------------------------
    def setup(self) -> None:
        from app.ai.env import setup_ai_environment

        info = setup_ai_environment(self.mcfg)
        try:  # priority ต่ำกว่า UI (ข้อ 5.3) — ไม่มี psutil ก็ข้าม
            import psutil

            if sys.platform == "win32" and self.mcfg.get("worker_priority", "below_normal") != "normal":
                cls = psutil.IDLE_PRIORITY_CLASS if self.mcfg.get("worker_priority") == "idle" else psutil.BELOW_NORMAL_PRIORITY_CLASS
                psutil.Process().nice(cls)
        except Exception:  # noqa: BLE001
            pass
        import torch

        self._torch = torch
        want = self.mcfg.get("device", "auto")
        self.device = "cuda" if (want in ("auto", "cuda") and torch.cuda.is_available()) else "cpu"
        if self.device == "cuda":
            torch.backends.cudnn.benchmark = bool(self.mcfg.get("cudnn_benchmark", True))
            torch.set_float32_matmul_precision("high")
        self._env_info = info

    def vram_mb(self) -> tuple[int, int]:
        """(ว่าง, ทั้งหมด) MB — CPU = (0, 0)"""
        if self.device != "cuda":
            return 0, 0
        free, total = self._torch.cuda.mem_get_info()
        return int(free / 2**20), int(total / 2**20)

    def demucs(self) -> Any:
        if self._demucs is None and self.mcfg.get("demucs", {}).get("enabled", True):
            from app.ai.pipeline import stems

            self._demucs = stems.load_model(self.mcfg.get("demucs", {}), self.device)
        return self._demucs

    def whisper(self) -> Any:
        if self._whisper is None:
            from app.ai.pipeline import transcribe

            wcfg = dict(self.mcfg.get("whisper", {}))
            free, _ = self.vram_mb()
            if self.device == "cuda" and 0 < free < 3000 and wcfg.get("compute_type") == "float16":
                wcfg["compute_type"] = wcfg.get("fallback_compute_type", "int8_float16")
                self.emit("degraded", {"reason": f"VRAM ว่างเหลือ {free} MB", "action": "whisper -> " + wcfg["compute_type"]})
            md = self.mcfg.get("model_dir") or ""
            self._whisper = transcribe.load_model(wcfg, self.device, download_root=str(Path(md) / "whisper") if md else None)
            self._whisper_ctype = str(wcfg.get("compute_type"))
        return self._whisper

    def whisper_pipeline(self) -> Any:
        """faster-whisper BatchedInferencePipeline ครอบโมเดล Whisper ที่โหลดอยู่ (ถอดทั้งเพลงแบบ batch)"""
        if getattr(self, "_wpipe", None) is None or getattr(self, "_wpipe_for", None) is not self._whisper:
            from faster_whisper import BatchedInferencePipeline

            model = self.whisper()
            self._wpipe = BatchedInferencePipeline(model=model)
            self._wpipe_for = model
        return self._wpipe

    def mms(self) -> Any:
        """MMS_FA สำหรับเกลาเวลาคำ — โหลดไม่ได้ครั้งเดียวก็เลิกลอง (ใช้เวลาจาก Whisper ต่อ ไม่พังทั้งงาน)"""
        if self._mms is None and not self._mms_failed and self.mcfg.get("align", {}).get("enabled", True):
            try:
                from app.ai.pipeline import align

                self._mms = align.load_model(self.mcfg.get("align", {}), self.device)
            except Exception as e:  # noqa: BLE001
                self._mms_failed = True
                self.emit("degraded", {"reason": f"โหลด MMS_FA ไม่ได้: {e}", "action": "ใช้เวลาคำจาก Whisper"})
        return self._mms

    def _refine(self, res: Any, lines_in: list[Any], vocals16: Any, language: str | None, filled: list[tuple[float, float]],
                refined: dict[int, dict[str, Any]]) -> None:
        """เกลาเวลาคำของบรรทัดที่จับคู่ได้ด้วย forced alignment (เฉพาะบรรทัดที่เสียงร้องช่วงนั้นพร้อมแล้ว) · ผลจำไว้ไม่คำนวณซ้ำ"""
        mms = self.mms()
        if mms is None:
            return
        from app.ai.pipeline import align

        merged: list[list[float]] = []
        for a, b in sorted(filled):
            if merged and a <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for i, ln in enumerate(res.lines):
            if not ln.resolved or not lines_in[i].words:
                continue
            prev = refined.get(i)
            if prev is not None and abs(prev["coarse"] - ln.start) < 0.4:
                ln.words, ln.start, ln.end = prev["spans"], prev["spans"][0][0], prev["spans"][-1][1]
                continue
            lo, hi = ln.start - align.EDGE_S, ln.end + align.EDGE_S
            if not any(a <= lo and hi <= b for a, b in merged):
                continue
            spans = align.align_line(mms, vocals16, ln.start, ln.end, lines_in[i].words, language)
            if spans and align.line_confidence(spans) >= mms["min_confidence"]:
                refined[i] = {"coarse": ln.start, "spans": spans}
                ln.words, ln.start, ln.end = spans, spans[0][0], spans[-1][1]
        self._merge_global(res, lines_in, vocals16, language, mms)
        # บรรทัดที่จับคู่กับ transcript ไม่ได้ (เวลาแค่ประมาณจากต้นฉบับ): ลองให้ MMS_FA ฟังเสียงร้องในช่วงที่คาดไว้ (กว้างขึ้น ±2.5 วิ)
        # ผ่านเมื่อมั่นใจสูงกว่าเกณฑ์ปกติ และไม่ข้ามลำดับ -> กลายเป็นเวลาจากเสียงจริง แทนที่การเดา
        prev_end = -1e9
        for i, ln in enumerate(res.lines):
            if ln.resolved or not lines_in[i].words or not ln.words:
                prev_end = max(prev_end, ln.end) if ln.words else prev_end
                continue
            lo, hi = ln.start - 2.5, ln.end + 2.5
            if not any(a <= lo and hi + align.EDGE_S <= b for a, b in merged):
                continue
            spans = align.align_line(mms, vocals16, lo, hi, lines_in[i].words, language)
            if spans and align.line_confidence(spans) >= mms["min_confidence"] + 0.1 and spans[0][0] >= prev_end - 0.5                     and spans[-1][1] - spans[0][0] <= max(8.0, 3.0 * max(0.5, ln.end - ln.start)):
                ln.words, ln.start, ln.end, ln.resolved = spans, spans[0][0], spans[-1][1], True
                ln.quality = align.line_confidence(spans)
            prev_end = max(prev_end, ln.end)

    def _merge_global(self, res: Any, lines_in: list[Any], vocals16: Any, language: str | None, mms: dict[str, Any]) -> None:
        """จัดเวลาทั้งเพลงด้วย CTC (ไม่พึ่ง Whisper) แล้วรวมกับผลจับคู่ Whisper ต่อบรรทัด:
          · ตรงกัน (ต่าง ≤ 1.5 วิ) = คงผลเดิม (หลักฐาน 2 ทางเห็นพ้อง)
          · ไม่ตรงกัน = ให้ MMS ฟังเสียงตรงช่วงของทั้งสองฝั่งแล้วเลือกช่วงที่ "ข้อความเนื้อเพลงเข้ากับเสียงมากกว่า" (ต้องดีกว่าอย่างน้อย 0.15)
          · บรรทัดที่ Whisper จับคู่ไม่ได้ = รับผล CTC เมื่อมั่นใจ ≥ เกณฑ์ และไม่ข้ามลำดับ"""
        from app.ai.pipeline import align

        acfg = self.mcfg.get("align", {})
        if not acfg.get("global_align", False):
            return
        try:
            glob = align.align_global(mms, vocals16, [ln.words for ln in lines_in], language)
        except Exception as e:  # noqa: BLE001 — ไม่พังทั้งงาน (เช่น VRAM ไม่พอ): ใช้ผลเดิม
            self.emit("degraded", {"reason": f"จัดเวลาทั้งเพลงด้วย CTC ไม่สำเร็จ: {e}", "action": "ใช้ผลจากการจับคู่ Whisper"})
            return
        thr = float(acfg.get("global_min_confidence", 0.5))
        min_gain = float(acfg.get("global_switch_gain", 0.15))

        def local(i: int, start: float, end: float) -> list[tuple[float, float, float]] | None:
            return align.align_line(mms, vocals16, start - 0.5, end + 0.5, lines_in[i].words, language)

        prev_end = -1e9
        for i, ln in enumerate(res.lines):
            g = glob[i]
            if g is None or not ln.words or not lines_in[i].words:
                if ln.words:
                    prev_end = max(prev_end, ln.end)
                continue
            gs, ge = g[0][0], g[-1][1]
            plausible = ge - gs <= max(10.0, 4.0 * max(0.5, ln.end - ln.start))
            if ln.resolved:
                if abs(gs - ln.start) > 1.5 and plausible:
                    cg = local(i, gs, ge)
                    cw = local(i, ln.start, ln.end)
                    conf_g = align.line_confidence(cg) if cg else 0.0
                    conf_w = align.line_confidence(cw) if cw else 0.0
                    if cg and conf_g >= thr and conf_g >= conf_w + min_gain and gs >= prev_end - 0.5:
                        ln.words, ln.start, ln.end, ln.quality = cg, cg[0][0], cg[-1][1], conf_g
            else:
                cg = local(i, gs, ge) if plausible else None
                conf_g = max(align.line_confidence(cg) if cg else 0.0, 0.0)
                if cg and conf_g >= thr and cg[0][0] >= prev_end - 0.5:
                    ln.words, ln.start, ln.end, ln.resolved, ln.quality = cg, cg[0][0], cg[-1][1], True, conf_g
            prev_end = max(prev_end, ln.end)

    def unload_whisper(self) -> None:
        self._whisper = None
        self._wpipe = None
        if self.device == "cuda":
            self._torch.cuda.empty_cache()

    def warmup(self) -> None:
        import numpy as np

        from app.ai.pipeline import stems, transcribe

        t0 = time.time()
        silence = np.zeros((44100 * 4, 2), dtype=np.float32)
        dm = self.demucs()
        if dm is not None:
            stems.separate_vocals(dm, silence, self.device, self.mcfg.get("demucs", {}))
        transcribe.transcribe_window(self.whisper(), np.zeros(16000 * 3, dtype=np.float32), None, self.mcfg.get("whisper", {}))
        self.emit("progress", {"job_id": "warmup", "fraction": 1.0, "seconds": round(time.time() - t0, 1)})

    # ------------------------------------------------------------------
    # งาน: จัดเวลาเนื้อเพลงจากเสียง
    # ------------------------------------------------------------------
    def job_align_song(self, p: dict[str, Any]) -> None:
        import numpy as np

        from app.ai import cache
        from app.ai.pipeline import audio, stems, transcribe
        from app.ai.pipeline.match import (InLine, TWord, clean_transcript, group_words_into_lines, match_lines,
                                           reconstruct_by_transcript, transcript_reliable, fill_missing_lines)
        from app.ai.pipeline.match import NOSPACE_LANGS
        from app.ai.pipeline.vocal_activity import vocal_segments

        job_id, vid = p["job_id"], p["video_id"]
        acfg = self.mcfg.get("analysis", {})
        win_s, ctx_s, sr = float(acfg.get("window_s", 30.0)), float(acfg.get("context_s", 3.0)), int(acfg.get("sample_rate", 44100))
        max_song = float(acfg.get("max_song_s", 900.0))
        lines_in = [InLine(words=list(ln["words"]), start=ln.get("start"), end=ln.get("end"),
                           word_times=[tuple(x) for x in ln["word_times"]] if ln.get("word_times") else None)
                    for ln in p.get("lines", [])]
        mode = "match" if lines_in else "transcribe"
        language = p.get("language")
        stems_dir = Path(self.cfg["stems_dir"]) / vid
        stems_dir.mkdir(parents=True, exist_ok=True)
        tkey = cache.transcript_key(self.mcfg)

        all_words: list[TWord] = []
        vsegs: list[tuple[float, float]] = []
        duration = 0.0
        cached = cache.load_transcript(stems_dir / "transcript.json", tkey)
        if cached is not None:
            all_words = [TWord(*w) for w in cached["words"]]
            vsegs = [tuple(x) for x in cached["vocal_segments"]]  # type: ignore[misc]
            duration = float(cached["duration"])
            language = language or cached.get("language")
            self.emit("progress", {"job_id": job_id, "fraction": 0.9, "cached": True})
        else:
            stereo = audio.decode(p["audio_path"], sr, 2, max_seconds=max_song + 1)
            duration = len(stereo) / sr
            if duration > max_song:
                self.emit("failed", {"job_id": job_id, "error": f"ยาว {duration:.0f} วิ เกินกำหนด ไม่ใช่เพลง", "traceback": "", "recoverable": False})
                return
            dm, wm = self.demucs(), self.whisper()
            wcfg = self.mcfg.get("whisper", {})
            n_win = max(1, int(np.ceil(duration / win_s)))
            hint = min(max(0.0, float(p.get("start_hint", 0.0))), duration)
            first = min(n_win - 1, int(hint // win_s))
            order = list(range(first, n_win)) + list(range(0, first))      # เริ่มจากช่วงที่กำลังฟัง แล้วไปข้างหน้า แล้วย้อนกลับมา
            vocals16 = np.zeros(int(duration * 16000) + 32000, dtype=np.float32)
            covered: list[list[float]] = []
            filled: list[tuple[float, float]] = []
            refined: dict[int, dict[str, Any]] = {}
            fast = bool(acfg.get("batched_whisper", True))
            if fast:   # Demucs ทุกช่วงก่อน แล้วถอดเสียงทั้งเพลงครั้งเดียวแบบ batch (เร็วกว่า ~4 เท่า) — ไม่มีผลทยอยระหว่างทาง แต่ทั้งงานสั้นลงมาก
                self._check_cancel(p)
                # แยกเสียงร้องทั้งเพลงครั้งเดียว (Demucs หั่นช่วง 7 วิภายในเอง VRAM คงที่) — ไม่ซ้ำช่วงบริบทหัวท้ายของแบบทีละช่วง (ประหยัด ~20%)
                voc = stems.separate_vocals(dm, stereo, self.device, self.mcfg.get("demucs", {})) if dm is not None else stereo
                v16_all = stems.to_mono_16k(voc, sr, self.device)
                n16 = min(len(v16_all), len(vocals16))
                vocals16[:n16] = v16_all[:n16]
                self.emit("progress", {"job_id": job_id, "fraction": 0.6})
                self._check_cancel(p)
                all_words, lang = transcribe.transcribe_full(self.whisper_pipeline(), vocals16[:int(duration * 16000)], language, wcfg)
                language = language or lang
                covered = [[0.0, duration]]
                filled = [(0.0, duration)]
                self.emit("progress", {"job_id": job_id, "fraction": 0.9})
            else:
                for done, k in enumerate(order, 1):
                    self._check_cancel(p)
                    c0, c1 = k * win_s, min(duration, (k + 1) * win_s)
                    e0, e1 = max(0.0, c0 - ctx_s), min(duration, c1 + ctx_s)
                    seg = stereo[int(e0 * sr):int(e1 * sr)]
                    if dm is not None:
                        seg = stems.separate_vocals(dm, seg, self.device, self.mcfg.get("demucs", {}))
                    v16 = stems.to_mono_16k(seg, sr, self.device)
                    i0 = int(e0 * 16000)
                    vocals16[i0:i0 + len(v16)] = v16
                    words, lang = transcribe.transcribe_window(wm, v16, language, wcfg, t_offset=e0)
                    language = language or lang
                    last = k == n_win - 1
                    all_words.extend(w for w in words if c0 <= (w.start + w.end) / 2 < (c1 if not last else duration + 1))
                    covered.append([c0, c1])
                    filled.append((e0, e1))
                    all_words.sort(key=lambda w: w.start)
                    if mode == "match":
                        res = match_lines(lines_in, clean_transcript(all_words))
                        self._refine(res, lines_in, vocals16, language, filled, refined)
                        self.emit("result", {"job_id": job_id, "kind": "align_partial", "data": self._pack(vid, res, only_resolved=True) | {
                            "covered": sorted(covered), "windows_done": done, "windows_total": n_win, "language": language}})
                    self.emit("progress", {"job_id": job_id, "fraction": done / n_win * 0.9})
            vsegs = vocal_segments(vocals16[:int(duration * 16000)], 16000)
            try:
                import numpy as _np

                _np.save(stems_dir / "vocals16k.npy", vocals16[:int(duration * 16000)].astype(_np.float16))
            except OSError:
                pass
            cache.save_transcript(stems_dir / "transcript.json", tkey, all_words, vsegs, duration, language)

        # ---- ผลสุดท้าย ----
        self._check_cancel(p)
        if mode == "match":
            # CTC ทั้งเพลง (เสียงร้อง + ข้อความเนื้อเพลงตรงๆ) เป็นอันดับแรก: เร็ว (~1 วิ/เพลง) และวัดได้แม่นกว่าเส้นทาง Whisper (เฉลยรายคำ: ≤0.3 วิ 86% เทียบ 79%)
            # ใช้เมื่อผ่านการตรวจกับเวลาเดิมของเนื้อเพลง ไม่ผ่าน (โครงสร้างต่าง/ไม่มีเวลาเดิม) = เส้นทาง Whisper + MMS เดิม
            res = None
            if acfg.get("ctc_first", True):
                voice16 = vocals16[:int(duration * 16000)] if cached is None else self._load_vocals(stems_dir)
                mms = self.mms() if voice16 is not None else None
                if mms is not None:
                    try:
                        from app.ai.pipeline import align as _align
                        from app.ai.pipeline.match import ctc_to_result

                        res = ctc_to_result(_align.align_global(mms, voice16, [ln.words for ln in lines_in], language), lines_in)
                    except Exception as e:  # noqa: BLE001 — เช่น VRAM ไม่พอ: ใช้เส้นทาง Whisper
                        self.emit("degraded", {"reason": f"CTC ทั้งเพลงไม่สำเร็จ: {e}", "action": "ใช้ Whisper + MMS รายบรรทัด"})
                        res = None
            if res is None:
                res = match_lines(lines_in, clean_transcript(all_words))
                if cached is None:
                    self._refine(res, lines_in, vocals16, language, filled, refined)
                else:   # transcript จาก cache: ใช้เสียงร้องที่เก็บไว้เกลาเวลาคำ (ถ้ามีไฟล์)
                    v16 = self._load_vocals(stems_dir)
                    if v16 is not None:
                        self._refine(res, lines_in, v16, language, [(0.0, len(v16) / 16000)], {})
            data = self._pack(vid, res, only_resolved=False)
            data["version_mismatch"] = res.coverage < float(acfg.get("min_coverage", 0.25))
            prefer_heard = bool(acfg.get("prefer_heard", True))   # ผู้ใช้สั่ง: ใช้ "เสียงที่ AI ได้ยิน" เป็นหลัก เนื้อเพลงเว็บใช้แก้คำที่ตรงกันเท่านั้น
            if (prefer_heard or res.coverage < float(acfg.get("reconstruct_below", 0.5))) and transcript_reliable(all_words):
                # โครงสร้างเพลงต่างจากเนื้อเพลง (รีมิกซ์/คนละเวอร์ชัน): จับคู่เรียงลำดับไม่ได้ -> สร้างบรรทัดตามลำดับที่ร้องจริงจากเสียง
                # แล้วใช้ข้อความเนื้อเพลงสำเร็จรูปแทนเฉพาะบรรทัดที่ตรงกัน (สะกดถูก) — เวลาถูกเสมอเพราะมาจากเสียง
                rr = reconstruct_by_transcript(lines_in, all_words, nospace=language in NOSPACE_LANGS, web_only=not prefer_heard)
                rr = fill_missing_lines(rr, lines_in, [tuple(x) for x in vsegs], duration)   # บรรทัดที่ AI ฟังไม่ได้ยิน แต่มีเสียงร้องจริง: เติมจากเนื้อเพลงเว็บ
                gain = float(acfg.get("reconstruct_gain", 0.08))
                # สร้างตามเสียงจริงเมื่อ: ได้ข้อความตรงเนื้อเพลงเพิ่มชัดเจน (โครงสร้างต่าง) หรือเนื้อเพลงแทบไม่ตรงเลย (ผิดเวอร์ชัน/คนละเพลง — ถอดเสียงดีกว่าเนื้อผิด)
                if rr.lines and (prefer_heard or rr.coverage >= res.coverage + gain or res.coverage < float(acfg.get("min_coverage", 0.25))):
                    data = {"video_id": vid, "coverage": round(rr.coverage, 4), "mono_coverage": round(res.coverage, 4), "offset_s": None,
                            "scale": None, "notes": ["reconstructed"], "version_mismatch": False,
                            "lines": [{"i": i, "start": ln.start, "end": ln.end, "resolved": True, "quality": 1.0, "src": ln.src,
                                       "text_words": ln.text_words, "words": [list(w) for w in ln.words]} for i, ln in enumerate(rr.lines)]}
                    mode = "reconstruct"
        else:
            nospace = language in NOSPACE_LANGS
            auto = group_words_into_lines(clean_transcript(all_words), max_words=30 if nospace else 9, max_chars=36 if nospace else 44)
            data = {"video_id": vid, "coverage": 1.0 if all_words else 0.0, "offset_s": None, "scale": None, "notes": [],
                    "lines": [{"i": i, "start": ln.start, "end": ln.end, "text_words": ln.words, "resolved": True, "quality": 1.0,
                               "words": [[a, b, 0.8] for a, b in (ln.word_times or [])]} for i, ln in enumerate(auto)]}
        data.update({"mode": mode, "language": language, "duration": duration, "vocal_segments": [list(s) for s in vsegs],
                     "transcript_words": len(all_words)})
        if acfg.get("snap_to_voice", True):
            voice = vocals16[:int(duration * 16000)] if cached is None else self._load_vocals(stems_dir)
            if voice is not None:
                from app.ai.pipeline.match import retime_unresolved
                from app.ai.pipeline.vocal_activity import classify_backing
                from app.ai.pipeline.vocal_activity import compact_line_outliers, remap_curves, snap_line_onset, snap_words_to_voice

                for ln in data.get("lines", []):
                    if ln.get("words") and ln.get("resolved", True):
                        old = [list(w) for w in ln["words"]]
                        ln["words"] = snap_words_to_voice(snap_line_onset(compact_line_outliers(ln["words"]), voice), voice)
                        if ln.get("curves"):
                            ln["curves"] = remap_curves(ln["curves"], old, ln["words"])
                        ln["start"] = ln["words"][0][0]
                        ln["end"] = ln["words"][-1][1]
                if data.get("mode") == "match":
                    retime_unresolved(data["lines"], lines_in)
                if acfg.get("heard_extras", True) and data.get("mode") in ("match", "reconstruct") and all_words:
                    from app.ai.pipeline.match import heard_extras

                    base_n = len(lines_in)
                    for k, ex in enumerate(heard_extras(data["lines"], lines_in, all_words, nospace=language in NOSPACE_LANGS)):
                        ex["i"] = base_n + 100000 + k
                        data["lines"].append(ex)
                if acfg.get("detect_backing", True) and data.get("mode") != "transcribe":
                    try:
                        view = [{"start": ln["start"], "end": ln["end"],
                                 "words": ln.get("text_words") or (list(lines_in[ln["i"]].words) if ln["i"] < len(lines_in) else [])}
                                for ln in data.get("lines", [])]
                        for ln, is_bg in zip(data.get("lines", []), classify_backing(view, voice)):
                            if is_bg and ln.get("resolved", True):
                                ln["voice"] = "background"
                    except Exception:  # noqa: BLE001 — ตรวจเสียงประสานไม่ได้ = แสดงเป็นบรรทัดปกติ ไม่พังทั้งงาน
                        pass
        self.emit("result", {"job_id": job_id, "kind": "align_final", "data": data})
        self.emit("progress", {"job_id": job_id, "fraction": 1.0})
        if self.mcfg.get("empty_cache_after_track", True) and self.device == "cuda":
            self._torch.cuda.empty_cache()
        if not self.mcfg.get("whisper", {}).get("keep_loaded", True):
            self.unload_whisper()

    @staticmethod
    def _load_vocals(stems_dir: Path) -> Any:
        try:
            import numpy as np

            return np.load(stems_dir / "vocals16k.npy").astype("float32")
        except (OSError, ValueError):
            return None

    @staticmethod
    def _pack(vid: str, res: Any, only_resolved: bool) -> dict[str, Any]:
        lines = [{"i": i, "start": ln.start, "end": ln.end, "words": [list(w) for w in ln.words], "resolved": ln.resolved,
                  "quality": round(ln.quality, 3), "curves": [getattr(w, "curve", None) for w in ln.words]}
                 for i, ln in enumerate(res.lines) if ln.resolved or not only_resolved]
        return {"video_id": vid, "lines": lines, "coverage": round(res.coverage, 4), "offset_s": res.offset_s, "scale": res.scale,
                "notes": list(res.notes)}

    # ------------------------------------------------------------------
    # วนรับงาน
    # ------------------------------------------------------------------
    def handle(self, msg: dict[str, Any]) -> None:
        t, p = msg.get("type"), msg.get("payload", {})
        if t == "warmup":
            self.warmup()
        elif t == "align_song":
            self.job_align_song(p)
        elif t == "emphasis":
            from app.ai import emphasis_job

            emphasis_job.run(self, p)
        elif t == "translate":
            from app.ai import translate_job

            translate_job.run(self, p)
        elif t == "status":
            free, total = self.vram_mb()
            self.emit("ready", {"device": self.device, "vram_total_mb": total, "vram_free_mb": free,
                                "models": {"demucs": self._demucs is not None, "whisper": self._whisper_ctype or None}})

    def run(self) -> None:
        try:
            self.setup()
        except Exception as e:  # noqa: BLE001 — torch ไม่พร้อม = รายงานแล้วออก (client ใช้โหมดไม่มี AI)
            self.emit("failed", {"job_id": "setup", "error": f"เตรียม AI ไม่สำเร็จ: {e}", "traceback": traceback.format_exc(), "recoverable": False})
            return
        threading.Thread(target=self._heartbeat, daemon=True).start()
        free, total = self.vram_mb()
        self.emit("ready", {"device": self.device, "vram_total_mb": total, "vram_free_mb": free, "models": {}})
        while not self.stop:
            if not self.pending:
                try:
                    self.pending.append(self.rq.get(timeout=0.5))
                except queue.Empty:
                    continue
                except (EOFError, OSError):
                    break
            self._drain()
            if not self.pending:
                continue
            msg = self.pending.popleft()
            p = msg.get("payload", {})
            if self._is_cancelled(p):
                continue
            self.busy = p.get("job_id") or msg.get("type")
            try:
                self.handle(msg)
            except _Cancelled:
                self.emit("progress", {"job_id": p.get("job_id", ""), "fraction": 0.0, "cancelled": True})
            except Exception as e:  # noqa: BLE001 — งานเดียวพังไม่ทำให้ worker ตาย
                recoverable = not isinstance(e, MemoryError) and "out of memory" not in str(e).lower()
                self.emit("failed", {"job_id": p.get("job_id", ""), "error": str(e), "traceback": traceback.format_exc(),
                                     "recoverable": recoverable})
                if not recoverable and self.device == "cuda":
                    self._torch.cuda.empty_cache()
            finally:
                self.busy = None

    def _heartbeat(self) -> None:
        while not self.stop:
            try:
                used = 0
                if self.device == "cuda":
                    free, total = self.vram_mb()
                    used = total - free
                self.emit("heartbeat", {"busy_job": self.busy, "vram_used_mb": used})
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)


def worker_main(requests: Any, events: Any, config: dict[str, Any]) -> None:
    """จุดเข้าของ process (multiprocessing.Process(target=worker_main, args=(rq, eq, config)))"""
    from app.core.streams import ensure_std_streams

    ensure_std_streams()
    Worker(requests, events, config).run()
