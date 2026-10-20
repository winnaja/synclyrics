"""ตัวช่วยติดตั้งส่วนขยาย Chrome ครั้งแรก (ข้อ 10.5) — ทำทุกอย่างที่ทำแทนผู้ใช้ได้

ขั้นตอน (Chrome ไม่ให้โปรแกรมโหลดส่วนขยายเองได้ จึงต้องให้ผู้ใช้กด Load unpacked 1 ครั้ง):
  1. คัดลอกโฟลเดอร์ extension/ ไปที่ถาวร %LOCALAPPDATA%\\SyncLyrics\\extension (ไม่รวม key.pem)
  2. ลงทะเบียน native messaging host ใน Registry (HKCU) ให้ตรงกับ extension ID
  3. คัดลอก path โฟลเดอร์ใส่ clipboard (ผู้ใช้วางในหน้าต่างเลือกโฟลเดอร์ได้ทันที)
  4. เปิด chrome://extensions (ผู้ใช้เปิด Developer mode -> Load unpacked -> วาง path)
  5. ตรวจว่าสำเร็จ = รอข้อความ hello จากส่วนขยาย (BridgeService เป็นคนรับ)
อัปเดตส่วนขยาย: เรียก sync_extension() ซ้ำ แล้วสั่ง reload_extension (chrome.runtime.reload()) ผ่าน bridge
"""

from __future__ import annotations

import filecmp
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.bridge import registry
from app.core.log import get_logger

log = get_logger("bridge")

# ไฟล์ที่ห้ามคัดลอกไปโฟลเดอร์ถาวร (ความลับ/ขยะ)
IGNORE = shutil.ignore_patterns("key.pem", "*.pem", "__pycache__", "*.md")


@dataclass(frozen=True, slots=True)
class InstallResult:
    ok: bool
    ext_dir: Path | None = None
    changed: bool = False   # True = ไฟล์ส่วนขยายถูกอัปเดต (ควรสั่ง reload_extension)
    message: str = ""


def sync_extension(src: Path, dst: Path) -> bool:
    """คัดลอก src ทับ dst เฉพาะไฟล์ที่ต่างกัน; คืน True ถ้ามีไฟล์เปลี่ยน"""
    changed = False
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("*"):
        rel = f.relative_to(src)
        if f.is_dir() or IGNORE(str(f.parent), [f.name]):
            continue
        target = dst / rel
        if target.exists() and filecmp.cmp(f, target, shallow=False):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        changed = True
    return changed


def install(paths, set_clipboard=None, open_url=None) -> InstallResult:  # noqa: ANN001
    """ทำขั้น 1-4 · paths = AppPaths · set_clipboard(text)/open_url(url) ฉีดจากภายนอกเพื่อให้ test ได้"""
    src = paths.extension_src_dir
    dst = paths.installed_extension_dir
    try:
        manifest = src / "manifest.json"
        if not manifest.exists():
            return InstallResult(False, message="ไม่พบโฟลเดอร์ extension ของโปรแกรม")
        changed = sync_extension(src, dst)
        registry.install(paths.home / "native-messaging", dst / "manifest.json")
    except Exception as e:  # noqa: BLE001
        log.exception("ติดตั้งส่วนขยายไม่สำเร็จ")
        return InstallResult(False, message=f"ติดตั้งไม่สำเร็จ: {e}")
    if set_clipboard:
        set_clipboard(str(dst))
    (open_url or open_chrome_extensions)("chrome://extensions")
    return InstallResult(True, dst, changed,
                         "คัดลอกที่อยู่โฟลเดอร์ใส่คลิปบอร์ดแล้ว — ใน Chrome: เปิด 'โหมดนักพัฒนาซอฟต์แวร์' "
                         "แล้วกด 'โหลดส่วนขยายที่แกะแล้ว' วางที่อยู่ (Ctrl+V) แล้วกดเลือกโฟลเดอร์")


def find_chrome() -> Path | None:
    import os

    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if p.exists():
                return p
    return None


def open_chrome_extensions(url: str = "chrome://extensions") -> bool:
    """เปิดหน้าส่วนขยายใน Chrome (chrome:// เปิดผ่าน shell ไม่ได้ ต้องเรียก chrome.exe ตรงๆ)"""
    chrome = find_chrome()
    if chrome is None:
        return False
    try:
        subprocess.Popen([str(chrome), url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except OSError:
        return False


def main() -> int:
    """ติดตั้งจาก command line: python -m app.bridge.installer (ใช้เมื่อเปิดหน้าต่างโปรแกรมไม่ได้)"""
    from app.core.paths import get_paths

    try:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance() or QGuiApplication([])
        set_clip = lambda t: app.clipboard().setText(t)  # noqa: E731
    except Exception:  # noqa: BLE001 — ไม่มี Qt ก็ติดตั้งได้ แค่ไม่ใส่ clipboard
        set_clip = None
    res = install(get_paths(), set_clipboard=set_clip)
    print(res.message)
    if res.ext_dir:
        print("โฟลเดอร์ส่วนขยาย:", res.ext_dir)
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
