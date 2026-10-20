"""คีย์ลัดทั้งระบบ (ใช้ได้แม้ไม่ได้โฟกัสโปรแกรม) ผ่าน Windows RegisterHotKey — UX UI ข้อ 8.4

- parse_hotkey("Ctrl+Alt+L") -> (modifiers, vk) · ต้องมี modifier อย่างน้อยหนึ่งตัว (กันแย่งปุ่มธรรมดาทั้งระบบ)
- HotkeyManager: เธรดเดียววน GetMessage รับ WM_HOTKEY แล้วเรียก callback(ชื่อ) (ในเธรดนี้ — ผู้เรียกต้องส่งต่อเข้า UI thread เอง)
  ลงทะเบียนไม่สำเร็จ (คีย์ซ้ำกับโปรแกรมอื่น/ผิดรูปแบบ) = รายงานเป็นข้อความต่อคีย์ ไม่ทำให้คีย์อื่นพัง
- ไม่ import PySide6 — ใช้ ctypes เท่านั้น (ส่วนที่แตะ Windows ถูกเรียกเฉพาะตอนเริ่มเธรด จึง import บน OS อื่นได้)
"""

from __future__ import annotations

import ctypes
import re
import threading
from collections.abc import Callable

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN, "meta": MOD_WIN}
_NAMED = {
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "space": 0x20, "enter": 0x0D, "tab": 0x09,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D, "delete": 0x2E,
    "-": 0xBD, "=": 0xBB, "+": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "`": 0xC0,
}


class HotkeyError(ValueError):
    """รูปแบบคีย์ลัดผิด"""


def parse_hotkey(text: str) -> tuple[int, int]:
    """"Ctrl+Alt+L" -> (modifiers, virtual-key) · ผิดรูปแบบโยน HotkeyError (ข้อความภาษาไทยแสดงผู้ใช้ได้)"""
    parts = [p.strip() for p in (text or "").replace(" ", "").split("+") if p.strip()]
    if text.strip().endswith("++"):  # "Ctrl++" = Ctrl กับปุ่ม +
        parts.append("+")
    if not parts:
        raise HotkeyError("ว่างเปล่า")
    mods = 0
    key: str | None = None
    for p in parts:
        low = p.lower()
        if low in _MODS:
            mods |= _MODS[low]
        elif key is None:
            key = low
        else:
            raise HotkeyError(f"มีปุ่มหลักมากกว่าหนึ่งปุ่ม ({text})")
    if not mods:
        raise HotkeyError("ต้องมี Ctrl, Alt, Shift หรือ Win อย่างน้อยหนึ่งตัว")
    if key is None:
        raise HotkeyError("ไม่มีปุ่มหลัก")
    if key in _NAMED:
        return mods, _NAMED[key]
    if re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", key):
        return mods, 0x70 + int(key[1:]) - 1
    if len(key) == 1 and key.isascii() and key.isalnum():
        return mods, ord(key.upper())
    raise HotkeyError(f"ไม่รู้จักปุ่ม {key!r}")


class HotkeyManager:
    """ลงทะเบียนชุดคีย์ลัด (ชื่อ -> ข้อความคีย์) และเรียก callback(ชื่อ) เมื่อถูกกด"""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._lock = threading.Lock()

    def set_bindings(self, bindings: dict[str, str]) -> dict[str, str]:
        """เริ่ม/เปลี่ยนชุดคีย์ลัด (หยุดชุดเก่าก่อน) คืน {ชื่อ: ข้อความผิดพลาด} ของที่ใช้ไม่ได้ — ชุดว่าง = หยุดทั้งหมด"""
        self.stop()
        errors: dict[str, str] = {}
        parsed: dict[str, tuple[int, int]] = {}
        seen: dict[tuple[int, int], str] = {}
        for name, text in bindings.items():
            if not (text or "").strip():
                continue  # ว่าง = ปิดคีย์ลัดนั้น
            try:
                combo = parse_hotkey(text)
            except HotkeyError as e:
                errors[name] = f"{name}: {e}"
                continue
            if combo in seen:
                errors[name] = f"{name}: ซ้ำกับ {seen[combo]}"
                continue
            seen[combo] = name
            parsed[name] = combo
        if not parsed:
            return errors
        ready = threading.Event()
        result: dict[str, str] = {}
        self._thread = threading.Thread(target=self._run, args=(parsed, ready, result), name="hotkeys", daemon=True)
        self._thread.start()
        ready.wait(3.0)
        errors.update(result)
        return errors

    def stop(self) -> None:
        with self._lock:
            tid, th = self._thread_id, self._thread
            self._thread_id, self._thread = 0, None
        if th is not None and tid:
            try:
                ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
            th.join(1.0)

    def _run(self, parsed: dict[str, tuple[int, int]], ready: threading.Event, errors: dict[str, str]) -> None:
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        except AttributeError:  # ไม่ใช่ Windows
            ready.set()
            return
        with self._lock:
            self._thread_id = kernel32.GetCurrentThreadId()
        ids: dict[int, str] = {}
        for i, (name, (mods, vk)) in enumerate(parsed.items(), start=1):
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                ids[i] = name
            else:
                errors[name] = f"{name}: คีย์นี้ถูกโปรแกรมอื่นใช้อยู่ (ลองเปลี่ยนคีย์)"
        ready.set()
        msg = ctypes.wintypes.MSG() if hasattr(ctypes, "wintypes") else None
        if msg is None:
            import ctypes.wintypes as wt

            msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                try:
                    self.callback(ids[msg.wParam])
                except Exception:  # noqa: BLE001 — callback พังห้ามทำให้เธรดคีย์ลัดหยุด
                    pass
        for i in ids:
            user32.UnregisterHotKey(None, i)
