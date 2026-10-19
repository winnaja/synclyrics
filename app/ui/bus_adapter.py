"""แปลงเหตุการณ์จาก EventBus (thread ใดก็ได้) เป็น Qt signal ใน UI thread

subscribe("*") แล้ว emit signal ที่ต่อแบบ Qt.QueuedConnection — handler ฝั่ง QML/Python UI
จึงรันใน UI thread เสมอ ห้าม logic ไปเรียก QObject ของ UI ตรงๆ จาก thread อื่น

การใช้: adapter = create_bus_adapter(bus); adapter.connect_slot(qobject.on_event)
 - ต้องเรียก create_bus_adapter จาก UI thread (adapter จะอยู่ใน thread นั้น)
 - connect_slot ต่อแบบ QueuedConnection เสมอ ปลายทางต้องเป็น @Slot ของ QObject ที่อยู่ใน UI thread
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_ADAPTER_CLASS: type | None = None


def make_bus_adapter_class() -> type:
    """สร้างคลาส BusAdapter (QObject) ครั้งเดียวแล้วจำไว้ — import PySide6 ภายในฟังก์ชันเท่านั้น"""
    global _ADAPTER_CLASS
    if _ADAPTER_CLASS is not None:
        return _ADAPTER_CLASS

    from PySide6.QtCore import QObject, Qt, Signal

    class BusAdapter(QObject):
        """สะพาน EventBus -> Qt signal `event(topic, payload)`"""

        # payload เป็น object (dict ของ Python ที่มี Lyrics/TrackMeta ได้) ไม่แปลงเป็น QVariantMap
        event = Signal(str, object)

        def __init__(self, bus: Any, parent: Any = None) -> None:
            super().__init__(parent)
            self.bus = bus
            self._unsubscribe: Callable[[], None] | None = bus.subscribe("*", self._on_bus)

        def _on_bus(self, topic: str, payload: dict[str, Any]) -> None:
            """รันใน thread ของผู้ส่ง — แค่ emit ส่วน slot ที่ต่อแบบ queued จะรันใน UI thread"""
            self.event.emit(topic, payload)

        def connect_slot(self, slot: Callable[[str, Any], None]) -> None:
            """ต่อ slot แบบ QueuedConnection"""
            self.event.connect(slot, Qt.ConnectionType.QueuedConnection)

        def close(self) -> None:
            """เลิกฟัง bus (ใช้ตอนปิดโปรแกรม)"""
            if self._unsubscribe is not None:
                self._unsubscribe()
                self._unsubscribe = None

    _ADAPTER_CLASS = BusAdapter
    return BusAdapter


def create_bus_adapter(bus: Any) -> Any:
    """สร้าง BusAdapter ที่ผูกกับ bus (เรียกจาก UI thread)"""
    return make_bus_adapter_class()(bus)
