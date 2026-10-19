"""ฝั่งโปรแกรมหลักของ bridge: QLocalServer บน named pipe (ข้อ 10.1, 2.3 single instance)

ใช้ server ตัวเดียวทำ 2 อย่าง:
  1. รับการเชื่อมต่อจาก native host (ส่วนขยาย) — ข้อความตาม app/core/messages.py
  2. single instance: เปิดโปรแกรมซ้ำ -> ตัวใหม่ต่อ pipe ได้ = มีตัวเดิมอยู่แล้ว
     ส่ง command{name:"focus"} (พร้อม argv เช่นลิงก์) แล้วปิดตัวเอง
ข้อความที่รับได้ส่งเข้า EventBus เป็นเหตุการณ์ "bridge.message" {type, payload, client}
(QLocalSocket อยู่ใน Qt event loop ของ UI thread — handler ฝั่ง controller ต้องส่งงานต่อไป IoThread เอง)

ต้องสร้าง BridgeServer หลังมี QGuiApplication แล้วเท่านั้น (ใช้ใน UI thread)
"""

from __future__ import annotations

from typing import Any

from app.bridge.host import pipe_name, pipe_path
from app.core.events import BRIDGE_MESSAGE
from app.core.log import get_logger
from app.core.messages import Envelope, FrameDecoder, MessageError, encode_frame

log = get_logger("bridge")


class BridgeServer:
    """เฟส 1: single instance + รับข้อความดิบเข้า bus · เฟส 2: โปรโตคอลส่วนขยายเต็มรูปแบบ"""

    def __init__(self, bus: Any) -> None:
        self.bus = bus
        self._server: Any = None
        self._clients: dict[Any, FrameDecoder] = {}

    def start(self) -> bool:
        """เปิด server คืน False ถ้าเปิดไม่ได้ (เช่น มีโปรแกรมอีกตัวเปิดอยู่แล้ว)"""
        from PySide6.QtNetwork import QLocalServer

        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(pipe_name()):
            # pipe ค้างจาก crash รอบก่อน (ไม่มีใครฟังอยู่จริง) — notify_existing_instance ตรวจก่อนแล้วว่าไม่มีตัวเดิม
            QLocalServer.removeServer(pipe_name())
            if not server.listen(pipe_name()):
                log.error("เปิด named pipe ไม่ได้", extra={"data": {"err": server.errorString()}})
                return False
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        for sock in list(self._clients):
            sock.disconnectFromServer()
        self._clients.clear()

    # ---------- รับข้อความ ----------
    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._clients[sock] = FrameDecoder()
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(lambda s=sock: self._on_disconnected(s))

    def _on_disconnected(self, sock: Any) -> None:
        self._clients.pop(sock, None)
        sock.deleteLater()

    def _on_ready(self, sock: Any) -> None:
        dec = self._clients.get(sock)
        if dec is None:
            return
        try:
            for raw in dec.feed(bytes(sock.readAll().data())):
                env = Envelope.from_dict(raw)
                self.bus.publish(BRIDGE_MESSAGE, {"type": env.type, "payload": env.payload, "id": env.id,
                                                  "client": id(sock)})
        except (MessageError, ValueError) as e:  # ข้อความเสีย: log แล้วทิ้ง ห้ามทำให้โปรแกรมพัง
            log.warning("bridge: ข้อความผิดรูปแบบ", extra={"data": {"err": str(e)}})

    # ---------- ส่งข้อความ ----------
    def send(self, type_: str, payload: dict[str, Any]) -> None:
        """ส่งข้อความถึงส่วนขยายทุกตัวที่เชื่อมอยู่ (UI thread เท่านั้น)"""
        frame = encode_frame(Envelope.new(type_, payload))
        for sock in list(self._clients):
            sock.write(frame)
            sock.flush()


def notify_existing_instance(argv: list[str]) -> bool:
    """เรียกตอนเปิดโปรแกรม: ถ้ามีตัวเดิมอยู่ ส่ง focus + argv แล้วคืน True (ตัวใหม่ต้องปิดตัวเอง)

    ไม่ใช้ Qt (เรียกก่อนสร้าง QApplication): เปิด named pipe ของ Windows ด้วย open() ธรรมดา
    """
    try:
        with open(pipe_path(), "r+b", buffering=0) as f:
            f.write(encode_frame(Envelope.new("command", {"name": "focus", "argv": argv})))
        return True
    except OSError:
        return False
