"""ตำแหน่งไฟล์ทั้งหมดของโปรแกรม (ที่เดียว ห้าม hard-code path ที่อื่น)

ข้อมูลผู้ใช้อยู่ที่ %LOCALAPPDATA%\\SyncLyrics เสมอ ยกเว้นตั้ง env SYNCLYRICS_HOME
(ใช้ใน test และโหมด portable) — โค้ดในโฟลเดอร์โปรเจกต์ (config/, themes/) เป็นค่าเริ่มต้นแบบอ่านอย่างเดียว
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# รากของโค้ด (C:\lyrics หรือโฟลเดอร์ที่ PyInstaller แตกไฟล์)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class AppPaths:
    """รวม path ทั้งหมด สร้างผ่าน get_paths() เท่านั้น"""

    home: Path

    # --- อ่านอย่างเดียว (มากับโปรแกรม) ---
    @property
    def default_config_dir(self) -> Path:
        """config ค่าเริ่มต้นที่มากับโปรแกรม"""
        return PROJECT_ROOT / "config"

    @property
    def builtin_themes_dir(self) -> Path:
        """ธีมสำเร็จรูป"""
        return PROJECT_ROOT / "themes"

    @property
    def extension_src_dir(self) -> Path:
        """ต้นฉบับส่วนขยาย Chrome ที่มากับโปรแกรม"""
        return PROJECT_ROOT / "extension"

    # --- เขียนได้ (ของผู้ใช้) ---
    @property
    def user_config_dir(self) -> Path:
        """config ที่ผู้ใช้แก้แล้ว (ทับค่าเริ่มต้นทีละไฟล์)"""
        return self.home / "config"

    @property
    def settings_file(self) -> Path:
        """การตั้งค่าของผู้ใช้ (หน้า Settings)"""
        return self.home / "settings.yaml"

    @property
    def user_themes_dir(self) -> Path:
        return self.home / "themes"

    @property
    def db_file(self) -> Path:
        """SQLite ไฟล์เดียวของทั้งโปรแกรม"""
        return self.home / "synclyrics.sqlite3"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def audio_cache_dir(self) -> Path:
        """PCM ที่ถอดรหัสแล้ว (<videoId>.f32) — ลบได้ตลอด มีจำกัดขนาด"""
        return self.cache_dir / "audio"

    @property
    def stems_cache_dir(self) -> Path:
        """stems จาก Demucs แยกตาม videoId"""
        return self.cache_dir / "stems"

    @property
    def art_cache_dir(self) -> Path:
        return self.cache_dir / "art"

    @property
    def models_dir(self) -> Path:
        """น้ำหนักโมเดล AI (Demucs, whisper, MMS)"""
        return self.home / "models"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def backups_dir(self) -> Path:
        """สำรองระบบเรียนรู้ AutoMix วันละครั้ง เก็บ 7 วัน"""
        return self.home / "backups"

    @property
    def renders_dir(self) -> Path:
        """WAV ที่ render จาก Mix Lab"""
        return self.home / "renders"

    @property
    def installed_extension_dir(self) -> Path:
        """โฟลเดอร์ถาวรที่ผู้ใช้ Load unpacked (ข้อ 10.5)"""
        return self.home / "extension"

    @property
    def state_file(self) -> Path:
        """สถานะล่าสุด (เพลง ตำแหน่ง) เขียนทุก 5 วิ — ใช้กู้คืนหลัง crash"""
        return self.home / "state.json"

    @property
    def cookies_file(self) -> Path:
        """cookies.txt สำรองที่ผู้ใช้ export เอง — ห้ามส่งออก ห้ามใส่ในรายงาน"""
        return self.home / "secrets" / "cookies.txt"

    def ensure(self) -> None:
        """สร้างโฟลเดอร์ที่เขียนได้ทั้งหมด (เรียกครั้งเดียวตอนเปิดโปรแกรม)"""
        for d in (
            self.home,
            self.user_config_dir,
            self.user_themes_dir,
            self.audio_cache_dir,
            self.stems_cache_dir,
            self.art_cache_dir,
            self.models_dir,
            self.logs_dir,
            self.backups_dir,
            self.renders_dir,
            self.cookies_file.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)


def get_paths() -> AppPaths:
    """คืน AppPaths ตาม env SYNCLYRICS_HOME หรือ %LOCALAPPDATA%\\SyncLyrics"""
    override = os.environ.get("SYNCLYRICS_HOME")
    if override:
        return AppPaths(home=Path(override))
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return AppPaths(home=Path(base) / "SyncLyrics")
