"""เอฟเฟกต์ของหน้าต่างบน Windows (ctypes ล้วน): เบลอฉากหลังจริง (acrylic) + ตัดมุมหน้าต่างให้โค้ง — UX UI ข้อ 5.3

ใช้กับหน้าต่างเนื้อเพลงลอยเมื่อเลือกพื้นหลัง "กระจกฝ้า" (cfg.ov_bg_style == "frosted" และ ov_blur_behind)
- SetWindowCompositionAttribute (ไม่เป็นทางการแต่ใช้ได้ Windows 10 1803+ / 11 กับหน้าต่าง frameless) ACCENT_ENABLE_ACRYLICBLURBEHIND
- พื้นที่ blur เป็นสี่เหลี่ยมทั้งหน้าต่าง จึงต้อง SetWindowRgn เป็นสี่เหลี่ยมมุมโค้งรัศมีเดียวกับพื้นหลังใน QML ไม่งั้นมุมจะมี blur ล้นออกมา
ระบบไม่รองรับ/เรียกไม่สำเร็จ = คืน False เงียบๆ (UI ใช้พื้นโปร่งแสงแทน — spec อนุญาต) ห้ามทำให้โปรแกรมพัง
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


class _AccentPolicy(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _CompositionData(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]


def supported() -> bool:
    return sys.platform == "win32"


def _set_accent(hwnd: int, state: int, tint_abgr: int = 0) -> bool:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    fn = getattr(user32, "SetWindowCompositionAttribute", None)
    if fn is None:
        return False
    policy = _AccentPolicy(state, 2 if state else 0, tint_abgr, 0)
    data = _CompositionData(WCA_ACCENT_POLICY, ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p), ctypes.sizeof(policy))
    fn.argtypes = [wintypes.HWND, ctypes.POINTER(_CompositionData)]
    fn.restype = wintypes.BOOL
    return bool(fn(hwnd, ctypes.byref(data)))


def _set_round_region(hwnd: int, width_px: int, height_px: int, radius_px: int) -> bool:
    gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32  # type: ignore[attr-defined]
    if radius_px <= 0:
        return bool(user32.SetWindowRgn(hwnd, None, True))
    rgn = gdi32.CreateRoundRectRgn(0, 0, width_px + 1, height_px + 1, radius_px * 2, radius_px * 2)
    if not rgn:
        return False
    if not user32.SetWindowRgn(hwnd, rgn, True):  # สำเร็จ = ระบบเป็นเจ้าของ region แล้ว (ห้าม DeleteObject)
        gdi32.DeleteObject(rgn)
        return False
    return True


DWM_CORNER_RADIUS_PX = 8  # DWMWCP_ROUND ของ Windows 11 (รัศมีคงที่ของระบบ)


def _set_dwm_round(hwnd: int, round_on: bool) -> bool:
    """มุมโค้งแบบระบบ (Windows 11): ตัดทั้งภาพและเบลอ — สำเร็จ = True · Windows 10 ไม่รองรับ (คืน False ให้ใช้ region แทน)"""
    try:
        pref = ctypes.c_int(2 if round_on else 1)  # DWMWCP_ROUND / DWMWCP_DONOTROUND
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))  # type: ignore[attr-defined]
        return hr == 0
    except Exception:  # noqa: BLE001
        return False


def apply_blur_behind(hwnd: int, enabled: bool, width_px: int, height_px: int, radius_px: int,
                      tint_rgb: tuple[int, int, int] = (20, 20, 28), tint_alpha: int = 0x30) -> bool:
    """เปิด/ปิดเบลอฉากหลังของหน้าต่าง (พิกเซลจริงของอุปกรณ์ ไม่ใช่พิกเซลตามสเกล) คืน True ถ้าทำสำเร็จ"""
    if not supported() or not hwnd:
        return False
    try:
        if not enabled:
            _set_accent(hwnd, ACCENT_DISABLED)
            _set_dwm_round(hwnd, False)
            _set_round_region(hwnd, width_px, height_px, 0)
            return True
        r, g, b = tint_rgb
        ok = _set_accent(hwnd, ACCENT_ENABLE_ACRYLICBLURBEHIND, (tint_alpha << 24) | (b << 16) | (g << 8) | r)
        if ok and not _set_dwm_round(hwnd, True):  # ไม่ใช่ Windows 11: ตัดด้วย region (รัศมีตามที่ผู้ใช้ตั้ง)
            _set_round_region(hwnd, width_px, height_px, radius_px)
        return ok
    except Exception:  # noqa: BLE001 — เอฟเฟกต์ตกแต่งพังห้ามทำให้โปรแกรมพัง
        return False
