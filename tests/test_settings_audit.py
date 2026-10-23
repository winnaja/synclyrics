"""ตรวจหน้าตั้งค่าแบบไม่ต้องเปิด GUI: ทุกคีย์ที่ SettingsWindow.qml ผูกไว้ต้องมีอยู่จริงใน SettingsStore
มีค่าเริ่มต้น รับ/ปฏิเสธค่าตามช่วง คืนค่าเริ่มต้นรายตัวได้ และมีผู้ใช้ค่านั้นจริง (QML หรือ Python อื่น) — กัน "ตัวเลือกที่ปรับได้แต่ไม่มีผล"
"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.ui.settings_store import SettingsStore

ROOT = Path(__file__).resolve().parent.parent
QML_DIR = ROOT / "app" / "ui" / "qml"
SETTINGS_QML = (QML_DIR / "SettingsWindow.qml").read_text(encoding="utf-8")
DYNAMIC = ("ov_w_", "ov_h_")                       # คีย์ขนาดหน้าต่างตามโหมดปัจจุบัน ("ov_w_" + cfg.ov_mode)
META = {"ov_theme", "ov_anim_preset"}              # ตั้งค่าชุดค่าอื่นผ่าน SettingsStore (ไม่มีผู้อ่านตรงๆ)
DYNAMIC_CONSUMERS = ("hk_", "ls_src_")             # อ่านด้วย getattr แบบวนลูป (hotkeys / lyrics service)

UI_KEYS = sorted(set(re.findall(r'key:\s*"([a-z]+_[a-z0-9_]+)"', SETTINGS_QML)))


def _sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in glob.glob(str(ROOT / "app" / "**" / "*.qml"), recursive=True) + glob.glob(str(ROOT / "app" / "**" / "*.py"), recursive=True):
        base = os.path.basename(path)
        if base in {"SettingsWindow.qml", "settings_store.py", "settings_presets.py", "config.py"}:
            continue
        out[path] = Path(path).read_text(encoding="utf-8")
    return out


def test_every_ui_key_exists_in_store():
    flat = SettingsStore(Settings()).flat()
    missing = [k for k in UI_KEYS if k not in flat and not k.startswith(DYNAMIC)]
    assert not missing, f"UI อ้างคีย์ที่ไม่มีใน SettingsStore: {missing}"
    assert len(UI_KEYS) > 100


def test_every_ui_key_has_a_runtime_consumer():
    srcs = _sources()
    no_effect = []
    for key in UI_KEYS:
        if key in META or key.startswith(DYNAMIC + DYNAMIC_CONSUMERS):
            continue
        name = key.split("_", 1)[1]
        qml_hit = any(re.search(rf"\b{key}\b", t) for p, t in srcs.items() if p.endswith(".qml"))
        py_hit = any(re.search(rf"\.{name}\b", t) or f'"{key}"' in t or f'"{name}"' in t for p, t in srcs.items() if p.endswith(".py"))
        if not (qml_hit or py_hit):
            no_effect.append(key)
    assert not no_effect, f"ตัวเลือกที่ไม่มีใครอ่านค่า (ปรับแล้วไม่มีผล): {no_effect}"


def test_hotkey_and_source_keys_are_consumed_by_name():
    hk = (ROOT / "app" / "ui" / "app_window.py").read_text(encoding="utf-8")
    for key in [k for k in UI_KEYS if k.startswith("hk_") and k not in {"hk_status"}]:
        assert key.split("_", 1)[1] in hk or key.split("_", 1)[1] in (ROOT / "app" / "ui" / "hotkeys.py").read_text(encoding="utf-8"), key
    svc = (ROOT / "app" / "lyrics" / "service.py").read_text(encoding="utf-8")
    assert 'f"src_{name}"' in svc


@pytest.mark.parametrize("key", [k for k in UI_KEYS if not k.startswith(DYNAMIC) and not k.startswith("hk_")])
def test_reset_key_restores_default_and_rejects_nothing_valid(key):
    store = SettingsStore(Settings())
    default = store.default_of(key)
    assert store.is_default(key, store.flat()[key])
    store.reset_key(key)                         # ต้องไม่ error
    assert store.is_default(key, store.flat()[key])
    assert store.flat()[key] == default or store.is_default(key, store.flat()[key])


def test_invalid_values_are_rejected_without_changing_state():
    store = SettingsStore(Settings())
    before = store.flat()
    with pytest.raises(ValueError):
        store.set("ov_font_size", 99999)
    with pytest.raises(ValueError):
        store.set("ov_not_a_key", 1)
    assert store.flat() == before


def test_line_spacing_slider_range_is_accepted():
    store = SettingsStore(Settings())
    lo, hi = 0.8, 2.5                            # ช่วงของ slider ใน SettingsWindow.qml
    assert f'key: "ov_line_spacing"; from: {lo}; to: {hi}' in SETTINGS_QML
    store.set("ov_line_spacing", lo)
    store.set("ov_line_spacing", hi)


def test_search_and_navigation_hooks_present_in_qml():
    # โครงค้นหา: จับคู่ชื่อ/คำอธิบาย/คีย์/หมวด · กดหัวข้อผลค้นหาไปหมวดนั้น · มีปุ่มล้าง · ตัวอย่างสดย่อได้
    for needle in ("function hit(", "win.hit(label", "function gotoPage(", "head.crumb", "previewCompact", "Keys.onEscapePressed"):
        assert needle in SETTINGS_QML, needle
