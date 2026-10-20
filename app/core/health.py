"""ตรวจสุขภาพตอนเปิดโปรแกรม (ข้อ 11.2): บอกปัญหาเป็นภาษาคน พร้อมวิธีแก้

ตรวจเฉพาะสิ่งที่ฟีเจอร์เฟส 1-2 ต้องใช้: ffmpeg, Node.js (yt-dlp แก้โจทย์ JS ของ YouTube), cookies Premium,
ส่วนขยาย Chrome (ลงทะเบียน host แล้วไหม / เชื่อมอยู่ไหม), อุปกรณ์เสียง · เฟส 4/8 เพิ่ม GPU/โมเดล/เน็ต
ทุกการตรวจต้องไม่พัง (พัง = รายงานเป็นปัญหาข้อหนึ่ง) และไม่ใช้เครือข่าย เพื่อรันตอนเปิดได้เร็ว
ห้ามใส่ค่า cookie ใดๆ ในผลลัพธ์
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class HealthItem:
    """ผลตรวจหนึ่งข้อ · ok=False แสดงให้ผู้ใช้เห็น (severity: "error" ใช้งานไม่ได้ / "warn" ใช้ได้แต่ด้อยลง)"""

    id: str
    ok: bool
    message: str = ""
    fix: str = ""
    severity: str = "warn"


def _guard(fn: Callable[[], HealthItem], id_: str) -> HealthItem:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — ตัวตรวจพังต้องไม่ทำให้โปรแกรมพัง
        return HealthItem(id_, False, f"ตรวจ {id_} ไม่สำเร็จ ({type(e).__name__})", severity="warn")


def check_ffmpeg(find_ffmpeg: Callable[[], Path | None]) -> HealthItem:
    if find_ffmpeg() is not None:
        return HealthItem("ffmpeg", True)
    return HealthItem("ffmpeg", False, "ไม่พบ ffmpeg จึงถอดรหัสเสียงไม่ได้",
                      "ติดตั้งด้วย: winget install Gyan.FFmpeg แล้วเปิดโปรแกรมใหม่", "error")


def check_node(which: Callable[[str], str | None] = shutil.which) -> HealthItem:
    if which("node"):
        return HealthItem("node", True)
    return HealthItem("node", False, "ไม่พบ Node.js — YouTube ต้องใช้แก้โจทย์ก่อนโหลดเสียง อาจโหลดเพลงไม่ได้",
                      "ติดตั้งด้วย: winget install OpenJS.NodeJS.LTS แล้วเปิดโปรแกรมใหม่", "error")


def check_cookies(cookies_file: Path, count_cookies: Callable[[Path], int] | None = None) -> HealthItem:
    """มี cookies.txt ที่ใช้ได้ไหม (ไม่ทดสอบกับเครือข่าย) — ไม่มี = เล่นแบบไม่ล็อกอิน (เสียงเท่ากัน แต่วิดีโอจำกัดอายุโหลดไม่ได้)"""
    fix = ("export cookies.txt ของ youtube.com จาก Chrome (ส่วนขยาย 'Get cookies.txt LOCALLY') "
           f"แล้ววางไว้ที่ {cookies_file}")
    if not cookies_file.exists():
        return HealthItem("cookies", False, "ยังไม่มี cookies — ข้อมูลของวิดีโอที่จำกัดอายุ/ต้องล็อกอินจะดึงไม่ได้ (ไม่กระทบเพลงทั่วไป)", fix)
    n = count_cookies(cookies_file) if count_cookies else _count_netscape(cookies_file)
    if n <= 0:
        return HealthItem("cookies", False, "ไฟล์ cookies.txt ไม่มี cookies ของ YouTube/Google (รูปแบบผิดหรือหมดอายุ)", fix)
    return HealthItem("cookies", True)


def _count_netscape(path: Path) -> int:
    """นับบรรทัด cookies ของ youtube/google ในไฟล์ Netscape (ไม่อ่านค่า cookie ออกมาเก็บ)"""
    n = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and ("youtube" in parts[0] or "google" in parts[0]):
            n += 1
    return n


def check_extension_registered(is_registered: Callable[[], bool]) -> HealthItem:
    if is_registered():
        return HealthItem("extension_registered", True)
    return HealthItem("extension_registered", False,
                      "ยังไม่ได้ติดตั้งส่วนขยาย Chrome (ปุ่มบน YouTube และการส่งเพลงอัตโนมัติจะไม่ทำงาน)",
                      "กด 'ติดตั้งส่วนขยาย' ในโปรแกรม แล้วทำตามขั้นตอน")


def check_audio(engine_error: str | None) -> HealthItem:
    if not engine_error:
        return HealthItem("audio", True)
    return HealthItem("audio", False, engine_error, "ตรวจว่าเสียบลำโพง/หูฟังแล้ว และไม่มีโปรแกรมอื่นจองอุปกรณ์เสียงแบบ exclusive", "error")


def run_health_checks(*, find_ffmpeg: Callable[[], Path | None], cookies_file: Path,
                      is_ext_registered: Callable[[], bool], engine_error: str | None,
                      which: Callable[[str], str | None] = shutil.which, app_audio: bool = True) -> list[HealthItem]:
    """รันทุกข้อ คืนรายการ (รวมข้อที่ผ่านด้วย — UI กรองเอาเฉพาะที่ ok=False)

    app_audio=False (แอปแสดงเนื้อเพลงอย่างเดียว): ไม่ตรวจอุปกรณ์เสียง/ffmpeg เพราะยังไม่ได้ใช้ (ffmpeg กลับมาตรวจเมื่อเฟส 4 ใช้ AI)
    """
    items = [
        _guard(lambda: check_node(which), "node"),
        _guard(lambda: check_cookies(cookies_file), "cookies"),
        _guard(lambda: check_extension_registered(is_ext_registered), "extension_registered"),
    ]
    if app_audio:
        items = [_guard(lambda: check_audio(engine_error), "audio"), _guard(lambda: check_ffmpeg(find_ffmpeg), "ffmpeg"), *items]
    return items


def format_problems(items: list[HealthItem]) -> str:
    """ข้อความสั้นๆ สำหรับแสดงใน UI/log: เฉพาะที่มีปัญหา (ว่าง = ปกติ)"""
    lines = [f"• {i.message}" + (f"\n   วิธีแก้: {i.fix}" if i.fix else "") for i in items if not i.ok]
    return "\n".join(lines)
