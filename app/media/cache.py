"""cache เสียงชั่วคราวในเครื่อง: จำกัดขนาด (LRU) + ปุ่มล้าง (ข้อ 2.1, 9.3)

ไฟล์ PCM อยู่ที่ cache/audio/<videoId>.f32 (+ .meta.json) ตาราง audio_cache ใน DB บอกขนาดและเวลาใช้ล่าสุด
ลบเก่าสุดก่อน (last_access_at) จนไม่เกินขนาดที่ตั้ง ห้ามลบเพลงที่กำลังเล่น (protect)
ไฟล์ดาวน์โหลดดิบจาก yt-dlp (.webm/.m4a) ไม่เก็บ: ลบทิ้งทันทีหลังถอดรหัสเสร็จ
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

from app.core.log import get_logger

log = get_logger("media")
GB = 1024**3


def _remove_audio_files(audio_dir: Path, video_id: str) -> int:
    freed = 0
    for p in audio_dir.glob(f"{video_id}.*"):
        try:
            freed += p.stat().st_size
            p.unlink()
        except OSError:
            pass
    return freed


def touch(conn: sqlite3.Connection, video_id: str) -> None:
    """บันทึกว่าเพิ่งใช้ (LRU)"""
    conn.execute("UPDATE audio_cache SET last_access_at=? WHERE video_id=?", (time.time(), video_id))


def total_bytes(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COALESCE(SUM(bytes),0) FROM audio_cache").fetchone()[0])


def enforce_limit(conn: sqlite3.Connection, audio_dir: Path, max_gb: float,
                  protect: Iterable[str] = ()) -> list[str]:
    """ลบเพลงที่ไม่ได้ใช้นานสุดจนขนาดรวมไม่เกิน max_gb คืนรายการ videoId ที่ลบ"""
    limit = int(max_gb * GB)
    keep = set(protect)
    removed: list[str] = []
    total = total_bytes(conn)
    if total <= limit:
        return removed
    rows = conn.execute("SELECT video_id, bytes FROM audio_cache ORDER BY last_access_at ASC").fetchall()
    for r in rows:
        if total <= limit:
            break
        if r["video_id"] in keep:
            continue
        _remove_audio_files(audio_dir, r["video_id"])
        conn.execute("DELETE FROM audio_cache WHERE video_id=?", (r["video_id"],))
        total -= r["bytes"]
        removed.append(r["video_id"])
    if removed:
        log.info("ล้าง cache เสียงตามขนาดที่จำกัด", extra={"data": {"removed": len(removed)}})
    return removed


def clear_all(conn: sqlite3.Connection, audio_dir: Path, protect: Iterable[str] = ()) -> int:
    """ปุ่ม "ล้าง cache": ลบทั้งหมดยกเว้นเพลงที่กำลังเล่น คืนจำนวนไบต์ที่คืนพื้นที่"""
    keep = set(protect)
    freed = 0
    for r in conn.execute("SELECT video_id FROM audio_cache").fetchall():
        if r["video_id"] in keep:
            continue
        freed += _remove_audio_files(audio_dir, r["video_id"])
        conn.execute("DELETE FROM audio_cache WHERE video_id=?", (r["video_id"],))
    # ไฟล์กำพร้า (โหลดค้าง/crash กลางทาง) ที่ไม่มีแถวใน DB
    known = {r["video_id"] for r in conn.execute("SELECT video_id FROM audio_cache").fetchall()} | keep
    for p in audio_dir.glob("*"):
        if p.is_file() and p.name.split(".")[0] not in known:
            try:
                freed += p.stat().st_size
                p.unlink()
            except OSError:
                pass
    return freed


def register(conn: sqlite3.Connection, video_id: str, path: Path, audio_dir: Path, sample_rate: int,
             frames: int, source_format: str, complete: bool) -> None:
    """บันทึกไฟล์ PCM ลง audio_cache (ต้องมีแถวใน tracks ก่อน — LyricsService/controller สร้างให้)"""
    now = time.time()
    size = path.stat().st_size if path.exists() else frames * 8
    conn.execute(
        "INSERT INTO audio_cache(video_id, path, sample_rate, channels, frames, bytes, source_format, complete,"
        " created_at, last_access_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET "
        "path=excluded.path, sample_rate=excluded.sample_rate, frames=excluded.frames, bytes=excluded.bytes,"
        " source_format=excluded.source_format, complete=excluded.complete, last_access_at=excluded.last_access_at",
        (video_id, str(path.relative_to(audio_dir)) if path.is_relative_to(audio_dir) else path.name, sample_rate,
         2, frames, size, source_format, 1 if complete else 0, now, now),
    )
