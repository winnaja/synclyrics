"""เก็บข้อมูลสอน (training data) จากทุกเพลงที่แอปเล่น — ผู้ใช้สั่ง 2026-10-21 "เก็บทั้งหมด" เพื่อเทรนโมเดลของเราเอง

เก็บในเครื่องเท่านั้นที่ <โปรเจกต์>/dataset/ (ไม่ส่งออกนอกเครื่อง ไม่เข้า git):
  songs/<videoId>/meta.json        ชื่อ/ศิลปิน/ภาษา/ความยาว + ฉบับเนื้อเพลงที่ใช้ + ผลสุดท้ายของ AI (เวลารายคำ เสียงประสาน นักร้อง) + สถิติ
  songs/<videoId>/candidates.json  เนื้อเพลงทุกฉบับที่ผู้สมัคร (แหล่ง/คะแนน/ข้อความรายบรรทัด) — ใช้เทรนตัวเลือกฉบับ
  songs/<videoId>/vocals16k.npy    เสียงร้องที่ Demucs แยกแล้ว 16 kHz (float16) — ใช้เทรนตัวจัดเวลา/ตรวจคอรัส/นับนักร้อง
  songs/<videoId>/transcript.json  คำที่ Whisper ได้ยิน
  events.jsonl                     สิ่งที่ผู้ใช้ทำ (กด "ตัวอื่น", ปรับเวลา ฯลฯ) = สัญญาณว่าผลถูกใจไหม
เล่นซ้ำ = เขียนทับไฟล์ผลของเพลงนั้น (เก็บฉบับล่าสุด) · ปิดได้ที่ตั้งค่า > การซิงก์ > AI ("เก็บข้อมูลสอน")
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.log import get_logger
from app.core.paths import PROJECT_ROOT

log = get_logger("ai")

DATASET_DIR = PROJECT_ROOT / "dataset"


def song_dir(video_id: str) -> Path:
    return DATASET_DIR / "songs" / video_id


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def lyrics_lines(lyrics: Any) -> list[dict[str, Any]]:
    """Lyrics -> รายการบรรทัดแบบเรียบง่าย (ข้อความ/เวลา/คำ) สำหรับเก็บ"""
    out = []
    for ln in getattr(lyrics, "lines", []) or []:
        out.append({"start": ln.start, "end": ln.end, "voice": getattr(ln.voice, "value", str(ln.voice)),
                    "text": ln.text, "words": [[w.text, w.start, w.end] for w in ln.words]})
    return out


def record_song(video_id: str, meta: dict[str, Any], candidates: list[dict[str, Any]] | None, stems_dir: Path | None) -> None:
    """เก็บเพลงหนึ่งเพลงหลัง AI จัดเวลาเสร็จ (เรียกใน thread ของ AI ห้ามพัง: ล้มเหลวแค่ log)"""
    try:
        d = song_dir(video_id)
        d.mkdir(parents=True, exist_ok=True)
        meta = {**meta, "recorded_at": time.time(), "video_id": video_id}
        _write_json(d / "meta.json", meta)
        if candidates:
            _write_json(d / "candidates.json", candidates)
        if stems_dir is not None:
            for name in ("vocals16k.npy", "transcript.json"):
                src = Path(stems_dir) / name
                dst = d / name
                if src.exists() and (not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime):
                    shutil.copy2(src, dst)
    except Exception:  # noqa: BLE001
        log.exception("เก็บข้อมูลสอนไม่สำเร็จ")


def record_event(kind: str, video_id: str | None, **data: Any) -> None:
    """เก็บการกระทำของผู้ใช้หนึ่งครั้ง (บรรทัดเดียวใน events.jsonl)"""
    try:
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        with (DATASET_DIR / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, "video_id": video_id, **data}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        log.exception("เก็บเหตุการณ์ไม่สำเร็จ")
