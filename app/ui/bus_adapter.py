"""แปลงเหตุการณ์จาก EventBus (thread ใดก็ได้) เป็น Qt signal ใน UI thread

subscribe("*") แล้ว emit signal ที่ต่อแบบ Qt.QueuedConnection — handler ฝั่ง QML/Python UI
จึงรันใน UI thread เสมอ ห้าม logic ไปเรียก QObject ของ UI ตรงๆ จาก thread อื่น
"""

from __future__ import annotations

from typing import Any


class BusAdapter:
    """เฟส 1"""

    def __init__(self, bus: Any) -> None:
        self.bus = bus
