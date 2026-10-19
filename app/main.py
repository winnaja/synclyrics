"""จุดเริ่มโปรแกรม: ประกอบทุกส่วนเข้าด้วยกันตามลำดับที่ปลอดภัย (ARCHITECTURE.md §1)

ลำดับการเปิด:
  1. ตรวจ Safe Mode (กด Shift ค้างตอนเปิด หรือ --safe-mode) -> ปิดเอฟเฟกต์และ AI ทั้งหมด
  2. single instance: มีตัวเดิมอยู่ -> ส่ง focus + argv แล้วปิดตัวเอง
  3. paths.ensure(), setup_logging(), โหลด config (พังใช้ค่าเริ่มต้น), เปิด DB (migration)
  4. สร้าง EventBus, AudioEngine (start ก่อนอย่างอื่น — เสียงต้องพร้อมเสมอ)
  5. สร้าง IO thread (asyncio loop) สำหรับ yt-dlp / เนื้อเพลง / ปก
  6. AiClient.start() ใน background (ไม่บล็อก UI; ไม่มี GPU = โหมดไม่มี AI)
  7. BridgeServer.start(), health check ใน background
  8. กู้สถานะล่าสุด (state.json) แล้วเปิด UI (run_ui) — UI พังต้องไม่ทำให้เสียงหยุด

ทุกขั้นห่อด้วย try/except: ขั้นไหนพัง log + ข้อความเข้าใจง่าย + ใช้ fallback แล้วไปต่อ
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass


@dataclass(slots=True)
class LaunchOptions:
    safe_mode: bool = False
    from_host: bool = False       # เปิดโดย native host (ส่วนขยายกด) — ไม่ต้องเปิด Chrome ซ้ำ
    minimized: bool = False       # เปิดพร้อม Windows -> ย่อไป tray
    open_url: str | None = None   # ลิงก์ YouTube ที่ส่งมาทาง argv


def parse_args(argv: list[str]) -> LaunchOptions:
    p = argparse.ArgumentParser(prog="SyncLyrics")
    p.add_argument("--safe-mode", action="store_true", help="ปิดเอฟเฟกต์และ AI ทั้งหมด")
    p.add_argument("--from-host", action="store_true")
    p.add_argument("--minimized", action="store_true")
    p.add_argument("url", nargs="?")
    a = p.parse_args(argv)
    return LaunchOptions(a.safe_mode, a.from_host, a.minimized, a.url)


def shift_held() -> bool:
    """กด Shift ค้างตอนเปิดโปรแกรม = Safe Mode (GetAsyncKeyState ผ่าน ctypes ไม่ต้องมี Qt)"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        VK_SHIFT = 0x10
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    """เฟส 1 จะประกอบส่วนที่มีจริง ส่วนที่ยังไม่มีให้ข้ามอย่างปลอดภัย"""
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    opts.safe_mode = opts.safe_mode or shift_held()
    raise NotImplementedError("เฟส 1")
