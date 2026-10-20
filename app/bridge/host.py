"""Native messaging host — process เล็กที่ Chrome เปิดเมื่อส่วนขยายเรียก connectNative (ข้อ 10.1)

หน้าที่เดียว: ส่งต่อข้อความสองทางระหว่าง stdin/stdout ของ Chrome กับ named pipe ของโปรแกรมหลัก
  - ต่อ pipe \\\\.\\pipe\\synclyrics-<username> ไม่ได้ (โปรแกรมไม่ได้เปิด) -> รอเงียบๆ เช็กทุก 1 วิ
    **ไม่เปิดโปรแกรมเอง** (ไม่งั้นผู้ใช้ปิดโปรแกรมไม่ได้ เพราะส่วนขยายต่อใหม่ตลอด) เปิดเฉพาะเมื่อส่วนขยาย
    สั่ง launch_app (กดไอคอน / "เล่นเลย") — ดู HostBridge
  - pipe หลุด (ปิดโปรแกรม) -> ส่ง status{connected:false} แล้วรอ pipe ใหม่ (host ไม่จบ ส่วนขยายไม่ต้องต่อใหม่)
ต้องเบาและไม่ import PySide6/numpy (เปิดเร็ว) — build เป็น exe แยก: synclyrics-host.exe
stdout ใช้ส่งข้อความเท่านั้น ห้าม print อย่างอื่น (จะทำให้ protocol พัง) — log ลงไฟล์

กับดักของ Windows: handle แบบ synchronous อ่านค้างอยู่ในเธรดหนึ่ง = เขียนจากอีกเธรดไม่ได้ (ถูกล็อก)
จึงฝั่งอ่านจาก pipe ใช้ PeekNamedPipe ถามก่อนว่ามีข้อมูลไหมค่อยอ่าน (ไม่บล็อก) ฝั่งเขียนทำได้ตลอด
"""

from __future__ import annotations

import ctypes
import getpass
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO

HOST_NAME = "com.synclyrics.host"
CONNECT_TIMEOUT_S = 15.0
CONNECT_RETRY_S = 0.25
PEEK_INTERVAL_S = 0.005
MAX_FRAME = 64 * 1024 * 1024


def pipe_name() -> str:
    """ชื่อ named pipe ที่โปรแกรมหลักเปิด (QLocalServer ใช้ชื่อนี้ — ต้องตรงกันทั้งสองฝั่ง)

    ตัวแปรสภาพแวดล้อม SYNCLYRICS_PIPE ใช้แทนชื่อ (ไว้ทดสอบ end-to-end แยกจากโปรแกรมที่ผู้ใช้เปิดอยู่จริง —
    host ที่ Chrome เปิดสืบทอด env จาก Chrome จึงตามไปด้วย)
    """
    override = os.environ.get("SYNCLYRICS_PIPE", "")
    if override:
        return re.sub(r"[^A-Za-z0-9_-]", "_", override)
    user = re.sub(r"[^A-Za-z0-9_-]", "_", getpass.getuser())
    return f"synclyrics-{user}"


def pipe_path() -> str:
    return rf"\\.\pipe\{pipe_name()}"


# ---------------------------------------------------------------------------
# อ่านแบบไม่บล็อกจาก pipe
# ---------------------------------------------------------------------------
def _available_bytes(f: BinaryIO) -> int | None:
    """จำนวนไบต์ที่อ่านได้ทันที (0 = ยังไม่มี) หรือ None ถ้า pipe ปิดแล้ว/พัง"""
    import msvcrt

    handle = msvcrt.get_osfhandle(f.fileno())
    avail = ctypes.c_ulong(0)
    ok = ctypes.windll.kernel32.PeekNamedPipe(  # type: ignore[attr-defined]
        ctypes.c_void_p(handle), None, 0, None, ctypes.byref(avail), None)
    return int(avail.value) if ok else None


def read_exact_pipe(f: BinaryIO, n: int, stop: threading.Event) -> bytes | None:
    """อ่าน n ไบต์จาก pipe โดยไม่ล็อก handle; คืน None เมื่อ pipe ปิดหรือสั่งหยุด"""
    out = bytearray()
    while len(out) < n:
        if stop.is_set():
            return None
        avail = _available_bytes(f)
        if avail is None:
            return None
        if avail == 0:
            time.sleep(PEEK_INTERVAL_S)
            continue
        chunk = f.read(min(avail, n - len(out)))
        if not chunk:
            return None
        out.extend(chunk)
    return bytes(out)


def read_frame_pipe(f: BinaryIO, stop: threading.Event) -> bytes | None:
    """อ่านข้อความ 1 ก้อน (ตัวความยาว uint32 LE ตามด้วยเนื้อหา) คืนเนื้อหา JSON ดิบ"""
    head = read_exact_pipe(f, 4, stop)
    if head is None:
        return None
    (n,) = struct.unpack("<I", head)
    if n > MAX_FRAME:
        return None
    return read_exact_pipe(f, n, stop) if n else b""


def read_frame_stdio(f: BinaryIO) -> bytes | None:
    """อ่านข้อความจาก stdin ของ Chrome (บล็อกได้ เพราะ stdin เป็นของเธรดหลักเท่านั้น)"""
    head = f.read(4)
    if len(head) < 4:
        return None
    (n,) = struct.unpack("<I", head)
    if n > MAX_FRAME:
        return None
    body = f.read(n)
    return body if len(body) == n else None


def write_frame(f: BinaryIO, body: bytes) -> None:
    f.write(struct.pack("<I", len(body)) + body)
    f.flush()


def _envelope(type_: str, payload: dict) -> bytes:
    return json.dumps({"v": 1, "type": type_, "id": "", "payload": payload},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# เปิดโปรแกรมหลัก
# ---------------------------------------------------------------------------
def launch_command() -> list[str] | None:
    """คำสั่งเปิดโปรแกรมหลัก (--from-host) · dev: .venv ของโปรเจกต์ · ตัวติดตั้ง: SyncLyrics.exe ข้างๆ host"""
    here = Path(sys.executable).resolve().parent
    exe = here / "SyncLyrics.exe"
    if exe.exists():
        return [str(exe), "--from-host"]
    root = Path(__file__).resolve().parents[2]
    pyw = root / ".venv" / "Scripts" / "pythonw.exe"
    if pyw.exists():
        return [str(pyw), "-m", "app", "--from-host"]
    return None


def start_main_app() -> bool:
    cmd = launch_command()
    if cmd is None:
        return False
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    try:
        subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[2]), creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True)
        return True
    except OSError:
        return False



def try_open_pipe(path: str | None = None) -> BinaryIO | None:
    """ต่อ named pipe ของโปรแกรมหลัก; ต่อไม่ได้ (โปรแกรมไม่ได้เปิด) = None ห้ามเปิดโปรแกรมให้เอง"""
    try:
        return open(path or pipe_path(), "r+b", buffering=0)  # noqa: SIM115
    except OSError:
        return None


# ---------------------------------------------------------------------------
# ตัวส่งต่อ
# ---------------------------------------------------------------------------
class HostBridge:
    """ส่งต่อข้อความ Chrome <-> โปรแกรมหลัก โดย host อยู่ได้ตลอดแม้โปรแกรมหลักยังไม่เปิด

    เหตุผล: ถ้า host เปิดโปรแกรมให้ทุกครั้งที่ต่อไม่ได้ + ส่วนขยายต่อใหม่ทุก 2 วิ ผู้ใช้จะปิดโปรแกรมไม่ได้เลย
    จึงให้ host รอเงียบๆ (เช็ก pipe ทุก 1 วิ) และเปิดโปรแกรมก็ต่อเมื่อส่วนขยายสั่ง {"type":"launch_app"}
    (กดไอคอน/ปุ่ม "เล่นเลย") ข้อความที่ host จัดการเอง ไม่ส่งต่อ: launch_app
    ข้อความที่ host ส่งให้ส่วนขยายเอง: host_connected (pipe ต่อติด -> ส่วนขยายส่ง hello), status{connected:false},
    error{code:"app_not_running"}
    """

    def __init__(self, stdin: BinaryIO, stdout: BinaryIO, open_pipe=try_open_pipe, launch=start_main_app,  # noqa: ANN001
                 poll_s: float = 1.0) -> None:
        self.stdin, self.stdout = stdin, stdout
        self._open_pipe, self._launch, self._poll_s = open_pipe, launch, poll_s
        self._pipe: BinaryIO | None = None
        self._lock = threading.Lock()  # ป้องกัน self._pipe
        self._out_lock = threading.Lock()  # stdout เขียนทีละข้อความ
        self._stop = threading.Event()

    def _to_chrome(self, body: bytes) -> None:
        with self._out_lock:
            write_frame(self.stdout, body)

    def _pipe_loop(self) -> None:
        """เธรดลูก: รอ pipe -> ส่ง host_connected -> อ่านข้อความส่งให้ Chrome -> pipe หลุด -> วนรอใหม่"""
        while not self._stop.is_set():
            pipe = self._open_pipe()
            if pipe is None:
                self._stop.wait(self._poll_s)
                continue
            try:
                with self._lock:
                    self._pipe = pipe
                self._to_chrome(_envelope("host_connected", {}))
                while not self._stop.is_set():
                    body = read_frame_pipe(pipe, self._stop)
                    if body is None:
                        break
                    self._to_chrome(body)
            except (OSError, ValueError):
                pass
            finally:
                with self._lock:
                    self._pipe = None
                try:
                    pipe.close()
                except OSError:
                    pass
                try:
                    self._to_chrome(_envelope("status", {"connected": False}))
                except (OSError, ValueError):
                    self._stop.set()  # Chrome ปิด stdout แล้ว = จบ

    def _handle_chrome(self, body: bytes) -> None:
        try:
            msg = json.loads(body.decode("utf-8"))
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("type") == "launch_app":
            self._launch()
            return
        with self._lock:
            pipe = self._pipe
            if pipe is not None:
                try:
                    write_frame(pipe, body)
                    return
                except (OSError, ValueError):
                    pass
        self._to_chrome(_envelope("error", {"code": "app_not_running", "message": "โปรแกรม SyncLyrics ยังไม่เปิด"}))

    def run(self) -> None:
        """วนอ่าน stdin ของ Chrome จนปิด (เธรดหลัก)"""
        t = threading.Thread(target=self._pipe_loop, daemon=True, name="host-pipe")
        t.start()
        try:
            while not self._stop.is_set():
                body = read_frame_stdio(self.stdin)
                if body is None:  # Chrome ปิด port
                    break
                self._handle_chrome(body)
        except (OSError, ValueError):
            pass
        finally:
            self._stop.set()


def _setup_log() -> None:
    """log ข้อผิดพลาดของ host ลงไฟล์ (stdout ห้ามใช้)"""
    try:
        base = Path(os.environ.get("SYNCLYRICS_HOME") or Path(os.environ.get("LOCALAPPDATA", ".")) / "SyncLyrics")
        (base / "logs").mkdir(parents=True, exist_ok=True)
        sys.stderr = open(base / "logs" / "bridge-host.log", "a", encoding="utf-8")  # noqa: SIM115
    except OSError:
        pass


def main() -> int:
    """จุดเริ่มของ synclyrics-host: Chrome เปิดด้วย stdin/stdout เป็น pipe"""
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    _setup_log()
    HostBridge(sys.stdin.buffer, sys.stdout.buffer).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
