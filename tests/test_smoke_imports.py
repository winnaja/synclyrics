"""ทุก module ต้อง import ได้โดยไม่มี side effect หนัก (ไม่โหลด torch/Qt ตอน import)"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import pytest

import app

# module ที่ตั้งใจให้รันได้เฉพาะเมื่อเรียก (ไม่ใช่ library)
SKIP = {"app.__main__"}
# ไลบรารีที่ห้ามถูก import แค่เพราะ import module ของเรา (กัน process หลักช้า/หนัก)
FORBIDDEN_AT_IMPORT = ("torch", "torchaudio", "demucs", "faster_whisper", "PySide6")


def all_modules() -> list[str]:
    names = []
    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        if info.name not in SKIP:
            names.append(info.name)
    return sorted(names)


@pytest.mark.parametrize("name", all_modules())
def test_import(name: str) -> None:
    importlib.import_module(name)


def test_no_heavy_imports() -> None:
    for name in all_modules():
        importlib.import_module(name)
    loaded = [m for m in FORBIDDEN_AT_IMPORT if m in sys.modules]
    assert loaded == [], f"module ของเราไป import {loaded} ตอนโหลด — ให้ import ภายในฟังก์ชันแทน"


def test_module_count_sane() -> None:
    # กันกรณี walk_packages ไม่เจออะไรเลย (เช่นลืม __init__.py)
    assert len(all_modules()) >= 50
