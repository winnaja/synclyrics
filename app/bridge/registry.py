"""ลงทะเบียน native messaging host ใน Registry ของผู้ใช้ (ไม่ต้องใช้สิทธิ์ admin) — ข้อ 10.1

HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.synclyrics.host = <path ของ host manifest>
manifest: {"name", "description", "path": synclyrics-host.exe, "type": "stdio",
           "allowed_origins": ["chrome-extension://<EXTENSION_ID>/"]}  — มีแค่ ID ของเราเท่านั้น
EXTENSION_ID มาจาก "key" ใน extension/manifest.json (คงที่ตลอด) — คำนวณด้วย extension_id_from_key()
ตัวติดตั้ง (Inno Setup) ทำขั้นตอนเดียวกัน; ฟังก์ชันนี้ใช้ตอนรันจากโค้ดและ "แก้ไขอัตโนมัติ"
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

REG_KEY = r"Software\Google\Chrome\NativeMessagingHosts\com.synclyrics.host"


def extension_id_from_key(public_key_b64: str) -> str:
    """คำนวณ extension ID จาก "key" ใน manifest (SHA-256 ของ DER, 32 ตัวแรก hex แปลง 0-f -> a-p)"""
    der = base64.b64decode(public_key_b64)
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def write_host_manifest(target: Path, host_exe: Path, extension_id: str) -> Path:
    """เขียนไฟล์ manifest ของ host — เฟส 2"""
    raise NotImplementedError("เฟส 2")


def register(manifest_path: Path) -> None:
    """เขียนค่า registry ใน HKCU (winreg) — เฟส 2"""
    raise NotImplementedError("เฟส 2")


def is_registered() -> bool:
    """ใช้ใน health check — เฟส 2"""
    raise NotImplementedError("เฟส 2")
