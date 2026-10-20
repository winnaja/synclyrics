"""คีย์ลัดทั้งระบบ (parse + ลงทะเบียนจริง) และเปิดพร้อม Windows (ใช้ registry key ทดสอบ)"""

from __future__ import annotations

import os
import threading
import time

import pytest

from app.ui import startup
from app.ui.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, HotkeyError, HotkeyManager, parse_hotkey


def test_parse_hotkey_valid_forms() -> None:
    assert parse_hotkey("Ctrl+Alt+L") == (MOD_CONTROL | MOD_ALT, ord("L"))
    assert parse_hotkey("ctrl + shift + 7") == (MOD_CONTROL | MOD_SHIFT, ord("7"))
    assert parse_hotkey("Win+F12") == (MOD_WIN, 0x7B)
    assert parse_hotkey("Ctrl+Alt+Up") == (MOD_CONTROL | MOD_ALT, 0x26)
    assert parse_hotkey("Ctrl+Alt+]") == (MOD_CONTROL | MOD_ALT, 0xDD)
    assert parse_hotkey("Ctrl++") == (MOD_CONTROL, 0xBB)


@pytest.mark.parametrize("bad", ["", "L", "Ctrl", "Ctrl+Alt", "Ctrl+A+B", "Ctrl+Banana", "Ctrl+F25", "Shift+"])
def test_parse_hotkey_rejects_bad(bad: str) -> None:
    with pytest.raises(HotkeyError):
        parse_hotkey(bad)


@pytest.mark.skipif(os.name != "nt", reason="RegisterHotKey เฉพาะ Windows")
def test_manager_registers_reports_conflicts_and_stops() -> None:
    fired: list[str] = []
    m = HotkeyManager(fired.append)
    try:
        # คีย์ที่ไม่น่าจะมีโปรแกรมไหนใช้ + ซ้ำกันเอง + ผิดรูปแบบ + ว่าง (ปิด)
        errors = m.set_bindings({"a": "Ctrl+Alt+Shift+F13", "dup": "Ctrl+Alt+Shift+F13", "bad": "Banana", "off": ""})
        assert "a" not in errors and "dup" in errors and "ซ้ำ" in errors["dup"] and "bad" in errors and "off" not in errors
        # คีย์เดียวกันลงทะเบียนซ้ำจาก manager ตัวที่สอง = ระบบปฏิเสธ -> รายงานว่ามีโปรแกรมอื่นใช้อยู่
        m2 = HotkeyManager(lambda n: None)
        try:
            assert "อื่นใช้อยู่" in m2.set_bindings({"x": "Ctrl+Alt+Shift+F13"}).get("x", "")
        finally:
            m2.stop()
    finally:
        m.stop()
    # หยุดแล้วลงทะเบียนใหม่ได้ (ปล่อยคีย์คืนระบบจริง)
    m3 = HotkeyManager(lambda n: None)
    try:
        assert m3.set_bindings({"x": "Ctrl+Alt+Shift+F13"}) == {}
    finally:
        m3.stop()


@pytest.mark.skipif(os.name != "nt", reason="winreg เฉพาะ Windows")
def test_launch_with_windows_roundtrip_on_test_key() -> None:
    import winreg

    key = r"Software\SyncLyricsTest\Run"
    try:
        assert startup.is_launch_with_windows(key) is False
        if startup.startup_command() is None:
            pytest.skip("ไม่มีตัวรันโปรแกรมให้ลงทะเบียน")
        assert startup.set_launch_with_windows(True, key) is True
        assert startup.is_launch_with_windows(key) is True
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            value, _ = winreg.QueryValueEx(k, "SyncLyrics")
        assert "--minimized" in value and "-m app" in value
        assert startup.set_launch_with_windows(False, key) is True
        assert startup.is_launch_with_windows(key) is False
        assert startup.set_launch_with_windows(False, key) is True  # ปิดซ้ำไม่พัง
    finally:
        for sub in (key, r"Software\SyncLyricsTest"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass


def test_blur_behind_never_raises_on_bad_window_handles() -> None:
    """เอฟเฟกต์ตกแต่ง (acrylic/มุมโค้ง) ต้องไม่ทำให้โปรแกรมพังแม้ handle ผิด/ไม่ใช่ Windows"""
    from app.ui import winfx

    assert winfx.apply_blur_behind(0, True, 100, 100, 8) is False       # hwnd ว่าง
    assert winfx.apply_blur_behind(0xDEAD, True, 100, 100, 8) in (True, False)  # hwnd ปลอม: คืนค่าได้ ห้าม raise
    assert winfx.apply_blur_behind(0xDEAD, False, 100, 100, 0) in (True, False)
