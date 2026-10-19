"""ระบบ plugin ของแหล่งเนื้อเพลง (ข้อ 4.2, 11.1)

เพิ่มแหล่งใหม่ = สร้างไฟล์เดียวใน app/lyrics/sources/ ที่มีคลาสสืบทอด LyricsSource
และประกาศ SOURCE = <คลาสนั้น> ไว้ระดับ module — discover() จะเจอเอง
ลบแหล่ง = ลบไฟล์ (หรือปิดในหน้าตั้งค่า)

กฎของทุกแหล่ง:
  - search() ต้องจบภายใน timeout_s ของตัวเอง ห้ามโยน exception ออกไป (คืน [] แทน)
    ยกเว้น SourceUnavailable ที่ service จะ log และข้ามเงียบๆ
  - ห้ามดึงจากหน้าผลค้นหา Google หรือเว็บเนื้อเพลงที่ห้าม scraping
  - ใช้ httpx.AsyncClient ที่ service ส่งให้ (ใช้ connection ร่วมกัน)
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from app.core.models import Lyrics, TrackMeta, TrackRef

if TYPE_CHECKING:
    import httpx


@dataclass(slots=True)
class LyricsQuery:
    """ทุกอย่างที่แหล่งเนื้อเพลงอาจใช้ค้น"""

    track: TrackRef
    meta: TrackMeta
    duration: float | None
    # ข้อมูลเสริมที่บางแหล่งต้องใช้ (เช่น รายการคำบรรยายจาก yt-dlp)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LyricsCandidate:
    """ผลหนึ่งรายการจากแหล่งหนึ่ง (ยังไม่ให้คะแนน)"""

    lyrics: Lyrics
    matched_title: str = ""
    matched_artist: str = ""
    matched_duration: float | None = None
    score: float = 0.0  # scoring.py เป็นคนเติม
    score_detail: dict[str, float] = field(default_factory=dict)


class LyricsSource(ABC):
    """แม่แบบของแหล่งเนื้อเพลง"""

    name: ClassVar[str]                 # id ใช้ใน config/DB เช่น "lrclib"
    display_name: ClassVar[str]         # แสดงมุมจอ เช่น "LRCLIB"
    enabled_by_default: ClassVar[bool] = True
    timeout_s: ClassVar[float] = 6.0
    # แหล่งที่ไม่เป็นทางการ (NetEase, QQ) พังได้บ่อย — service จะไม่แจ้งผู้ใช้เวลาพัง
    unofficial: ClassVar[bool] = False

    @abstractmethod
    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        """ค้นและคืนผลทั้งหมดที่น่าจะใช่ (parse เป็น Lyrics แล้ว)"""


def discover() -> dict[str, type[LyricsSource]]:
    """หา plugin ทุกตัวใน package นี้ (ไฟล์ที่ประกาศ SOURCE) — ไฟล์ที่ import พังจะถูกข้าม"""
    import app.lyrics.sources as pkg

    found: dict[str, type[LyricsSource]] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        try:
            mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
        except Exception:  # plugin พังห้ามทำให้ทั้งระบบพัง
            from app.core.log import get_logger

            get_logger("lyrics").exception("โหลด plugin ไม่ได้", extra={"data": {"plugin": info.name}})
            continue
        cls = getattr(mod, "SOURCE", None)
        if isinstance(cls, type) and issubclass(cls, LyricsSource):
            found[cls.name] = cls
    return found
