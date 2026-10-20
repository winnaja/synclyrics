"""LyricsEmphasis — ฝั่ง process หลัก: ให้ AI (โมเดลภาษาในเครื่อง) เลือก "คำเน้น" ของเพลง แล้วส่งเข้า UI (ผู้ใช้สั่ง 2026-10-21)

คำเน้น = คำที่มีน้ำหนักทางอารมณ์/เป็นแก่นของเพลง (เช่น creep, belong, burning) — UI ขยาย+เรืองแสงตอนร้องถึงคำนั้น (ถ้าเปิด "คำเน้น")
ผลเก็บใน DB (ai_results kind='emphasis') ผูกกับข้อความเนื้อเพลง + โมเดล · ล้มเหลวเงียบๆ (ไม่มีคำเน้น)
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from app.ai.aligner import WAIT_AI_S, lyrics_key
from app.core import db as dbmod
from app.core import events as ev
from app.core.log import get_logger
from app.core.models import Lyrics

log = get_logger("ai")

KIND = "emphasis"
VERSION = 1


def norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def pick_emphasis(lines: list[str], answers: dict[int, str], max_ratio: float = 0.28) -> dict[str, str]:
    """คำต่อบรรทัดจากโมเดล (เกือบทุกบรรทัดมีคำ) -> เลือกเฉพาะบรรทัด "ไฮไลต์" จริง: {ข้อความบรรทัด(normalize): คำ}
    คะแนนบรรทัด: คำที่โมเดลเลือกซ้ำหลายบรรทัด = คำแก่นของเพลง (ฮุก) · คำท้ายบรรทัด · คำยาว · บรรทัดที่ซ้ำกันทั้งบรรทัดนับเป็นบรรทัดเดียว
    ให้ไม่เกิน max_ratio ของบรรทัดไม่ซ้ำ และห่างกันอย่างน้อย 2 บรรทัด (ไม่เน้นติดกันรัว)"""
    uniq: dict[str, int] = {}            # ข้อความ -> ดัชนีแรก
    for i, t in enumerate(lines):
        k = norm(t)
        if k and k not in uniq:
            uniq[k] = i
    freq: dict[str, int] = {}
    for i, w in answers.items():
        freq[norm(w)] = freq.get(norm(w), 0) + 1
    scored: list[tuple[float, int, str, str]] = []
    for k, i in uniq.items():
        w = answers.get(i)
        if not w:
            continue
        toks = lines[i].split()
        last = norm(toks[-1]) == norm(w) if toks else False
        s = min(freq.get(norm(w), 1), 6) + (0.8 if last else 0.0) + (0.4 if len(w) >= 5 else 0.0)
        scored.append((s, i, k, w))
    cap = max(2, int(round(len(uniq) * max_ratio)))
    chosen: dict[str, str] = {}
    used: list[int] = []
    for s, i, k, w in sorted(scored, key=lambda x: (-x[0], x[1])):
        if len(chosen) >= cap:
            break
        if any(abs(i - j) < 2 for j in used):
            continue
        chosen[k] = w
        used.append(i)
    return chosen


class LyricsEmphasis:
    def __init__(self, ai: Any, bus: Any, db_path: Path | str, models_config: dict[str, Any]) -> None:
        self.ai = ai
        self.bus = bus
        self.db_path = db_path
        self.cfg = models_config.get("emphasis", {})
        self._jobs: dict[str, str] = {}

    def cancel(self, video_id: str) -> None:
        if self._jobs.pop(video_id, None) is not None:
            try:
                self.ai.cancel_video(video_id)
            except Exception:  # noqa: BLE001
                pass

    def _load(self, video_id: str, key: str) -> dict[str, str] | None:
        try:
            conn = dbmod.connect(self.db_path)
            row = conn.execute("SELECT payload FROM ai_results WHERE video_id=? AND kind=? AND lyrics_key=?", (video_id, KIND, key)).fetchone()
            conn.close()
            if row:
                d = json.loads(row["payload"])
                if d.get("model") == self.cfg.get("model") and d.get("v") == VERSION:
                    return dict(d["emphasis"])
        except Exception:  # noqa: BLE001
            log.exception("อ่านคำเน้นจาก DB ไม่ได้")
        return None

    def _save(self, video_id: str, key: str, mapping: dict[str, str]) -> None:
        try:
            conn = dbmod.connect(self.db_path)
            conn.execute("INSERT OR REPLACE INTO ai_results(video_id, kind, lyrics_key, version, payload, created_at) VALUES(?,?,?,?,?,?)",
                         (video_id, KIND, key, VERSION, json.dumps({"model": self.cfg.get("model"), "v": VERSION, "emphasis": mapping},
                                                                    ensure_ascii=False), time.time()))
            conn.commit()
            conn.close()
        except Exception:  # noqa: BLE001
            log.exception("บันทึกคำเน้นลง DB ไม่ได้")

    def _publish(self, video_id: str, mapping: dict[str, str]) -> None:
        self.bus.publish(ev.EMPHASIS_READY, {"video_id": video_id, "emphasis": mapping})

    async def start(self, video_id: str, lyrics: Lyrics | None) -> None:
        try:
            await self._start(video_id, lyrics)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("เลือกคำเน้นด้วย AI ไม่สำเร็จ")

    async def _start(self, video_id: str, lyrics: Lyrics | None) -> None:
        if not self.cfg.get("enabled", True) or lyrics is None or len(lyrics.lines) < 4:
            return
        key = lyrics_key(lyrics)
        cached = await asyncio.to_thread(self._load, video_id, key)
        if cached is not None:
            self._publish(video_id, cached)
            return
        self.cancel(video_id)
        waited = 0.0
        while not getattr(self.ai, "available", False):
            if waited >= WAIT_AI_S or (waited >= 3.0 and not getattr(self.ai, "started", True) and not getattr(self.ai, "_starting", False)):
                return
            await asyncio.sleep(0.5)
            waited += 0.5
        lines = [ln.text for ln in lyrics.lines]

        def handler(msg: dict[str, Any]) -> None:
            if video_id not in self._jobs:
                return
            if msg.get("type") == "result" and msg.get("payload", {}).get("kind") == "emphasis_final":
                raw = msg["payload"]["data"].get("answers", {})
                self._jobs.pop(video_id, None)
                answers = {int(k): str(v) for k, v in raw.items() if str(k).isdigit()}
                mapping = pick_emphasis(lines, answers)
                self._save(video_id, key, mapping)
                if mapping:
                    self._publish(video_id, mapping)
            elif msg.get("type") == "failed":
                self._jobs.pop(video_id, None)

        self._jobs[video_id] = "pending"
        self._jobs[video_id] = self.ai.submit_emphasis(video_id, lines, handler)
