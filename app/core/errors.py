"""ชนิด error กลาง — ทุก error ที่ผู้ใช้อาจเห็นต้องมีข้อความภาษาไทยที่เข้าใจง่าย

ใช้: raise SourceUnavailable("lrclib", "เชื่อมต่อ LRCLIB ไม่ได้", hint="ตรวจอินเทอร์เน็ต")
UI แสดง user_message + hint ส่วน log เก็บรายละเอียดเต็ม
"""

from __future__ import annotations


class SyncLyricsError(Exception):
    """error ที่รู้จัก มีข้อความสำหรับผู้ใช้และบอกว่ามี fallback ไหม"""

    def __init__(self, module: str, user_message: str, hint: str = "", recoverable: bool = True) -> None:
        super().__init__(f"[{module}] {user_message}")
        self.module = module
        self.user_message = user_message
        self.hint = hint
        self.recoverable = recoverable


class MediaError(SyncLyricsError):
    """โหลด/ถอดรหัสเสียงไม่ได้ (yt-dlp, ffmpeg, cookies)"""


class CookiesError(MediaError):
    """ดึง cookies จาก Chrome ไม่ได้ -> ใช้ cookies.txt (ข้อ 2.1)"""


class SourceUnavailable(SyncLyricsError):
    """แหล่งเนื้อเพลงใช้ไม่ได้ชั่วคราว -> ข้ามไปแหล่งถัดไป"""


class AiError(SyncLyricsError):
    """AI worker ทำงานไม่สำเร็จ -> ใช้เวลาแบบประมาณ"""


class AudioDeviceError(SyncLyricsError):
    """เปิดอุปกรณ์เสียงไม่ได้ -> ลองอุปกรณ์เริ่มต้น / buffer ใหญ่ขึ้น"""
