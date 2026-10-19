"""สร้าง QGuiApplication + QQmlApplicationEngine และผูก object ฝั่ง Python เข้ากับ QML

- ตั้ง QSG_RHI_BACKEND (d3d11 บน Windows) และ vsync, รองรับ 120/144Hz
- ลงทะเบียน: PlayerBridge (สถานะเพลง/คำสั่ง), LyricsModel, SettingsBridge, DebugBridge
- หน้าต่าง: Immersive (เต็มจอ), ปกติ, มินิเพลเยอร์, เนื้อเพลงลอยบนเดสก์ท็อป (ข้อ 2.3)
- safe_mode=True: ไม่โหลด shader/เอฟเฟกต์ ใช้ QML แบบเรียบ (ต้องใช้ได้แน่นอน ข้อ 11.2)
"""

from __future__ import annotations

from typing import Any


def run_ui(context: Any, safe_mode: bool = False) -> int:
    """เปิด UI และวน event loop คืน exit code — เฟส 1"""
    raise NotImplementedError("เฟส 1")
