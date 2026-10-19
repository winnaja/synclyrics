"""เวลาแบบประมาณ — ใช้ระหว่างรอ AI และเมื่อ AI ไม่มั่นใจ (ข้อ 4.4)

- กระจายเวลาในบรรทัดตามจำนวนพยางค์/ตัวอักษรของแต่ละคำ (ไทย: นับพยางค์ด้วย pythainlp)
- คำท้ายบรรทัดได้น้ำหนักมากกว่า (มักลากเสียง)
- เนื้อเพลงไม่มีเวลาเลย: กระจายบรรทัดตลอดช่วงที่มีเสียงร้อง (ถ้ารู้) หรือทั้งเพลง
ต้องเร็วมาก (< 50ms ต่อเพลง) เพราะต้องขึ้นจอภายใน 1 วิหลังกดเล่น
"""

from __future__ import annotations

from app.core.models import Line, Lyrics

LAST_WORD_WEIGHT = 1.6


def estimate_line(line: Line) -> Line:
    """ใส่เวลาทีละคำให้บรรทัดที่มีเวลาเริ่ม/จบแล้ว — เฟส 1"""
    raise NotImplementedError("เฟส 1")


def estimate_lyrics(lyrics: Lyrics, duration: float,
                    vocal_segments: list[tuple[float, float]] | None = None) -> Lyrics:
    """ทั้งเพลง: บรรทัดที่ไม่มีเวลาจะถูกกระจายก่อน แล้วค่อยกระจายคำ — เฟส 1"""
    raise NotImplementedError("เฟส 1")
