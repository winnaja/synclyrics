"""ธีมสำเร็จรูปของหน้าต่างเนื้อเพลงลอย (UX UI ข้อ 2.2) — ค่าที่ธีมกำหนดทับลงใน OverlaySettings

ทุกธีมออกแบบให้ตัวอักษรอ่านง่ายทั้งบนวอลเปเปอร์สว่างและมืด (เงาตัวอักษร + พื้นหลังโปร่งแสงพอประมาณ)
"custom" ไม่เปลี่ยนค่าอะไร (ผู้ใช้ปรับเอง) · แก้ค่าด้านล่างเพื่อปรับธีม ไม่มีค่าสีฝังในที่อื่น
"""

from __future__ import annotations

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "soft_dark": {
        "bg_style": "soft_dark", "bg_color": "#0B0B10", "bg_opacity": 0.62, "border_opacity": 0.08,
        "text_color": "#F5F5F7", "accent_color": "#A5B4FC", "inactive_color": "#777780", "secondary_color": "#A1A1AA",
        "text_shadow": 0.6, "shadow": 0.5,
    },
    "pure_black": {
        "bg_style": "solid", "bg_color": "#000000", "bg_opacity": 0.94, "border_opacity": 0.05,
        "text_color": "#FFFFFF", "accent_color": "#A5B4FC", "inactive_color": "#6B6B73", "secondary_color": "#9A9AA3",
        "text_shadow": 0.0, "shadow": 0.35,
    },
    "frosted": {
        "bg_style": "frosted", "bg_color": "#16161F", "bg_opacity": 0.45, "border_opacity": 0.16,
        "text_color": "#FFFFFF", "accent_color": "#C4B5FD", "inactive_color": "#8A8A96", "secondary_color": "#B4B4C0",
        "text_shadow": 0.5, "shadow": 0.6,
    },
    "minimal_transparent": {
        "bg_style": "transparent", "bg_color": "#000000", "bg_opacity": 0.0, "border_opacity": 0.0,
        "text_color": "#FFFFFF", "accent_color": "#A5B4FC", "inactive_color": "#C8C8D0", "secondary_color": "#D0D0D8",
        "text_shadow": 1.0, "shadow": 0.0,
    },
    "light": {
        "bg_style": "solid", "bg_color": "#F5F5F7", "bg_opacity": 0.88, "border_opacity": 0.12,
        "text_color": "#1C1C1E", "accent_color": "#4F46E5", "inactive_color": "#8E8E93", "secondary_color": "#5E5E66",
        "text_shadow": 0.0, "shadow": 0.3,
    },
    "custom": {},
}

THEME_NAMES_TH: dict[str, str] = {
    "soft_dark": "Soft Dark", "pure_black": "Pure Black", "frosted": "Frosted Glass",
    "minimal_transparent": "Minimal Transparent", "light": "Light", "custom": "กำหนดเอง",
}

# ค่าที่ธีมเป็นเจ้าของ: ผู้ใช้แก้ค่าพวกนี้เองเมื่อไหร่ ธีมจะกลายเป็น "custom" อัตโนมัติ
THEME_OWNED_KEYS: frozenset[str] = frozenset(
    {k for preset in PRESETS.values() for k in preset})


def preset_values(name: str) -> dict[str, Any]:
    """ค่าของธีม (สำเนา) — ชื่อไม่รู้จัก = ว่าง"""
    return dict(PRESETS.get(name, {}))
