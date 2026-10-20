"""เรียก yt-dlp: ข้อมูลวิดีโอ, โหลดเสียง bestaudio, คำบรรยาย, ค้นหา (ข้อ 2.1)

ใช้ yt-dlp แบบ Python API ใน thread ของ IO (ไม่ใช่ UI thread)
cookies: ลอง cookiesfrombrowser=("chrome",) ก่อน -> ถ้า Chrome ล็อกไฟล์/ถอดรหัสไม่ได้
ใช้ paths.cookies_file (cookies.txt ที่ผู้ใช้ export เอง) -> ถ้าไม่มีทั้งคู่ เล่นแบบไม่ล็อกอิน + แจ้งผู้ใช้
เลือกสตรีมเสียง bitrate สูงสุดที่บัญชีเข้าถึงได้ (ตรวจ 2026-10-20: ไม่ว่าจะล็อกอินหรือไม่ได้สูงสุด opus ~137k เท่ากัน — cookies มีประโยชน์กับวิดีโอจำกัดอายุ/ต้องล็อกอิน)
YouTube ต้องใช้ JS runtime แก้โจทย์ n-challenge: ใช้ Node.js ที่อยู่ใน PATH (ผ่าน yt-dlp-ejs)

กฎความปลอดภัย: ห้าม log/คืนค่า cookies ใดๆ — ข้อความ error ผ่าน redact() เสมอ

yt-dlp อัปเดตตัวเองวันละครั้ง (ข้อ 11.2) ผ่าน pip ใน background — บันทึกเวลาล่าสุดใน kv
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.errors import CookiesError, MediaError
from app.core.log import get_logger, redact
from app.core.models import TrackRef

log = get_logger("media")

CookieMode = Literal["chrome", "file", "none"]
_COOKIE_FAIL_HINTS = ("cookie", "dpapi", "decrypt", "database is locked", "permission")


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


def _format_label(fmt: dict[str, Any] | None) -> str:
    if not fmt:
        return ""
    abr = fmt.get("abr")
    return f"{fmt.get('format_id', '?')} {fmt.get('acodec', '?')} {int(abr)}k" if abr else (
        f"{fmt.get('format_id', '?')} {fmt.get('acodec', '?')}")


def _thumb(info: dict[str, Any]) -> str | None:
    vid = info.get("id")
    return info.get("thumbnail") or (f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg" if vid else None)


# วิธีโหลดตามลำดับเมื่อเจอ 403: ปกติ -> ไม่แบ่ง chunk -> ไคลเอนต์ YouTube อื่น
FALLBACK_VARIANTS: tuple[dict[str, Any], ...] = (
    {},
    {"http_chunk_size": None},
    {"http_chunk_size": None, "extractor_args": {"youtube": {"player_client": ["tv", "web_safari"]}}},
)


class YouTubeClient:
    """ห่อ yt-dlp ให้มี fallback ครบ"""

    def __init__(self, cookies_file: Path, ffmpeg_dir: Path | None = None) -> None:
        self.cookies_file = cookies_file
        self.ffmpeg_dir = ffmpeg_dir
        self.cookie_mode: CookieMode = "chrome"
        self._lock = threading.Lock()
        self.last_cookie_error: str = ""  # ข้อความอธิบาย (ผ่าน redact แล้ว) ให้ wizard/health check แสดง

    # ---------- ตัวเลือกพื้นฐาน ----------
    def _opts(self, mode: CookieMode, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
            "socket_timeout": 15, "retries": 3, "fragment_retries": 3,
            "http_chunk_size": 4 * 1024 * 1024,
        }
        node = shutil.which("node")
        if node:
            opts["js_runtimes"] = {"node": {"path": node}}
        if self.ffmpeg_dir:
            opts["ffmpeg_location"] = str(self.ffmpeg_dir)
        if mode == "chrome":
            opts["cookiesfrombrowser"] = ("chrome",)
        elif mode == "file" and self.cookies_file.exists():
            opts["cookiefile"] = str(self.cookies_file)
        opts.update(extra)
        return opts

    def _mode_order(self) -> list[CookieMode]:
        """ลองโหมดที่เคยใช้ได้ก่อน แล้วค่อยลดระดับ · มี cookies.txt = ลองไฟล์ก่อน Chrome (cookies จาก Chrome ที่เปิดอยู่
        อ่านไม่ได้บนเครื่องผู้ใช้ และการลองครั้งแรกเสียเวลา ~1.5 วิทุกครั้งที่เปิดโปรแกรม): file -> chrome -> none"""
        order: list[CookieMode] = ["file", "chrome", "none"] if self.cookies_file.exists() else ["chrome", "file", "none"]
        if self.cookie_mode in order:
            order.remove(self.cookie_mode)
            order.insert(0, self.cookie_mode)
        if not self.cookies_file.exists() and "file" in order:
            order.remove("file")
        return order

    def _run(self, work: Callable[[Any], Any], **extra: Any) -> tuple[Any, CookieMode]:
        """รัน work(ydl) ด้วยโหมด cookies ที่ใช้ได้ ลดระดับอัตโนมัติเมื่อ cookies มีปัญหา"""
        import yt_dlp

        last: Exception | None = None
        for mode in self._mode_order():
            try:
                with yt_dlp.YoutubeDL(self._opts(mode, **extra)) as ydl:
                    result = work(ydl)
                with self._lock:
                    if mode != self.cookie_mode:
                        log.info("เปลี่ยนโหมด cookies", extra={"data": {"mode": mode}})
                    self.cookie_mode = mode
                return result, mode
            except Exception as e:
                msg = redact(str(e))
                last = e
                if mode != "none" and any(h in msg.lower() for h in _COOKIE_FAIL_HINTS):
                    self.last_cookie_error = msg[:300]
                    log.warning("ใช้ cookies ไม่ได้ ลองวิธีถัดไป",
                                extra={"data": {"mode": mode, "err": msg[:300]}})
                    continue
                if mode != "none" and "Sign in" in msg:  # ไม่ล็อกอิน -> ลองโหมดที่มี cookies อื่น
                    continue
                raise self._wrap(e) from e
        raise self._wrap(last) if last else MediaError("media", "โหลดจาก YouTube ไม่ได้")

    @staticmethod
    def _wrap(e: Exception) -> MediaError:
        msg = redact(str(e))
        low = msg.lower()
        if "video unavailable" in low or "private video" in low:
            return MediaError("media", "วิดีโอนี้เปิดไม่ได้ (ถูกลบ/ส่วนตัว/ไม่อยู่ในประเทศนี้)", hint=msg[:200])
        if "sign in" in low or "confirm you" in low:
            return MediaError("media", "YouTube ขอให้ล็อกอิน", hint="ตั้งค่า cookies ของ Chrome หรือ cookies.txt", )
        if "http error 403" in low or "403" in low.split("\n")[0]:
            return MediaError("media", "YouTube ปฏิเสธการโหลด (403)", hint="อัปเดต yt-dlp แล้วลองใหม่")
        return MediaError("media", "โหลดข้อมูลจาก YouTube ไม่สำเร็จ", hint=msg[:200])

    # ---------- API ----------
    def fetch_info(self, video_id: str) -> VideoInfo:
        """ข้อมูลวิดีโอ + metadata เพลง (track/artist/album) + รายการคำบรรยาย"""
        url = f"https://www.youtube.com/watch?v={video_id}"
        info, _ = self._run(lambda ydl: ydl.extract_info(url, download=False),
                            format="bestaudio/best", skip_download=True)
        return self._to_video_info(video_id, info)

    @staticmethod
    def _to_video_info(video_id: str, info: dict[str, Any]) -> VideoInfo:
        meta = {k: info[k] for k in ("track", "artist", "album", "release_year", "creator", "alt_title")
                if info.get(k)}
        track = TrackRef(
            video_id=video_id, title=info.get("title") or "", channel=info.get("channel") or info.get("uploader") or "",
            duration=float(info["duration"]) if info.get("duration") else None,
            ytdlp_meta=meta, thumbnail_url=_thumb(info), added_from="ytdlp",
        )
        subs = {lang: fmts for lang, fmts in (info.get("subtitles") or {}).items() if lang != "live_chat"}
        return VideoInfo(
            track=track, duration=track.duration or 0.0,
            audio_format=_format_label(next(iter(info.get("requested_formats") or []), None) or info),
            subtitles=subs, chapters=info.get("chapters") or [], is_live=bool(info.get("is_live")),
        )

    def fetch_and_download(self, video_id: str, target_dir: Path,
                           on_info: Callable[[VideoInfo], None] | None = None,
                           on_progress: Callable[[float], None] | None = None) -> tuple[VideoInfo, DownloadResult]:
        """ดึงข้อมูล + โหลดเสียงด้วยการ extract ครั้งเดียว (เร็วกว่าเรียก fetch_info แล้ว download_audio)

        on_info ถูกเรียกทันทีที่รู้ข้อมูลวิดีโอ (ก่อนโหลดเสียง) เพื่อให้เริ่มหาเนื้อเพลง/ปกขนานกับการโหลด
        """
        target_dir.mkdir(parents=True, exist_ok=True)
        for stale in target_dir.glob(f"{video_id}.*"):
            if stale.suffix in (".part", ".ytdl"):
                stale.unlink(missing_ok=True)
        notified = False

        def hook(d: dict[str, Any]) -> None:
            if on_progress and d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    on_progress(min(1.0, d.get("downloaded_bytes", 0) / total))

        def work(ydl: Any) -> tuple[VideoInfo, dict[str, Any]]:
            nonlocal notified
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            vi = self._to_video_info(video_id, info)
            if on_info and not notified:
                notified = True
                on_info(vi)
            done = ydl.process_ie_result(info, download=True)
            return vi, done

        # 403 เป็นครั้งคราว (googlevideo ปฏิเสธลิงก์/ไคลเอนต์) -> ลองซ้ำด้วยวิธีที่ต่างกันตามลำดับ
        last_err: MediaError | None = None
        result: tuple[Any, CookieMode] | None = None
        for variant in FALLBACK_VARIANTS:
            try:
                result = self._run(
                    work, format="bestaudio/best", outtmpl=str(target_dir / "%(id)s.%(ext)s"),
                    progress_hooks=[hook], overwrites=False, **variant,
                )
                break
            except MediaError as e:
                last_err = e
                if "403" not in e.user_message:
                    raise
                log.warning("ถูกปฏิเสธ 403 ลองวิธีโหลดอื่น", extra={"data": {"variant": list(variant)}})
                for stale in target_dir.glob(f"{video_id}.*"):
                    stale.unlink(missing_ok=True)
        if result is None:
            raise last_err or MediaError("media", "โหลดเสียงไม่สำเร็จ")
        (vi, done), mode = result
        path = self._find_downloaded(target_dir, video_id, done)
        if path is None:
            raise MediaError("media", "โหลดเสียงแล้วแต่ไม่พบไฟล์", hint=str(target_dir))
        return vi, DownloadResult(path=path, audio_format=_format_label(done), cookie_mode=mode)

    def download_audio(self, video_id: str, target_dir: Path,
                       on_progress: Callable[[float], None] | None = None) -> DownloadResult:
        """โหลด bestaudio เป็นไฟล์ (ไม่แปลงรูปแบบ — decoder ถอดเอง)"""
        target_dir.mkdir(parents=True, exist_ok=True)
        for stale in target_dir.glob(f"{video_id}.*"):
            if stale.suffix in (".part", ".ytdl"):
                stale.unlink(missing_ok=True)

        def hook(d: dict[str, Any]) -> None:
            if on_progress and d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    on_progress(min(1.0, d.get("downloaded_bytes", 0) / total))

        url = f"https://www.youtube.com/watch?v={video_id}"
        info, mode = self._run(
            lambda ydl: ydl.extract_info(url, download=True),
            format="bestaudio/best", outtmpl=str(target_dir / "%(id)s.%(ext)s"),
            progress_hooks=[hook], overwrites=False,
        )
        path = self._find_downloaded(target_dir, video_id, info)
        if path is None:
            raise MediaError("media", "โหลดเสียงแล้วแต่ไม่พบไฟล์", hint=str(target_dir))
        return DownloadResult(path=path, audio_format=_format_label(info), cookie_mode=mode)

    @staticmethod
    def _find_downloaded(target_dir: Path, video_id: str, info: dict[str, Any]) -> Path | None:
        for d in info.get("requested_downloads") or []:
            p = d.get("filepath")
            if p and Path(p).exists():
                return Path(p)
        cands = [p for p in target_dir.glob(f"{video_id}.*") if p.suffix not in (".part", ".ytdl", ".f32")]
        return max(cands, key=lambda p: p.stat().st_mtime) if cands else None

    def fetch_subtitles(self, video_id: str, lang: str) -> str | None:
        """คำบรรยายที่คนทำ (ไม่ใช่ auto-generated) เป็นข้อความ VTT"""
        import httpx

        info = self.fetch_info(video_id)
        for fmt in info.subtitles.get(lang, []):
            if fmt.get("ext") == "vtt" and fmt.get("url"):
                r = httpx.get(fmt["url"], timeout=10, follow_redirects=True)
                return r.text if r.status_code == 200 else None
        return None

    def search(self, query: str, limit: int = 10) -> list[TrackRef]:
        """ช่องค้นหาในโปรแกรม (ytsearch)"""
        res, _ = self._run(
            lambda ydl: ydl.extract_info(f"ytsearch{limit}:{query}", download=False),
            extract_flat=True,
        )
        out: list[TrackRef] = []
        for e in (res or {}).get("entries") or []:
            if not e or not e.get("id"):
                continue
            out.append(TrackRef(
                video_id=e["id"], title=e.get("title") or "", channel=e.get("channel") or e.get("uploader") or "",
                duration=float(e["duration"]) if e.get("duration") else None,
                thumbnail_url=f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg", added_from="search",
            ))
        return out

    def expand_playlist(self, playlist_id: str) -> list[TrackRef]:
        raise NotImplementedError("เฟส 2")

    def test_cookies(self) -> tuple[CookieMode, str]:
        """ใช้ใน wizard/health check: คืนโหมดที่ใช้ได้ + ข้อความอธิบาย (ห้ามมีค่า cookie)"""
        import yt_dlp

        notes: list[str] = []
        for mode in ("chrome", "file"):
            if mode == "file" and not self.cookies_file.exists():
                notes.append("ไม่มีไฟล์ cookies.txt")
                continue
            try:
                with yt_dlp.YoutubeDL(self._opts(mode)) as ydl:
                    # yt-dlp โหลด cookies แบบขี้เกียจ ต้องแตะ cookiejar ถึงจะอ่านจริง (ไม่งั้นจะรายงาน "ได้" ทั้งที่อ่านไม่ได้)
                    n = sum(1 for c in ydl.cookiejar if "youtube" in c.domain or "google" in c.domain)
                if n == 0:
                    raise ValueError("ไม่พบ cookies ของ YouTube/Google ในแหล่งนี้ (ยังไม่ได้ล็อกอิน?)")
                self.cookie_mode = mode
                return mode, (f"อ่าน cookies จาก Chrome ได้ ({n} รายการ)" if mode == "chrome"
                              else f"ใช้ cookies.txt ที่ export เอง ({n} รายการ)")
            except Exception as e:
                notes.append(f"{mode}: {redact(str(e))[:160]}")
        self.cookie_mode = "none"
        return "none", (
            "ดึง cookies ไม่ได้ จึงเล่นแบบไม่ล็อกอิน (เสียงที่ดึงได้ไม่ต่างกัน แต่วิดีโอจำกัดอายุ/ต้องล็อกอินจะโหลดไม่ได้) — "
            "ปิด Chrome แล้วลองใหม่ หรือ export cookies.txt ไปไว้ที่ " + str(self.cookies_file)
            + " | " + " ; ".join(notes)
        )


def self_update_ytdlp() -> str | None:
    """อัปเดต yt-dlp (pip install -U yt-dlp) คืนเวอร์ชันใหม่ หรือ None ถ้าไม่ได้อัปเดต — เฟส 8"""
    raise NotImplementedError("เฟส 8")


async def fetch_oembed(video_id: str, client: Any = None, timeout_s: float = 4.0) -> tuple[str, str] | None:
    """ชื่อวิดีโอ + ชื่อช่องที่ถูกต้องจาก oEmbed ของ YouTube (เร็ว ~0.2 วิ ไม่ต้องใช้ key/cookies/yt-dlp)

    ใช้ยืนยันว่าชื่อเพลงตรงกับ videoId (ไม่เชื่อชื่อที่ส่วนขยายอ่านจากหน้าเว็บ ซึ่งอาจเป็นของเพลงก่อนหน้าตอนเปลี่ยนเพลง)
    คืน (title, author) หรือ None ถ้าดึงไม่ได้ (วิดีโอส่วนตัว/ถูกลบ/ไม่มีเน็ต)
    """
    own = client is None
    if own:
        import httpx

        client = httpx.AsyncClient(follow_redirects=True)
    try:
        r = await client.get("https://www.youtube.com/oembed",
                             params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
                             timeout=timeout_s)
        if r.status_code != 200:
            return None
        d = r.json()
        title = str(d.get("title") or "").strip()
        return (title, str(d.get("author_name") or "").strip()) if title else None
    except Exception as e:  # noqa: BLE001
        log.debug("oEmbed ไม่สำเร็จ", extra={"data": {"err": repr(e)}})
        return None
    finally:
        if own:
            await client.aclose()


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
