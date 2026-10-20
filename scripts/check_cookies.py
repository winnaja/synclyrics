"""ตรวจว่าโปรแกรมดึง cookies YouTube ได้ไหม และได้เสียงคุณภาพเท่าไร

ผลที่แสดง: โหมด cookies (chrome / file / none) และ format เสียงที่ได้ — ไม่แสดงค่า cookie ใดๆ
วิธีใช้: scripts\\check_cookies.bat  (แนะนำปิด Chrome ก่อน เพราะ Chrome ล็อกไฟล์ cookies ไว้)
ลิงก์ทดสอบเปลี่ยนได้: python scripts\\check_cookies.py <videoId>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.paths import get_paths  # noqa: E402
from app.media.youtube import YouTubeClient  # noqa: E402


def main() -> int:
    video_id = sys.argv[1] if len(sys.argv) > 1 else "2yqYAsUpdSc"
    paths = get_paths()
    client = YouTubeClient(paths.cookies_file)
    mode, msg = client.test_cookies()
    print(f"โหมด cookies: {mode}")
    print(msg)
    try:
        info = client.fetch_info(video_id)
        print(f"เสียงที่ได้: {info.audio_format}  (ตรวจแล้ว YouTube ให้ดึงเสียงได้สูงสุด opus ~137k ทั้งมีและไม่มี cookies — 256k ของ Premium มีเฉพาะในแอป YouTube Music)")
        print(f"โหมดที่ใช้จริงตอนดึงข้อมูล: {client.cookie_mode}")
    except Exception as e:  # noqa: BLE001
        print("ดึงข้อมูลวิดีโอไม่สำเร็จ:", e)
        return 1
    if client.cookie_mode == "none":
        print(f"\nถ้าต้องการให้เล่นวิดีโอจำกัดอายุ/ต้องล็อกอินได้: export cookies.txt (ส่วนขยาย 'Get cookies.txt LOCALLY') วางที่ {paths.cookies_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
