"""ลงทะเบียน native messaging host ใน Registry ของผู้ใช้ (ไม่ต้องใช้สิทธิ์ admin) — ข้อ 10.1

HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.synclyrics.host = <path ของ host manifest>
manifest: {"name", "description", "path": synclyrics-host.exe, "type": "stdio",
           "allowed_origins": ["chrome-extension://<EXTENSION_ID>/"]}  — มีแค่ ID ของเราเท่านั้น
EXTENSION_ID มาจาก "key" ใน extension/manifest.json (คงที่ตลอด) — คำนวณด้วย extension_id_from_key()
ตัวติดตั้ง (Inno Setup) ทำขั้นตอนเดียวกัน; ฟังก์ชันนี้ใช้ตอนรันจากโค้ดและ "แก้ไขอัตโนมัติ"

ระหว่างพัฒนา (ยังไม่มี synclyrics-host.exe) ใช้ scripts\\synclyrics-host.bat ที่เรียก .venv\\python -m app.bridge.host
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

HOST_NAME = "com.synclyrics.host"
REG_KEY = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def extension_id_from_key(public_key_b64: str) -> str:
    """คำนวณ extension ID จาก "key" ใน manifest (SHA-256 ของ DER, 32 ตัวแรก hex แปลง 0-f -> a-p)"""
    der = base64.b64decode(public_key_b64)
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def extension_id_from_manifest(manifest_path: Path) -> str:
    """อ่าน "key" จาก extension/manifest.json แล้วคำนวณ ID (ผิดพลาดโยน ValueError)"""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    key = data.get("key")
    if not key:
        raise ValueError("manifest.json ไม่มี key — extension ID จะไม่คงที่")
    return extension_id_from_key(key)


def default_host_exe() -> Path:
    """ตัวที่ Chrome จะเปิด: synclyrics-host.exe (ตัวติดตั้ง) หรือ .bat ของโหมดพัฒนา"""
    exe = PROJECT_ROOT / "synclyrics-host.exe"
    return exe if exe.exists() else PROJECT_ROOT / "scripts" / "synclyrics-host.bat"


def write_host_manifest(target: Path, host_exe: Path, extension_id: str) -> Path:
    """เขียนไฟล์ manifest ของ host ที่ target (allowed_origins มีแค่ extension ของเรา) คืน path"""
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": HOST_NAME,
        "description": "SyncLyrics native messaging host",
        "path": str(host_exe),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def register(manifest_path: Path) -> None:
    """เขียนค่า registry ใน HKCU (ค่า default ของ key = path ของ manifest)"""
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifest_path))


def unregister() -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    except FileNotFoundError:
        pass


def registered_manifest() -> Path | None:
    """path ของ manifest ที่ลงทะเบียนไว้ หรือ None"""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            value, _ = winreg.QueryValueEx(k, "")
            return Path(value)
    except OSError:
        return None


def is_registered() -> bool:
    """ลงทะเบียนแล้วและไฟล์ manifest + host ที่ชี้ไปยังอยู่จริง (ใช้ใน health check)"""
    mp = registered_manifest()
    if mp is None or not mp.exists():
        return False
    try:
        host = Path(json.loads(mp.read_text(encoding="utf-8"))["path"])
    except (OSError, ValueError, KeyError):
        return False
    return host.exists()


def install(manifest_dir: Path, extension_manifest: Path, host_exe: Path | None = None) -> Path:
    """ทำครบทีเดียว: คำนวณ ID -> เขียน host manifest -> ลง registry (ใช้ใน wizard / "แก้ไขอัตโนมัติ")"""
    ext_id = extension_id_from_manifest(extension_manifest)
    mp = write_host_manifest(manifest_dir / f"{HOST_NAME}.json", host_exe or default_host_exe(), ext_id)
    register(mp)
    return mp
