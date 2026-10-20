"""เปิดโปรแกรมพร้อม Windows (UX UI ข้อ 11) — ค่า Run ใน HKCU (ไม่ต้องใช้สิทธิ์ admin) เปิดแบบซ่อนหน้าต่างตั้งค่า

เปิดพร้อมระบบแล้วไม่เด้งหน้าต่างตั้งค่า: โปรแกรมนี้ไม่มีหน้าต่างหลัก มีแต่เนื้อเพลงลอยกับถาดระบบ
ตอนพัฒนา (ยังไม่มี SyncLyrics.exe) ใช้ .venv\\Scripts\\pythonw.exe -m app
"""

from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SyncLyrics"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def startup_command() -> str | None:
    """คำสั่งเปิดโปรแกรม (ใส่ใน Run) หรือ None ถ้าหาตัวรันไม่เจอ"""
    exe = Path(sys.executable).resolve().parent / "SyncLyrics.exe"
    if exe.exists():
        return f'"{exe}" --minimized'
    pyw = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if pyw.exists():
        return f'"{pyw}" -m app --minimized'
    return None


def set_launch_with_windows(enabled: bool, run_key: str = RUN_KEY) -> bool:
    """เปิด/ปิดการเริ่มพร้อม Windows คืน True ถ้าทำสำเร็จ (run_key ไว้ให้ test ใช้ key ทดสอบ)"""
    try:
        import winreg

        if enabled:
            cmd = startup_command()
            if cmd is None:
                return False
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False


def is_launch_with_windows(run_key: str = RUN_KEY) -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as k:
            winreg.QueryValueEx(k, VALUE_NAME)
            return True
    except OSError:
        return False
