"""ฝั่งโปรแกรมหลักของ bridge: QLocalServer บน named pipe (ข้อ 10.1, 2.3 single instance)

ใช้ server ตัวเดียวทำ 2 อย่าง:
  1. รับการเชื่อมต่อจาก native host (ส่วนขยาย) — ข้อความตาม app/core/messages.py
  2. single instance: เปิดโปรแกรมซ้ำ -> ตัวใหม่ต่อ pipe ได้ = มีตัวเดิมอยู่แล้ว
     ส่ง command{name:"focus"} (พร้อม argv เช่นลิงก์) แล้วปิดตัวเอง
ข้อความที่รับได้ส่งต่อเข้า EventBus / PlayerController ใน UI thread (QLocalSocket อยู่ใน Qt event loop)
"""

from __future__ import annotations

from typing import Any


class BridgeServer:
    """เฟส 2 (ส่วน single instance ทำในเฟส 1 พร้อมหน้าต่างหลัก)"""

    def __init__(self, bus: Any) -> None:
        self.bus = bus

    def start(self) -> bool:
        """เปิด server คืน False ถ้ามีโปรแกรมอีกตัวเปิดอยู่แล้ว"""
        raise NotImplementedError("เฟส 1")

    def send(self, type_: str, payload: dict[str, Any]) -> None:
        """ส่งข้อความถึงส่วนขยายทุกตัวที่เชื่อมอยู่"""
        raise NotImplementedError("เฟส 2")


def notify_existing_instance(argv: list[str]) -> bool:
    """เรียกตอนเปิดโปรแกรม: ถ้ามีตัวเดิมอยู่ ส่ง focus + argv แล้วคืน True (ตัวใหม่ต้องปิดตัวเอง)"""
    raise NotImplementedError("เฟส 1")
