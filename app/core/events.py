"""EventBus — ส่งเหตุการณ์ระหว่างส่วนต่างๆ โดยไม่ผูกกับ Qt

ส่วน logic (player, lyrics, automix, ai client) ส่งเหตุการณ์ผ่าน bus นี้
ฝั่ง UI มี adapter (app/ui/bus_adapter.py) แปลงเป็น Qt signal แบบ queued ไปเข้า UI thread
ทำให้ test logic ได้โดยไม่ต้องมี Qt และ logic ไม่ต้องรู้ว่าอยู่ thread ไหน

กฎ: handler ต้องทำงานสั้นๆ ห้ามบล็อก (handler รันใน thread ของผู้ส่ง)
handler พังห้ามทำให้ผู้ส่งพัง — bus จับ exception แล้ว log
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.core.log import get_logger

Handler = Callable[[str, dict[str, Any]], None]

# ชื่อเหตุการณ์มาตรฐาน (เพิ่มได้ ให้เขียนลง ARCHITECTURE.md §4 ด้วย)
TRACK_CHANGED = "track.changed"              # {video_id, track_ref, deck}
TRACK_META_READY = "track.meta_ready"        # {video_id, meta, cover_path, palette}
PLAYBACK_STATE = "playback.state"            # {playing, video_id}
LYRICS_READY = "lyrics.ready"                # {video_id, lyrics, source_label, candidates_count}
LYRICS_TIMING_UPDATED = "lyrics.timing"      # {video_id, start, end, words}  อัปเกรดเวลาทีละช่วง
ALIGN_COVERAGE = "lyrics.coverage"           # {video_id, ranges: [[start,end],...]}  แถบบน progress bar
ANALYSIS_READY = "analysis.ready"            # {video_id, analysis}
QUEUE_CHANGED = "queue.changed"              # {items, index}
PRELOAD_STATUS = "preload.status"            # {video_id, stage, fraction}
MIX_PLANNED = "mix.planned"                  # {plan}
MIX_STARTED = "mix.started"                  # {mix_id, plan}
MIX_FINISHED = "mix.finished"                # {mix_id}
RATING_REQUEST = "mix.rating_request"        # {mix_id, cover_a, cover_b}
AI_STATUS = "ai.status"                      # {state, vram_used_mb, queue}
BRIDGE_STATUS = "bridge.status"              # {connected, ext_version}
ERROR = "error"                              # {module, message, user_message, recoverable}


class EventBus:
    """pub/sub แบบ thread-safe ง่ายๆ"""

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.Lock()
        self._log = get_logger("app")

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        """สมัครรับเหตุการณ์ ("*" = ทุกเหตุการณ์) คืนฟังก์ชันสำหรับยกเลิก"""
        with self._lock:
            self._subs[topic].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._subs[topic]:
                    self._subs[topic].remove(handler)

        return unsubscribe

    def publish(self, topic: str, data: dict[str, Any] | None = None) -> None:
        """ส่งเหตุการณ์ให้ทุก handler ที่สมัครไว้"""
        payload = data or {}
        with self._lock:
            handlers = list(self._subs.get(topic, ())) + list(self._subs.get("*", ()))
        for h in handlers:
            try:
                h(topic, payload)
            except Exception:
                self._log.exception("event handler พัง", extra={"data": {"topic": topic}})
