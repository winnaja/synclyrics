"""Native messaging host — process เล็กที่ Chrome เปิดเมื่อส่วนขยายเรียก connectNative (ข้อ 10.1)

หน้าที่เดียว: ส่งต่อข้อความสองทางระหว่าง stdin/stdout ของ Chrome กับ named pipe ของโปรแกรมหลัก
  - ต่อ pipe \\\\.\\pipe\\synclyrics-<username> ไม่ได้ -> เปิดโปรแกรมหลัก (SyncLyrics.exe --from-host)
    แล้วลองใหม่ทุก 250ms สูงสุด 15 วิ ไม่สำเร็จ -> ส่ง error กลับให้ส่วนขยายแสดงปุ่ม "แก้ไขอัตโนมัติ"
  - pipe หลุด (ปิดโปรแกรม) -> ส่ง status{connected:false} แล้วจบ process (ส่วนขยายจะต่อใหม่ทุก 2 วิ)
ต้องเบาและไม่ import PySide6/numpy (เปิดเร็ว) — build เป็น exe แยก: synclyrics-host.exe
stdout ใช้ส่งข้อความเท่านั้น ห้าม print อย่างอื่น (จะทำให้ protocol พัง) — log ลงไฟล์ bridge
"""

from __future__ import annotations

import getpass
import re

HOST_NAME = "com.synclyrics.host"


def pipe_name() -> str:
    """ชื่อ named pipe ที่โปรแกรมหลักเปิด (QLocalServer ใช้ชื่อนี้ — ต้องตรงกันทั้งสองฝั่ง)"""
    user = re.sub(r"[^A-Za-z0-9_-]", "_", getpass.getuser())
    return f"synclyrics-{user}"


def pipe_path() -> str:
    return rf"\\.\pipe\{pipe_name()}"


def main() -> int:
    """เฟส 2"""
    raise NotImplementedError("เฟส 2")


if __name__ == "__main__":
    raise SystemExit(main())
