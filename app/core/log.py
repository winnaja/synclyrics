"""log แบบมีโครงสร้าง (JSON lines) แยกไฟล์ตาม module เก็บ 7 วันล่าสุด

ใช้: log = get_logger("audio"); log.info("underrun", extra={"data": {"frames": 512}})
ไฟล์: logs/<module>-YYYY-MM-DD.jsonl  หนึ่งบรรทัด = หนึ่ง event

ห้ามเรียก logger ใน audio callback (มี I/O และ lock) — callback ให้นับสถิติใส่ตัวแปรแทน
ห้าม log cookies / token / path ที่มีชื่อผู้ใช้เต็มๆ (ใช้ redact())
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
import threading
import traceback
from collections import deque
from pathlib import Path
from typing import Any

# ชื่อ module ที่รู้จัก (ใช้เป็นชื่อไฟล์ log และในหน้า debug)
MODULES: tuple[str, ...] = (
    "app", "ui", "audio", "ai", "lyrics", "automix", "bridge", "media", "player", "db",
)
RETENTION_DAYS = 7
# เก็บ log ล่าสุดในหน่วยความจำไว้ให้หน้า debug และรายงานปัญหา
_RING_SIZE = 2000

_SECRET_PATTERNS = [
    re.compile(r"(?i)(cookie|authorization|token|sapisid|__secure-[\w-]+)\s*[:=]\s*\S+"),
]

_ring: dict[str, deque[dict[str, Any]]] = {}
_ring_lock = threading.Lock()
_configured_dir: Path | None = None


def redact(text: str) -> str:
    """ลบค่าที่ดูเหมือนความลับออกจากข้อความ"""
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: m.group(1) + "=<redacted>", text)
    return text


class _JsonLinesHandler(logging.Handler):
    """เขียน JSON lines ลงไฟล์รายวันของ module นั้น และเก็บสำเนาใน ring buffer"""

    def __init__(self, logs_dir: Path, module: str) -> None:
        super().__init__()
        self.logs_dir = logs_dir
        self.module = module
        self._day: str | None = None
        self._fh: Any = None

    def _file_for_today(self) -> Any:
        day = _dt.date.today().isoformat()
        if day != self._day:
            if self._fh:
                self._fh.close()
            self._day = day
            self._fh = open(self.logs_dir / f"{self.module}-{day}.jsonl", "a", encoding="utf-8")
        return self._fh

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry: dict[str, Any] = {
                "ts": _dt.datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "module": self.module,
                "logger": record.name,
                "msg": redact(record.getMessage()),
                "thread": record.threadName,
            }
            data = getattr(record, "data", None)
            if data is not None:
                entry["data"] = data
            if record.exc_info:
                entry["exc"] = redact("".join(traceback.format_exception(*record.exc_info)))
            with _ring_lock:
                _ring.setdefault(self.module, deque(maxlen=_RING_SIZE)).append(entry)
            fh = self._file_for_today()
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            fh.flush()
        except Exception:  # log พังห้ามทำให้โปรแกรมพัง
            self.handleError(record)


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    """ตั้งค่า log ทุก module และลบไฟล์เก่ากว่า RETENTION_DAYS (เรียกครั้งเดียวตอนเปิด)"""
    global _configured_dir
    logs_dir.mkdir(parents=True, exist_ok=True)
    _configured_dir = logs_dir
    purge_old_logs(logs_dir)
    for module in MODULES:
        lg = logging.getLogger(f"synclyrics.{module}")
        lg.setLevel(level)
        lg.propagate = False
        lg.handlers.clear()
        lg.addHandler(_JsonLinesHandler(logs_dir, module))


def purge_old_logs(logs_dir: Path, keep_days: int = RETENTION_DAYS) -> int:
    """ลบไฟล์ log ที่เก่ากว่า keep_days คืนจำนวนไฟล์ที่ลบ"""
    cutoff = _dt.date.today() - _dt.timedelta(days=keep_days)
    removed = 0
    for f in logs_dir.glob("*-????-??-??.jsonl"):
        try:
            day = _dt.date.fromisoformat(f.stem[-10:])
        except ValueError:
            continue
        if day < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


def get_logger(module: str) -> logging.Logger:
    """คืน logger ของ module (ต้องเป็นชื่อใน MODULES) ใช้ได้แม้ยังไม่ setup (จะไม่เขียนไฟล์)"""
    if module not in MODULES:
        raise ValueError(f"ไม่รู้จัก module log: {module!r} (เพิ่มใน MODULES ก่อน)")
    return logging.getLogger(f"synclyrics.{module}")


def recent_entries(module: str, limit: int = 200) -> list[dict[str, Any]]:
    """log ล่าสุดของ module จากหน่วยความจำ (ใช้ในหน้า debug / รายงานปัญหา)"""
    with _ring_lock:
        buf = list(_ring.get(module, ()))
    return buf[-limit:]
