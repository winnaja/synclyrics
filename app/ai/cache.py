"""ไฟล์ cache ของ AI ต่อเพลง (cache/stems/<videoId>/) — ใช้ร่วมกันระหว่าง worker และ process หลัก (ไม่พึ่ง torch)

  transcript.json   คำ+เวลาที่ Whisper ฟังได้ทั้งเพลง + ช่วงเสียงร้อง (ใช้ซ้ำเมื่อสลับเนื้อเพลง/เปิดเพลงเดิม: ไม่ต้องโหลดเสียงและไม่ต้องใช้ GPU)
  vocals16k.npy     เสียงร้องที่แยกแล้ว 16 kHz mono (float16) สำหรับ alignment ละเอียดภายหลัง
กุญแจ (key) บอกว่าไฟล์สร้างด้วยวิธี/โมเดลอะไร ไม่ตรงกับตอนนี้ = ถือว่าไม่มี
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

TRANSCRIPT_FORMAT = 1


def transcript_key(models_config: dict[str, Any]) -> dict[str, Any]:
    a = models_config.get("analysis", {})
    return {"fmt": TRANSCRIPT_FORMAT, "algo": a.get("transcript_version", 2),   # แยกจาก algo_version: เปลี่ยนวิธีจัดเวลา/ประกอบบรรทัดไม่ต้องฟังเสียงซ้ำ (Demucs+Whisper ช้า)
             "whisper": models_config.get("whisper", {}).get("model"),
            "demucs": bool(models_config.get("demucs", {}).get("enabled", True))}


def load_transcript(path: Path, key: dict[str, Any]) -> dict[str, Any] | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if d.get("key") == key and d.get("complete") else None


def save_transcript(path: Path, key: dict[str, Any], words: list[Any], vsegs: list[Any], duration: float, language: str | None) -> None:
    """words = [TWord] (มี text/start/end/prob)"""
    try:
        path.write_text(json.dumps({"key": key, "complete": True, "duration": duration, "language": language,
                                    "vocal_segments": [list(s) for s in vsegs],
                                    "words": [[w.text, w.start, w.end, w.prob] for w in words]}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def enforce_limit(stems_dir: Path, max_songs: int = 400) -> int:
    """เก็บโฟลเดอร์เพลงล่าสุดไม่เกิน max_songs (ลบที่ใช้นานสุดก่อน) คืนจำนวนที่ลบ"""
    try:
        dirs = [d for d in stems_dir.iterdir() if d.is_dir()]
    except OSError:
        return 0
    if len(dirs) <= max_songs:
        return 0
    dirs.sort(key=lambda d: d.stat().st_mtime)
    removed = 0
    for d in dirs[: len(dirs) - max_songs]:
        shutil.rmtree(d, ignore_errors=True)
        removed += 1
    return removed


def touch(path: Path) -> None:
    try:
        path.touch(exist_ok=True)
        path.parent.touch(exist_ok=True)
    except OSError:
        pass


_ = time  # (เผื่อใช้ตรวจอายุไฟล์ภายหลัง)
