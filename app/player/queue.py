"""คิวเพลง (ข้อ 6): เพิ่มท้าย/เล่นถัดไป, ลากสลับ, ลบ, บันทึกเป็น playlist, บันทึกทุก 5 วิ

แหล่งที่มา: playlist/Up next จากส่วนขยาย, ปุ่มบน YouTube, ช่องค้นหา, ลากลิงก์, Ctrl+V
ทุกการเปลี่ยนแปลง -> EventBus QUEUE_CHANGED และ Preloader ตรวจว่าเพลงถัดไปเปลี่ยนไหม
"""

from __future__ import annotations

from app.core.models import TrackRef


class PlayQueue:
    """เฟส 5 (เฟส 1 มีแค่เพลงเดียว + ปุ่มถัดไปแบบง่าย)"""

    def __init__(self) -> None:
        self.items: list[TrackRef] = []
        self.index: int = -1

    def add(self, tracks: list[TrackRef], position: str = "end") -> None:
        raise NotImplementedError("เฟส 5")

    def move(self, src: int, dst: int) -> None:
        raise NotImplementedError("เฟส 5")

    def remove(self, index: int) -> None:
        raise NotImplementedError("เฟส 5")

    def peek_next(self) -> TrackRef | None:
        raise NotImplementedError("เฟส 5")

    def advance(self) -> TrackRef | None:
        raise NotImplementedError("เฟส 5")
