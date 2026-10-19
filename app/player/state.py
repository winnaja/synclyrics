"""บันทึก/กู้คืนสถานะการเล่นทุก 5 วิ (ข้อ 6, 11.2)

เขียน state.json แบบ atomic (ไฟล์ชั่วคราว + rename) และตาราง playback_state/queue_items
เปิดโปรแกรมใหม่ (รวมหลัง crash): กลับไปเพลงเดิม ตำแหน่งเดิม คิวเดิม (ยังไม่เล่นจนกว่าผู้ใช้กด)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

SAVE_INTERVAL_S = 5.0


def save_state(path: Path, state: dict[str, Any]) -> None:
    """เขียนสถานะแบบ atomic — ไฟล์เดิมไม่มีวันเสียครึ่งๆ กลางๆ"""
    data = dict(state, saved_at=time.time())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_state(path: Path) -> dict[str, Any] | None:
    """อ่านสถานะล่าสุด ไฟล์ไม่มี/พัง = None (เริ่มใหม่ ไม่ error)"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None
