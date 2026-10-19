"""โหลดล่วงหน้าแค่เพลงถัดไป 1 เพลง (ข้อ 6)

เริ่มเมื่อ: เพลงปัจจุบันเล่นถึง preload_at_percent (50%) และงาน AI ของเพลงปัจจุบันเสร็จแล้ว
เตรียมครบ: ชื่อ ปก texture สีจากปก เนื้อเพลง เสียง (PCM ใน RAM/memmap) วิเคราะห์ alignment แผนการมิกซ์
ข้ามเพลง/เปลี่ยนคิว: ยกเลิกงานเก่าทันทีแล้วเตรียมเพลงใหม่
สถานะส่งทาง EventBus PRELOAD_STATUS (แสดงที่ "เพลงถัดไป" ข้อ 3.1)
"""

from __future__ import annotations

from typing import Any


class Preloader:
    """เฟส 5"""

    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.video_id: str | None = None

    def maybe_start(self, position_s: float, duration_s: float) -> None:
        raise NotImplementedError("เฟส 5")

    def cancel(self) -> None:
        raise NotImplementedError("เฟส 5")
