"""LyricsTranslator — ฝั่ง process หลัก: ส่งเนื้อเพลงทั้งเพลงไปแปลเป็นภาษาไทยด้วย AI แล้วส่งคำแปลเข้า UI (เฟส 4)

ผลเก็บใน DB (ai_results kind='translation:th') ผูกกับข้อความเนื้อเพลง + โมเดลแปล — เปิดเพลงเดิมซ้ำได้ทันที ไม่เรียก AI
ไม่แปลเมื่อ: เนื้อเพลงเป็นภาษาไทยอยู่แล้ว · มีคำแปลไทยจากแหล่งอยู่แล้ว · ปิด translate.enabled · ไม่มี AI
ล้มเหลวเงียบๆ (หน้าจอไม่มีคำแปลเฉยๆ — ข้อ 11.2)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.ai.aligner import WAIT_AI_S, lyrics_key
from app.core import db as dbmod
from app.core import events as ev
from app.core.log import get_logger
from app.core.models import Lyrics

log = get_logger("ai")

KIND = "translation:th"


def needs_translation(lyrics: Lyrics | None, enabled: bool = True) -> tuple[bool, str | None]:
    """คืน (ควรแปลไหม, ภาษาต้นทาง)"""
    if not enabled or lyrics is None or not lyrics.lines:
        return False, None
    from app.lyrics.thai import detect_language

    texts = [ln.text for ln in lyrics.lines]
    lang = lyrics.language or detect_language(" ".join(texts[:40]))
    if lang == "th":
        return False, lang
    have = [ln.translation for ln in lyrics.lines if ln.translation]
    if have and detect_language(" ".join(have[:40])) == "th":
        return False, lang          # มีคำแปลไทยจากแหล่งอยู่แล้ว
    return True, lang


class LyricsTranslator:
    def __init__(self, ai: Any, bus: Any, db_path: Path | str, models_config: dict[str, Any]) -> None:
        self.ai = ai
        self.bus = bus
        self.db_path = db_path
        self.cfg = models_config.get("translate", {})
        self._jobs: dict[str, str] = {}

    def cancel(self, video_id: str) -> None:
        if self._jobs.pop(video_id, None) is not None:
            try:
                self.ai.cancel_video(video_id)
            except Exception:  # noqa: BLE001
                pass

    # ---------- DB ----------
    def _load(self, video_id: str, key: str, n_lines: int) -> list[str] | None:
        try:
            conn = dbmod.connect(self.db_path)
            row = conn.execute("SELECT payload FROM ai_results WHERE video_id=? AND kind=? AND lyrics_key=?", (video_id, KIND, key)).fetchone()
            conn.close()
            if row:
                d = json.loads(row["payload"])
                if d.get("model") == self.cfg.get("model") and len(d.get("translations", [])) == n_lines:
                    return list(d["translations"])
        except Exception:  # noqa: BLE001
            log.exception("อ่านคำแปลจาก DB ไม่ได้")
        return None

    def _save(self, video_id: str, key: str, translations: list[str]) -> None:
        try:
            conn = dbmod.connect(self.db_path)
            conn.execute("INSERT OR REPLACE INTO ai_results(video_id, kind, lyrics_key, version, payload, created_at) VALUES(?,?,?,?,?,?)",
                         (video_id, KIND, key, 1, json.dumps({"model": self.cfg.get("model"), "translations": translations}, ensure_ascii=False),
                          time.time()))
            conn.commit()
            conn.close()
        except Exception:  # noqa: BLE001
            log.exception("บันทึกคำแปลลง DB ไม่ได้")

    def _publish(self, video_id: str, translations: list[str]) -> None:
        self.bus.publish(ev.TRANSLATION_READY, {"video_id": video_id, "translations": translations, "lang": "th"})

    # ---------- ทำงาน ----------
    async def start(self, video_id: str, lyrics: Lyrics | None) -> None:
        try:
            await self._start(video_id, lyrics)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("แปลเนื้อเพลงด้วย AI ไม่สำเร็จ")

    async def _start(self, video_id: str, lyrics: Lyrics | None) -> None:
        need, src = needs_translation(lyrics, bool(self.cfg.get("enabled", True)))
        if not need or lyrics is None:
            return
        self.cancel(video_id)
        key = lyrics_key(lyrics)
        cached = await asyncio.to_thread(self._load, video_id, key, len(lyrics.lines))
        if cached is not None:
            self._publish(video_id, cached)
            return
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
            if msg.get("type") == "result" and msg.get("payload", {}).get("kind") == "translate_final":
                tr = list(msg["payload"]["data"].get("translations", []))
                self._jobs.pop(video_id, None)
                if len(tr) == len(lines) and any(tr):
                    self._save(video_id, key, tr)
                    self._publish(video_id, tr)
            elif msg.get("type") == "failed":
                self._jobs.pop(video_id, None)

        self._jobs[video_id] = "pending"
        self._jobs[video_id] = self.ai.submit_translate(video_id, lines, src, str(self.cfg.get("target_lang", "tha_Thai")), handler)
