"""เรียก yt-dlp: ข้อมูลวิดีโอ, โหลดเสียง bestaudio, คำบรรยาย, ค้นหา (ข้อ 2.1)

ใช้ yt-dlp แบบ Python API ใน thread ของ IO (ไม่ใช่ UI thread)
cookies: ลอง cookiesfrombrowser=("chrome",) ก่อน -> ถ้า Chrome ล็อกไฟล์/ถอดรหัสไม่ได้
ใช้ paths.cookies_file (cookies.txt ที่ผู้ใช้ export เอง) -> ถ้าไม่มีทั้งคู่ เล่นแบบไม่ล็อกอิน + แจ้งผู้ใช้
เลือกสตรีมเสียง bitrate สูงสุดที่บัญชีเข้าถึงได้ (Premium มักได้ opus/aac ที่สูงกว่า)

yt-dlp อัปเดตตัวเองวันละครั้ง (ข้อ 11.2) ผ่าน pip ใน background — บันทึกเวลาล่าสุดใน kv
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.models import TrackRef

CookieMode = Literal["chrome", "file", "none"]


@dataclass(slots=True)
class VideoInfo:
    """ข้อมูลที่ต้องใช้จาก yt-dlp (ไม่เก็บ dict ดิบทั้งก้อน เพราะอาจมีข้อมูลส่วนตัว)"""

    track: TrackRef
    duration: float
    audio_format: str = ""          # เช่น "251 opus 160k"
    subtitles: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # ไม่รวม auto-generated
    chapters: list[dict[str, Any]] = field(default_factory=list)
    is_live: bool = False


@dataclass(slots=True)
class DownloadResult:
    path: Path
    audio_format: str
    cookie_mode: CookieMode


class YouTubeClient:
    """ห่อ yt-dlp ให้มี fallback ครบ — เฟส 1"""

    def __init__(self, cookies_file: Path, ffmpeg_dir: Path | None = None) -> None:
        self.cookies_file = cookies_file
        self.ffmpeg_dir = ffmpeg_dir
        self.cookie_mode: CookieMode = "chrome"

    def fetch_info(self, video_id: str) -> VideoInfo:
        """ข้อมูลวิดีโอ + metadata เพลง (track/artist/album) + รายการคำบรรยาย"""
        raise NotImplementedError("เฟส 1")

    def download_audio(self, video_id: str, target_dir: Path,
                       on_progress: Callable[[float], None] | None = None) -> DownloadResult:
        """โหลด bestaudio เป็นไฟล์ (ไม่แปลงรูปแบบ — decoder ถอดเอง)"""
        raise NotImplementedError("เฟส 1")

    def fetch_subtitles(self, video_id: str, lang: str) -> str | None:
        """คำบรรยายที่คนทำ (ไม่ใช่ auto-generated) เป็นข้อความ VTT/SRV3"""
        raise NotImplementedError("เฟส 1")

    def search(self, query: str, limit: int = 10) -> list[TrackRef]:
        """ช่องค้นหาในโปรแกรม (ytsearch)"""
        raise NotImplementedError("เฟส 1")

    def expand_playlist(self, playlist_id: str) -> list[TrackRef]:
        raise NotImplementedError("เฟส 2")

    def test_cookies(self) -> tuple[CookieMode, str]:
        """ใช้ใน wizard/health check: คืนโหมดที่ใช้ได้ + ข้อความอธิบาย (ห้ามมีค่า cookie)"""
        raise NotImplementedError("เฟส 1")


def self_update_ytdlp() -> str | None:
    """อัปเดต yt-dlp (pip install -U yt-dlp) คืนเวอร์ชันใหม่ หรือ None ถ้าไม่ได้อัปเดต — เฟส 8"""
    raise NotImplementedError("เฟส 8")


def parse_video_id(text: str) -> str | None:
    """ดึง videoId จากลิงก์/ข้อความที่วาง (Ctrl+V, ลากลิงก์) — รองรับ watch?v=, youtu.be/, music., shorts/"""
    import re

    m = re.search(
        r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", text
    )
    if m:
        return m.group(1)
    t = text.strip()
    return t if re.fullmatch(r"[A-Za-z0-9_-]{11}", t) else None
