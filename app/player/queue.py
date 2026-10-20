"""คิวเพลงขั้นต่ำของเฟส 2 (คิวเต็มรูปแบบ ลากสลับ + preload เป็นเฟส 5)

คิวเป็นรายการ TrackRef + ตำแหน่งปัจจุบัน (index) · เพลงที่เล่นไปแล้วยังอยู่ในรายการ (กดย้อนกลับได้)
เหตุการณ์ QUEUE_CHANGED ส่งจากเจ้าของคิว (controller) ไม่ใช่จากที่นี่ — คลาสนี้ไม่รู้จัก bus
thread-safe: ใช้ lock เพราะถูกเรียกจากทั้ง UI thread (ส่วนขยาย) และ IO thread (เพลงจบ)
"""

from __future__ import annotations

import threading
from typing import Any

from app.core.models import TrackRef

MAX_ITEMS = 500  # กัน playlist ใหญ่เกินจนหน่วง


class PlayQueue:
    """รายการเพลงที่จะเล่น + ตำแหน่งปัจจุบัน"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: list[TrackRef] = []
        self._index = -1

    # ---------- อ่าน ----------
    @property
    def index(self) -> int:
        return self._index

    def items(self) -> list[TrackRef]:
        with self._lock:
            return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def current(self) -> TrackRef | None:
        with self._lock:
            return self._items[self._index] if 0 <= self._index < len(self._items) else None

    def has_next(self) -> bool:
        return self._index + 1 < len(self._items)

    def has_prev(self) -> bool:
        return self._index > 0

    # ---------- แก้ ----------
    def play_now(self, track: TrackRef) -> None:
        """ตั้งเพลงนี้เป็นเพลงปัจจุบัน: ถ้าอยู่ในคิวแล้วกระโดดไปที่นั่น ไม่งั้นแทรกถัดจากเพลงปัจจุบัน"""
        with self._lock:
            for i, t in enumerate(self._items):
                if t.video_id == track.video_id:
                    self._items[i] = self._merge(t, track)
                    self._index = i
                    return
            self._items.insert(self._index + 1, track)
            self._index += 1
            self._trim()

    def add(self, tracks: list[TrackRef], position: str = "end") -> int:
        """เพิ่มเพลง ("end" = ท้ายคิว, "next" = ถัดจากเพลงปัจจุบัน) เพลงซ้ำที่อยู่ข้างหน้าแล้วข้าม คืนจำนวนที่เพิ่ม"""
        with self._lock:
            ahead = {t.video_id for t in self._items[self._index + 1:]}
            fresh: list[TrackRef] = []
            for t in tracks:
                if t.video_id in ahead or any(t.video_id == f.video_id for f in fresh):
                    continue
                fresh.append(t)
            if self._items and 0 <= self._index < len(self._items) and fresh:
                fresh = [t for t in fresh if t.video_id != self._items[self._index].video_id]
            if position == "next":
                at = self._index + 1
                self._items[at:at] = fresh
            else:
                self._items.extend(fresh)
            self._trim()
            return len(fresh)

    def next(self) -> TrackRef | None:
        """เลื่อนไปเพลงถัดไป คืนเพลงนั้น (ไม่มี = None และตำแหน่งไม่ขยับ)"""
        with self._lock:
            if not self.has_next():
                return None
            self._index += 1
            return self._items[self._index]

    def prev(self) -> TrackRef | None:
        with self._lock:
            if not self.has_prev():
                return None
            self._index -= 1
            return self._items[self._index]

    def peek_next(self) -> TrackRef | None:
        """เพลงถัดไปโดยไม่ขยับตำแหน่ง (เฟส 5 ใช้ preload)"""
        with self._lock:
            return self._items[self._index + 1] if self.has_next() else None

    def move(self, src: int, dst: int) -> None:
        """ลากสลับลำดับ (ตำแหน่งปัจจุบันตามเพลงเดิม)"""
        with self._lock:
            n = len(self._items)
            if not (0 <= src < n and 0 <= dst < n) or src == dst:
                return
            cur = self.current()
            self._items.insert(dst, self._items.pop(src))
            if cur is not None:
                self._index = next(i for i, t in enumerate(self._items) if t is cur)

    def remove(self, index: int) -> None:
        with self._lock:
            if not 0 <= index < len(self._items):
                return
            del self._items[index]
            if index < self._index:
                self._index -= 1
            elif index == self._index:
                self._index = min(self._index, len(self._items) - 1)

    def clear_upcoming(self) -> None:
        with self._lock:
            del self._items[self._index + 1:]

    # ---------- บันทึก/กู้ ----------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"items": [t.to_dict() for t in self._items], "index": self._index}

    def restore(self, data: dict[str, Any]) -> None:
        """กู้จาก state.json — ข้อมูลพังบางส่วนให้ข้ามรายการนั้น ไม่ crash"""
        items: list[TrackRef] = []
        for raw in (data.get("items") or [])[:MAX_ITEMS]:
            try:
                items.append(TrackRef(**{k: v for k, v in raw.items() if k in TrackRef.__dataclass_fields__}))
            except (TypeError, AttributeError):
                continue
        with self._lock:
            self._items = items
            idx = data.get("index", -1)
            self._index = idx if isinstance(idx, int) and -1 <= idx < len(items) else len(items) - 1

    # ---------- ภายใน ----------
    @staticmethod
    def _merge(old: TrackRef, new: TrackRef) -> TrackRef:
        """ข้อมูลใหม่จากส่วนขยายสำคัญกว่า แต่ไม่ทิ้งช่องที่เติมไว้แล้ว"""
        out = TrackRef(**new.to_dict())
        out.title = out.title or old.title
        out.channel = out.channel or old.channel
        out.duration = out.duration or old.duration
        out.music_section = out.music_section or old.music_section
        out.thumbnail_url = out.thumbnail_url or old.thumbnail_url
        return out

    def _trim(self) -> None:
        extra = len(self._items) - MAX_ITEMS
        if extra > 0:  # ตัดจากหัวคิว (เพลงที่เล่นไปแล้ว) ก่อน
            cut = min(extra, max(self._index, 0))
            del self._items[:cut]
            self._index -= cut
            del self._items[MAX_ITEMS:]
