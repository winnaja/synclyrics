"""PresetStore — เก็บ "ชุดการตั้งค่า" ที่ผู้ใช้ตั้งชื่อไว้ (บันทึก/ใช้/ลบ) ลงไฟล์ JSON ไฟล์เดียว

ไม่ผูกกับ Qt และไม่รู้จักโครงสร้าง Settings: เก็บแค่ {ชื่อ: {คีย์แบน: ค่า}} (คีย์แบบเดียวกับ SettingsStore.flat())
ตัวกรองว่าคีย์ไหนเข้าชุด/ค่าไหนใช้ได้ อยู่ที่ SettingsStore.snapshot()/apply_snapshot()
ไฟล์พัง = เริ่มว่างและเก็บไฟล์เดิมไว้เป็น .bad (ห้าม crash เพราะไฟล์ตั้งค่าของผู้ใช้)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app.core.log import get_logger

_log = get_logger("ui")

VERSION = 1
MAX_NAME_LEN = 40
MAX_PRESETS = 50


def clean_name(name: str) -> str:
    """ตัดช่องว่างหัวท้าย/ยุบช่องว่างซ้ำ · คืน "" ถ้าชื่อใช้ไม่ได้ (ว่าง/ยาวเกิน/มีอักขระควบคุม)"""
    name = " ".join(str(name).split())
    if not name or len(name) > MAX_NAME_LEN or any(ord(c) < 32 for c in name):
        return ""
    return name


class PresetStore:
    """path=None = เก็บในหน่วยความจำอย่างเดียว (test/ไม่มีโฟลเดอร์ข้อมูล)"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self._presets: dict[str, dict[str, Any]] = {}
        self._load()

    # ---------- อ่าน ----------
    def names(self) -> list[str]:
        """ชื่อชุดเรียงตามเวลาที่บันทึกล่าสุดก่อน"""
        return sorted(self._presets, key=lambda n: self._presets[n].get("saved_at", 0), reverse=True)

    def get(self, name: str) -> dict[str, Any] | None:
        entry = self._presets.get(clean_name(name))
        return dict(entry["values"]) if entry else None

    # ---------- เขียน ----------
    def save(self, name: str, values: dict[str, Any]) -> str:
        """บันทึก/เขียนทับชุด คืนข้อความผิดพลาด ("" = สำเร็จ)"""
        cleaned = clean_name(name)
        if not cleaned:
            return f"ชื่อชุดต้องไม่ว่างและยาวไม่เกิน {MAX_NAME_LEN} ตัวอักษร"
        if cleaned not in self._presets and len(self._presets) >= MAX_PRESETS:
            return f"บันทึกได้สูงสุด {MAX_PRESETS} ชุด ลบชุดเก่าก่อน"
        # Windows นาฬิกาละเอียดแค่ ~15 ms: บันทึกถี่ๆ ได้เวลาเท่ากัน ลำดับ "ใหม่สุดก่อน" จึงต้องบังคับให้เพิ่มขึ้นเสมอ
        latest = max((float(e.get("saved_at", 0)) for e in self._presets.values()), default=0.0)
        self._presets[cleaned] = {"saved_at": max(time.time(), latest + 1e-3), "values": dict(values)}
        return self._write()

    def delete(self, name: str) -> bool:
        if self._presets.pop(clean_name(name), None) is None:
            return False
        self._write()
        return True

    # ---------- ไฟล์ ----------
    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            presets = raw["presets"]
            for name, entry in presets.items():
                if clean_name(name) == name and isinstance(entry.get("values"), dict):
                    self._presets[name] = {"saved_at": float(entry.get("saved_at", 0)), "values": entry["values"]}
        except Exception:
            _log.warning("ไฟล์ชุดการตั้งค่าพัง เริ่มใหม่และเก็บไฟล์เดิมเป็น .bad", extra={"data": {"path": str(self.path)}})
            self._presets = {}
            try:
                os.replace(self.path, self.path.with_suffix(".bad"))
            except OSError:
                pass

    def _write(self) -> str:
        if self.path is None:
            return ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": VERSION, "presets": self._presets}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)  # เขียนไฟล์ชั่วคราวแล้วสลับ — ไฟล์ไม่ขาดครึ่งถ้าโปรแกรมดับกลางทาง
        except OSError as e:
            _log.warning("บันทึกชุดการตั้งค่าไม่สำเร็จ", extra={"data": {"err": str(e)}})
            return "บันทึกไฟล์ไม่สำเร็จ"
        return ""
