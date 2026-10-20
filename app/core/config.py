"""โหลดไฟล์ config ทั้งหมด พร้อมตรวจรูปแบบ แปลงเวอร์ชันเก่า และรวมค่าของผู้ใช้

ไฟล์ config (ค่าเริ่มต้นอยู่ใน <โปรเจกต์>/config, ของผู้ใช้อยู่ใน %LOCALAPPDATA%/SyncLyrics/config):
  settings.yaml        การตั้งค่าในหน้า Settings     -> Settings
  models.yaml          โมเดล AI และงบ VRAM            -> ModelsConfig
  automix_rules.yaml   กฎ AutoMix (แก้แล้วมีผลทันที)   -> AutomixRules
  selectors.json       selector ของหน้า YouTube        -> dict (ส่วนขยายเป็นคนใช้)

ลำดับ: อ่านค่าเริ่มต้น -> อ่านของผู้ใช้ (ถ้ามี) -> แปลงเวอร์ชันเก่า -> รวมแบบ deep merge -> ตรวจด้วย pydantic
ไฟล์ของผู้ใช้พัง: log + ใช้ค่าเริ่มต้น (ห้ามทำให้โปรแกรมเปิดไม่ได้) — ข้อ 11.2

เปลี่ยนรูปแบบไฟล์ = เพิ่ม CURRENT_VERSIONS + ฟังก์ชันใน MIGRATORS ห้ามแก้ไฟล์ผู้ใช้ทิ้งโดยไม่สำรอง
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.paths import PROJECT_ROOT, AppPaths

CURRENT_VERSIONS: dict[str, int] = {
    "settings.yaml": 5,
    "models.yaml": 1,
    "automix_rules.yaml": 1,
    "selectors.json": 1,
}

# MIGRATORS[ชื่อไฟล์][v] = ฟังก์ชันแปลงข้อมูลจาก v -> v+1
MIGRATORS: dict[str, dict[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    name: {} for name in CURRENT_VERSIONS
}


def _settings_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """v2 (2026-10-20): ค่าแอนิเมชัน/ความจาง/เบลอ ปรับใหม่ตามคลิป Apple Music ที่วัดจริง — ไฟล์ผู้ใช้เก่าเก็บค่าเดิมไว้ทุกตัว (ค่าเริ่มต้นใหม่จะไม่มีผล)
    จึงลบคีย์เหล่านี้ออกครั้งเดียว ให้กลับไปใช้ค่าเริ่มต้นใหม่ (ผู้ใช้ปรับเองต่อได้ตามปกติหลังจากนี้)"""
    drop = {
        "overlay": ("anim_preset", "animation", "animation_intensity", "anim_speed", "wave_ms", "blur", "falloff", "idle_scale", "lift_px",
                    "word_anim", "word_ease", "word_anim_ms", "word_scale", "glow_strength", "glow_color", "word_hold_ms", "word_release_ms",
                    "emph_on", "weight_boost"),
        "lyrics_look": ("spring_stiffness", "spring_damping"),
        "fullwindow": ("inactive_opacity", "blur", "falloff"),
    }
    for group, keys in drop.items():
        sec = data.get(group)
        if isinstance(sec, dict):
            for k in keys:
                sec.pop(k, None)
    return data


MIGRATORS["settings.yaml"][1] = _settings_v1_to_v2


def _settings_v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """v3 (2026-10-20): word_anim เหลือ none/word/char (lift/rise/pop/glow/glow_rise เดิมแปลงเป็น word + ปริมาณลอย/ขยาย/แสงที่เทียบเท่า)"""
    ov = data.get("overlay")
    if isinstance(ov, dict):
        wa = ov.get("word_anim")
        if wa in ("lift", "rise", "pop", "glow", "glow_rise"):
            ov["word_anim"] = "word"
            if wa in ("lift", "rise", "glow_rise") and float(ov.get("lift_px", 0) or 0) <= 0:
                ov["lift_px"] = 3.0
            if wa == "pop" and float(ov.get("word_scale", 1) or 1) <= 1.0:
                ov["word_scale"] = 1.1
            if wa in ("glow", "glow_rise") and float(ov.get("glow_strength", 0) or 0) <= 0:
                ov["glow_strength"] = 0.6
    return data


MIGRATORS["settings.yaml"][2] = _settings_v2_to_v3


def _settings_v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """v4 (2026-10-20): ปุ่มปิด (กากบาท) ปิดโปรแกรมจริงเป็นค่าเริ่มต้น (เดิมซ่อนลง tray แล้วโผล่หน้าต่างเล็ก ผู้ใช้งง) — ล้างค่าเดิมครั้งเดียว"""
    for sec in (data.get("startup"),):
        if isinstance(sec, dict):
            sec.pop("close_to_tray", None)
    return data


MIGRATORS["settings.yaml"][3] = _settings_v3_to_v4


def _settings_v4_to_v5(data: dict[str, Any]) -> dict[str, Any]:
    """v5 (2026-10-21): คำเน้นเปิดเป็นค่าเริ่มต้น (AI เลือกคำเน้น) — ล้างค่า emph_on เดิมที่บันทึกไว้ (เคยปิด) ครั้งเดียว"""
    ov = data.get("overlay")
    if isinstance(ov, dict):
        ov.pop("emph_on", None)
    return data


MIGRATORS["settings.yaml"][4] = _settings_v4_to_v5


class ConfigError(Exception):
    """ไฟล์ config ผิดรูปแบบ"""


class _Model(BaseModel):
    # ignore key ที่ไม่รู้จัก: ไฟล์จากเวอร์ชันใหม่กว่าจะไม่ทำให้โปรแกรมเก่าพัง
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


# ---------------------------------------------------------------------------
# settings.yaml
# ---------------------------------------------------------------------------
class LyricsLook(_Model):
    # ฟอนต์หลักสำหรับไทย+อังกฤษ (ผู้ใช้เลือก SF Thonburi — ฟอนต์ของ Apple ติดตั้งในเครื่องผู้ใช้เอง ไม่รวมมากับโปรแกรม)
    font_family: str = "SF Thonburi"
    # ไม่มีฟอนต์หลักในเครื่อง -> ใช้ตัวแรกที่มี (ฟรีและฝังกับตัวติดตั้งในเฟส 3/8)
    font_fallbacks: list[str] = ["Prompt", "Noto Sans Thai", "Kanit", "Segoe UI"]
    font_size: int = Field(44, ge=12, le=160)
    font_weight: int = Field(700, ge=100, le=900)
    line_spacing: float = Field(1.25, ge=0.8, le=3.0)
    letter_spacing: float = Field(0.0, ge=-5, le=20)
    align: Literal["left", "center", "right"] = "left"
    visible_lines: int = Field(7, ge=1, le=21)
    color_sung: str = "#FFFFFF"
    color_active: str = "#FFFFFF"
    color_unsung: str = "#FFFFFF66"
    glow_color: str | Literal["auto"] = "auto"
    blur_strength: float = Field(1.0, ge=0, le=3)
    glow_strength: float = Field(1.0, ge=0, le=3)
    animation_speed: float = Field(1.0, ge=0.25, le=4)
    spring_stiffness: float = Field(256.0, ge=10, le=1000)
    spring_damping: float = Field(32.0, ge=1, le=200)
    highlight_effect: Literal[
        "wipe", "glow", "bounce", "scale", "karaoke", "fade", "typewriter"
    ] = "wipe"
    show_translation: bool = True
    translation_scale: float = Field(0.55, ge=0.2, le=1.5)
    show_romanization: bool = False
    romanization_scale: float = Field(0.5, ge=0.2, le=1.5)


class BackgroundSettings(_Model):
    kind: Literal["fluid", "blur_cover", "video", "solid", "gradient", "image"] = "fluid"
    blur: float = Field(1.0, ge=0, le=3)
    brightness: float = Field(0.8, ge=0, le=2)
    speed: float = Field(1.0, ge=0, le=4)
    beat_pulse: bool = True
    chorus_brighten: bool = False
    solid_color: str = "#111318"
    gradient: list[str] = ["#1b1f3b", "#402b5a"]
    image_path: str | None = None


class DesktopLyricsSettings(_Model):
    enabled: bool = False
    locked: bool = True
    click_through: bool = True
    lines: int = Field(2, ge=1, le=2)
    font_size: int = Field(32, ge=10, le=120)
    color: str = "#FFFFFF"
    shadow: float = Field(0.8, ge=0, le=3)
    x: int | None = None
    y: int | None = None
    width: int | None = None


class OverlaySettings(_Model):
    """หน้าต่างเนื้อเพลงลอย (ตาม add by win/UX UI.txt) — ทุกค่ามีผลทันที ไม่ต้องเปิดโปรแกรมใหม่"""

    # ---- โหมดและหน้าต่าง ----
    # minimal = บรรทัดเดียว · focus = 3 บรรทัด (ค่าเริ่มต้น) · "full" เป็นค่าเก่า (ตอนนี้โหมดเต็มคือหน้าต่างแยก FullWindowSettings;
    # ค่านี้ยังรับได้เพื่อไม่ให้ไฟล์ตั้งค่าเก่าพัง — main.py แปลงเป็น focus ตอนเปิด)
    mode: Literal["minimal", "focus", "full"] = "focus"
    visible: bool = True
    always_on_top: bool = True
    locked: bool = False            # ล็อกตำแหน่ง/ขนาด กันลากพลาด
    click_through: bool = False     # เมาส์ทะลุหน้าต่าง (ปิดได้จาก tray / คีย์ลัด)
    remember_position: bool = True
    start_position: Literal["center", "center_h", "top_center", "bottom_center", "top_left", "top_right",
                            "bottom_left", "bottom_right"] = "bottom_center"  # ใช้เมื่อยังไม่เคยจำตำแหน่ง/ปิดการจำตำแหน่ง
    monitor: int = Field(0, ge=0, le=15)  # จอที่ใช้ตอนเริ่ม (ลำดับตาม Windows)
    window_opacity: float = Field(1.0, ge=0.3, le=1)  # ความโปร่งใสทั้งหน้าต่าง (UX UI ข้อ 5.2)
    blur_behind: bool = True  # พื้นหลัง "กระจกฝ้า" ใช้เบลอฉากหลังจริงของ Windows (acrylic) — ปิด/ไม่รองรับ = พื้นโปร่งแสง
    x: int | None = None
    y: int | None = None
    # ขนาดจำแยกตามโหมด
    w_minimal: int = Field(760, ge=240, le=4000)
    h_minimal: int = Field(110, ge=60, le=2000)
    w_focus: int = Field(760, ge=240, le=4000)
    h_focus: int = Field(230, ge=100, le=2000)
    w_full: int = Field(1000, ge=420, le=4000)
    h_full: int = Field(680, ge=320, le=2400)

    # ---- ธีม / พื้นหลัง ----
    theme: Literal["soft_dark", "pure_black", "frosted", "minimal_transparent", "light", "custom"] = "soft_dark"
    bg_style: Literal["transparent", "frosted", "soft_dark", "solid", "gradient", "custom"] = "soft_dark"
    bg_color: str = "#0B0B10"
    bg_color2: str = "#1B1F3B"      # สีที่สองของ gradient
    bg_opacity: float = Field(0.62, ge=0, le=1)       # แยกจากความโปร่งใสของตัวอักษร (UX UI ข้อ 5.2)
    border_opacity: float = Field(0.08, ge=0, le=1)
    shadow: float = Field(0.5, ge=0, le=1)            # เงาของหน้าต่าง
    corner_radius: int = Field(22, ge=0, le=60)

    # ---- ตัวอักษร ----
    text_color: str = "#F5F5F7"      # บรรทัดปัจจุบัน / คำที่ร้องแล้ว
    accent_color: str = "#A5B4FC"    # ไฮไลต์ / glow
    inactive_color: str = "#777780"  # ยังไม่ร้อง
    secondary_color: str = "#A1A1AA" # คำแปล / ข้อความรอง
    text_opacity: float = Field(1.0, ge=0.2, le=1)
    inactive_opacity: float = Field(0.5, ge=0.05, le=1)  # บรรทัดที่ไม่ใช่ปัจจุบัน
    text_shadow: float = Field(0.6, ge=0, le=1)
    font_size: int = Field(34, ge=12, le=120)
    text_width: float = Field(1.0, ge=0.4, le=1.0)    # ความกว้างของข้อความเทียบกับหน้าต่าง (UX UI ข้อ 3.3 "ปรับความกว้างของข้อความ")
    font_weight: int = Field(700, ge=100, le=900)
    weight_boost: int = Field(100, ge=0, le=300)  # บรรทัดปัจจุบันหนาขึ้นกี่หน่วย (Weight highlight, UX UI ข้อ 4.3)
    line_spacing: float = Field(1.15, ge=0.8, le=2.5)
    letter_spacing: float = Field(0.0, ge=-3, le=12)
    align: Literal["left", "center", "right"] = "center"
    visible_lines: int = Field(3, ge=1, le=9)          # จำนวนบรรทัดที่เห็นในโหมด focus

    # ---- เนื้อเพลง/แอนิเมชัน ----
    highlight: Literal["fill", "word", "glow", "line"] = "fill"  # fill = เติมสีซ้ายไปขวา · word = ทีละคำ · glow = เรืองแสง · line = ทั้งบรรทัด
    animation: Literal["fade_move", "fade", "move", "scale"] = "fade_move"
    animation_intensity: float = Field(1.0, ge=0, le=2)
    reduced_motion: bool = False
    # ปรับแต่งแอนิเมชันเนื้อเพลงละเอียด (ผู้ใช้ขอ) — ชุดสำเร็จรูปอยู่ใน app/ui/anim_presets.py
    # ค่าเริ่มต้น = ชุด "smooth" (นุ่มนวลแบบ Apple Music: เลื่อนช้า คลื่นหน่วง เบลอบรรทัดไกล) ให้ตรงกับ app/ui/anim_presets.py
    anim_preset: Literal["smooth", "balanced", "bouncy", "snappy", "none", "custom"] = "smooth"
    anim_speed: float = Field(1.0, ge=0.3, le=3.0)   # ตัวคูณความเร็ว (มาก = เร็ว)
    wave_ms: int = Field(30, ge=0, le=150)            # คลื่น: บรรทัดที่อยู่ต่ำลงไปเริ่มไหลช้ากว่า (ms ต่อ 100 พิกเซล) — Apple Music วัดได้ ~30
    blur: float = Field(0.35, ge=0, le=1)             # เบลอบรรทัดที่ไกลจากบรรทัดปัจจุบัน
    falloff: float = Field(0.12, ge=0.03, le=0.3)     # ความจางต่อบรรทัดที่ไกลขึ้น
    idle_scale: float = Field(0.92, ge=0.6, le=1.0)   # ขนาดบรรทัดที่ไม่ใช่ปัจจุบัน (แอนิเมชันจาง+เลื่อน)
    lift_px: float = Field(0.0, ge=0, le=14)          # ลอยขึ้นกี่พิกเซล (0 = ไม่ลอย) — ใช้กับ word_anim "word"/"char"
    # แอนิเมชันระดับ "คำ" (คาราโอเกะ) — ผู้ใช้ว่าเด้งอย่างเดียวไม่สวย จึงมีหลายแบบ
    # none = เติมสีอย่างเดียว · word = ทั้งคำลอย/ขยาย/เรืองแสงทันทีที่ถึงคำ (ไม่รอร้องจบ) · char = ทีละตัวอักษรตามขอบการเติมสี
    # ปริมาณของแต่ละอย่างเป็นอิสระต่อกัน (lift_px / word_scale / glow_strength — 0 หรือ 1.0 = ไม่ใช้) ใช้ร่วมกันได้
    word_anim: Literal["none", "word", "char"] = "none"   # ค่าเริ่มต้น = เติมสีขอบนุ่มอย่างเดียว ตามคลิป Apple Music
    word_ease: Literal["smooth", "gentle", "spring", "linear"] = "smooth"
    word_anim_ms: int = Field(420, ge=60, le=1200)    # ระยะเวลาเคลื่อนไหวของคำ
    word_scale: float = Field(1.0, ge=1.0, le=1.35)  # ขยายกี่เท่า (1.0 = ไม่ขยาย)
    word_stay: bool = True                            # ค้างสถานะลอย/ขยาย/เรืองแสงไว้จนจบบรรทัด (ปิด = คืนหลัง word_hold_ms)
    glow_strength: float = Field(0.0, ge=0, le=1)     # ความแรงของแสง (0 = ไม่มี) — เรืองเฉพาะส่วนที่เติมสีแล้ว
    glow_color: str = "#FFFFFF"                       # สีของแสงเรืองรอบคำ (รวมคำเน้น)
    word_hold_ms: int = Field(250, ge=0, le=2000)     # ร้องคำนั้นจบแล้วค้างสถานะ "ลอย/เรืองแสง" ต่ออีกกี่ ms ก่อนเริ่มคืน
    word_release_ms: int = Field(700, ge=0, le=3000)  # ใช้เวลาคืนกลับ (ลอยลง/แสงค่อยๆ ลด) กี่ ms
    # คำเน้น (แบบ Apple Music): คำที่ลากเสียงยาว (หรือที่ตัวตรวจจับ/AI ในเฟส 4 ระบุ emphasis) เรืองแสง+ขยายตอนร้อง
    emph_on: bool = True    # คำเน้น (เรืองแสง+ขยาย) ที่ AI เลือก (ผู้ใช้สั่ง 2026-10-21) — ปิดได้ที่ตั้งค่า > แอนิเมชัน
    emph_min_s: float = Field(1.2, ge=0.4, le=4.0)    # คำที่ยาวตั้งแต่กี่วินาทีถือเป็นคำเน้น
    emph_glow: float = Field(0.9, ge=0, le=1)
    emph_scale: float = Field(1.08, ge=1.0, le=1.3)
    group_lines: bool = True                          # บรรทัดที่ร้องต่อเนื่องเป็นท่อนเดียวกัน ค้างความสว่างไว้แล้วจางพร้อมกันเมื่อจบท่อน
    group_gap_s: float = Field(0.6, ge=0.1, le=2.0)   # ช่องว่างสูงสุดระหว่างบรรทัดที่ยังนับเป็นท่อนเดียวกัน (ถ้าดูเป็นประโยคต่อ)
    auto_scroll: bool = True
    scroll_lead_s: float = Field(0.3, ge=0.0, le=1.0)  # เริ่มเลื่อนไปบรรทัดถัดไปก่อนบรรทัดนั้นเริ่มร้องเท่านี้ (ให้เลื่อนถึงกลางจอพอดีตอนเริ่มร้อง ไม่หน่วง) — ใช้เมื่อบรรทัดก่อนหน้าจบแล้ว
    resume_s: float = Field(3.0, ge=1, le=15)       # เลื่อนอ่านเองแล้วกลับไปตามเพลงใน (วินาที)
    click_seek: bool = True                          # คลิกบรรทัดเพื่อกรอ YouTube ไปที่บรรทัดนั้น
    show_source: bool = True                         # แสดงป้ายแหล่งเนื้อเพลง
    translation_size: float = Field(0.55, ge=0.3, le=1.2)
    show_translation: bool = True   # สวิตช์หลัก (แสดงเฉพาะเมื่อมีคำแปลและเป็นภาษาไทย หรือผู้ใช้กดเปิดเอง)
    hover_controls: bool = True     # แถบควบคุมเล็กๆ ตอนเอาเมาส์ชี้ (UX UI ข้อ 8.1)


class FullWindowSettings(_Model):
    """หน้าต่างโหมดเต็ม (แบบ Apple Music): หน้าต่างปกติมีแถบชื่อ ย่อ/ขยาย/ปิดได้ + เต็มจอ (F/F11) · ปกใหญ่ซ้าย เนื้อเพลงใหญ่ขวา
    พื้นหลังไหลลื่นสีจากปก (fluid shader) · แถบควบคุมซ่อนเองเมื่อไม่ขยับเมาส์ตอนเต็มจอ"""

    open: bool = True                                 # เปิดโปรแกรมมาแล้วเห็นโหมดเต็มเป็นหน้าแรก
    start_full: bool = True                           # True = ทุกครั้งที่เปิดโปรแกรมให้เปิดโหมดเต็มก่อน (แม้ครั้งก่อนปิดไว้)
    fullscreen: bool = False
    maximized: bool = True                            # เริ่มแบบขยายเต็มจอ (maximize มีแถบชื่อ/แถบงาน ไม่ใช่ fullscreen) · ย่อกลับแล้วจำขนาดเดิม
    x: int | None = None
    y: int | None = None
    w: int = Field(1180, ge=640, le=7680)
    h: int = Field(740, ge=420, le=4320)
    background: Literal["fluid", "solid"] = "fluid"
    brightness: float = Field(0.85, ge=0.3, le=1.3)   # ความสว่างพื้นหลัง fluid
    font_scale: float = Field(1.0, ge=0.5, le=2.0)    # คูณกับขนาดตัวอักษรอัตโนมัติ (ตามความสูงหน้าต่าง)
    lyrics_visible: bool = True                       # False = ซ่อนเนื้อเพลง ดูแต่ปก (ปกขยายใหญ่กึ่งกลาง) — ปุ่มไอคอนเนื้อเพลง
    align: Literal["left", "center"] = "left"         # การจัดวางเนื้อเพลง (Apple Music = ชิดซ้าย)
    cover_scale: float = Field(1.0, ge=0.6, le=1.3)   # ขนาดปกเทียบกับค่าอัตโนมัติ
    show_volume: bool = True                          # แถบวอลลุ่มใต้ปุ่มควบคุม
    show_translation: bool = True
    inactive_opacity: float = Field(0.45, ge=0, le=1)  # ความสว่างของบรรทัดที่ไม่ได้ร้อง (0 = มองไม่เห็นเลย) · 0.45 × คำที่ยังไม่ร้อง 40% ≈ 18% ตรงกับที่วัดจากคลิป Apple Music
    blur: float = Field(0.7, ge=0, le=1)              # เบลอบรรทัดที่ไม่ได้ร้อง ยิ่งไกลยิ่งเบลอ (แบบ Apple Music: บรรทัดที่ 3 ขึ้นไปเบลอเต็มที่)
    falloff: float = Field(0.01, ge=0, le=0.3)        # จางเพิ่มต่อบรรทัดที่ไกลจากบรรทัดที่ร้อง (Apple Music: บรรทัดไกลๆ สว่างเท่ากัน ~17%)
    # สีเนื้อเพลงของโหมดเต็ม (แยกจากหน้าต่างลอย — สี ov_* ใช้กับหน้าต่างลอยเท่านั้น)
    text_color: str = "#FFFFFF"       # บรรทัด/คำที่ร้องแล้ว
    accent_color: str = "#FFFFFF"     # ไฮไลต์แบบเรืองแสง/ทีละคำ
    inactive_color: str = "#FFFFFF"   # บรรทัดที่ไม่ได้ร้อง (ความจางตั้งแยก)
    secondary_color: str = "#FFFFFF"  # คำแปล
    edge_blur: float = Field(0.8, ge=0, le=1)         # เบลอเพิ่มที่ขอบบน/ล่าง (ใช้คู่กับ edge_fade)
    edge_fade: float = Field(0.14, ge=0, le=0.4)     # เนื้อเพลงเบลอ/จางหายก่อนถึงขอบบน-ล่าง (สัดส่วนความสูง) แบบ Apple Music
    idle_hide: bool = True                            # ซ่อนปุ่มบน/ป้ายแหล่งเนื้อเพลงเมื่อไม่ขยับเมาส์ (ทั้งหน้าต่างปกติและเต็มจอ)
    idle_hide_s: float = Field(3.0, ge=1, le=60)      # ไม่ขยับเมาส์กี่วินาทีแล้วซ่อน (เต็มจอซ่อนเมาส์ด้วย)


class HotkeySettings(_Model):
    """คีย์ลัดทั้งระบบ (ใช้ได้แม้ไม่ได้โฟกัสโปรแกรม) รูปแบบ "Ctrl+Alt+L" — ว่าง = ปิด"""

    show_hide: str = "Ctrl+Alt+L"
    click_through: str = "Ctrl+Alt+K"
    lock: str = "Ctrl+Alt+O"
    full_toggle: str = "Ctrl+Alt+F"  # เปิด/ปิดหน้าต่างโหมดเต็ม
    translation: str = "Ctrl+Alt+T"
    font_up: str = "Ctrl+Alt+Up"
    font_down: str = "Ctrl+Alt+Down"
    offset_later: str = "Ctrl+Alt+Right"    # เนื้อเพลงช้าลง 0.1 วิ
    offset_earlier: str = "Ctrl+Alt+Left"   # เนื้อเพลงเร็วขึ้น 0.1 วิ
    offset_reset: str = "Ctrl+Alt+0"


class LyricsSourceSettings(_Model):
    # ชื่อ plugin -> เปิด/ปิด (plugin ที่ไม่มีในนี้ใช้ค่า enabled_by_default ของมันเอง)
    enabled: dict[str, bool] = {}
    allow_ai_transcribe: bool = True
    # เปิด/ปิดแหล่งเนื้อเพลงทีละแหล่ง (หน้าตั้งค่า > แหล่งเนื้อเพลง) · ปิดทั้งหมด = ไม่ค้นเว็บ ใช้ AI ถอดเสียงอย่างเดียว
    src_lrclib: bool = True
    src_lyrics_ovh: bool = True
    src_netease: bool = True
    src_qqmusic: bool = True
    src_youtube_subs: bool = True
    audio_pick: bool = True                             # ให้ AI ฟังเสียงเทียบเนื้อเพลงหลายฉบับ แล้วเลือกฉบับที่เข้ากับเสียงที่สุด
    split_long_lines: bool = True                       # ตัดบรรทัดเนื้อเพลงที่ยาวเกินเป็นบรรทัดสั้น (ที่วรรคตอน/คำเชื่อม) แบบ Apple Music
    max_line_width: int = Field(46, ge=20, le=120)      # ความกว้างสูงสุดของบรรทัด (ตัวอักษรกว้าง CJK นับ 2)


class PlaybackSettings(_Model):
    # False = แอปแสดงเนื้อเพลงอย่างเดียว ไม่เล่นเสียง ไม่เปิดอุปกรณ์เสียง (ผู้ใช้สั่ง 2026-10-20: เล่นใน YouTube เท่านั้น)
    # True = โค้ดโหมดแอปเดิม (เล่นเสียงเอง/คิว) ซึ่งเก็บไว้เผื่อเฟส 5-7 — ปิดอยู่ทั้งใน UI และส่วนขยาย
    app_audio: bool = False
    preload_at_percent: int = Field(50, ge=5, le=95)
    first_chunk_s: float = Field(25.0, ge=10, le=60)
    cache_max_gb: float = Field(10.0, ge=0.5, le=500)
    output_device: str | None = None  # None = อุปกรณ์เริ่มต้นของ Windows
    buffer_ms: int = Field(30, ge=5, le=200)
    loudness_normalize: bool = True
    target_lufs: float = Field(-14.0, ge=-30, le=-5)
    video_enabled: bool = False


class AutomixSettings(_Model):
    mode: Literal["off", "crossfade", "smart"] = "smart"
    boldness: Literal["careful", "balanced", "dj"] = "balanced"
    length: Literal["auto"] | float = "auto"  # หรือ 2-16 วิ
    allowed_styles: list[str] = [
        "beatmatch_blend", "bass_swap", "filter_sweep", "echo_out",
        "short_crossfade", "long_crossfade", "clean_cut",
    ]
    max_tempo_change_pct: float = Field(6.0, ge=0, le=12)
    show_indicator: bool = True
    show_mood: bool = True
    rating_popup: Literal["off", "always", "uncertain_only"] = "always"
    rating_popup_seconds: float = Field(7.0, ge=2, le=30)
    transition_style: str = "morph"
    short_transition_style: str = "blur_through"
    transition_easing: Literal["spring", "ease", "linear"] = "spring"
    transition_strength: float = Field(1.0, ge=0, le=2)


class AiSettings(_Model):
    """AI ฟังเสียงเบื้องหลัง (เฟส 4) — ค่าละเอียดของโมเดลอยู่ใน models.yaml"""

    enabled: bool = True     # ให้ AI ฟังเสียงจริงเพื่อจัดเวลาเนื้อเพลง (ปิด = ใช้เวลาจากแหล่ง/ประมาณล้วน ไม่ใช้ GPU)
    translate: bool = True   # แปลเนื้อเพลงที่ไม่ใช่ภาษาไทยเป็นไทยด้วย AI


class StartupSettings(_Model):
    launch_with_windows: bool = False
    minimize_to_tray: bool = True
    close_to_tray: bool = False  # กดปิดหน้าต่างหลัก/ตั้งค่า = ซ่อนลง tray (False = ปิดโปรแกรมจริง — ผู้ใช้คาดหวังแบบนี้ 2026-10-20)
    language: Literal["th", "en"] = "th"
    open_browser: Literal["youtube", "youtube_music", "none"] = "youtube"
    extension_sends_current_video: bool = True


class Settings(_Model):
    version: int = 5
    lyrics_look: LyricsLook = LyricsLook()
    background: BackgroundSettings = BackgroundSettings()
    desktop_lyrics: DesktopLyricsSettings = DesktopLyricsSettings()
    overlay: OverlaySettings = OverlaySettings()
    fullwindow: FullWindowSettings = FullWindowSettings()
    hotkeys: HotkeySettings = HotkeySettings()
    ai: AiSettings = AiSettings()
    lyrics_sources: LyricsSourceSettings = LyricsSourceSettings()
    playback: PlaybackSettings = PlaybackSettings()
    automix: AutomixSettings = AutomixSettings()
    startup: StartupSettings = StartupSettings()
    theme: str = "minimal"
    power_saving: Literal["auto", "on", "off"] = "auto"


# ---------------------------------------------------------------------------
# models.yaml
# ---------------------------------------------------------------------------
class DemucsCfg(_Model):
    enabled: bool = True
    model: str = "htdemucs"
    fp16: bool = True
    segment_s: float = 7.0
    shifts: int = 0
    overlap: float = 0.25


class AlignCfg(_Model):
    enabled: bool = True
    fp16: bool = True
    batch_lines: int = 16
    min_confidence: float = 0.45  # ต่ำกว่านี้ใช้เวลาแบบประมาณแทน (ข้อ 5.1 ขั้น 8)
    global_align: bool = False   # จัดเวลาทั้งเพลงด้วย CTC เทียบกับผล Whisper (ทดลอง ปิดไว้: ยังไม่เพิ่มบรรทัดที่จับคู่ได้)
    global_min_confidence: float = 0.5
    global_switch_gain: float = 0.15


class WhisperCfg(_Model):
    enabled: bool = True
    model: str = "large-v3-turbo"
    compute_type: str = "float16"
    fallback_compute_type: str = "int8_float16"
    keep_loaded: bool = True  # True = ค้างใน VRAM (เร็ว) · False = โหลดเฉพาะตอนใช้แล้ว unload (ประหยัด VRAM)
    beam_size: int = 5


class BeatsCfg(_Model):
    prefer: Literal["allin1", "beat_this"] = "beat_this"
    beat_this_checkpoint: str = "final0"
    min_confidence_for_beatmatch: float = 0.6


class ProgressiveCfg(_Model):
    chunk_s: float = 20.0
    overlap_s: float = 2.5
    lead_s: float = 30.0  # ต้องนำหน้าตัวเล่นอย่างน้อยเท่านี้
    analysis_deadline_before_mix_s: float = 30.0


class TranslateCfg(_Model):
    enabled: bool = True
    model: str = "JustFrederik/nllb-200-distilled-1.3B-ct2-int8"
    target_lang: str = "tha_Thai"
    beam_size: int = 4
    keep_loaded: bool = False


class EmphasisCfg(_Model):
    """เลือกคำเน้นด้วยโมเดลภาษาในเครื่อง (ผู้ใช้สั่ง 2026-10-21) — โหลดครั้งแรก ~4 GB ไป <model_dir>/llm/<local_name>"""

    enabled: bool = True
    model: str = "jncraton/Qwen3-4B-Instruct-2507-ct2-int8"
    local_name: str = "qwen3-4b-instruct-2507-ct2-int8"
    delay_s: float = 45.0     # รอหลังเปิดเพลงก่อนเริ่ม (กันขวางการจัดเวลาเมื่อข้ามเพลงรัว) และรองานจัดเวลาที่ค้างให้เสร็จก่อน


class AnalysisCfg(_Model):
    """การวิเคราะห์เสียงเบื้องหลังเพื่อจัดเวลาเนื้อเพลง (แอปไม่เล่นเสียงเอง — โหลดเสียงมาวิเคราะห์อย่างเดียว)"""

    enabled: bool = True
    max_song_s: float = 900.0   # ยาวกว่านี้ไม่ใช่เพลง (พอดแคสต์/ไลฟ์) ข้าม
    sample_rate: int = 44100    # ความถี่ที่ถอดรหัสให้ Demucs (Whisper/MMS ลดเป็น 16k เอง)
    window_s: float = 30.0      # ขนาดช่วงที่ประมวลผลทีละครั้ง (ทยอยส่งผลทีละช่วง)
    context_s: float = 3.0      # ซ้อนหัวท้ายแต่ละช่วงให้ Demucs/Whisper เห็นบริบท
    min_coverage: float = 0.25  # จับคู่เนื้อเพลงกับเสียงได้น้อยกว่านี้ = เนื้อเพลงอาจเป็นคนละเวอร์ชัน
    heard_extras: bool = True        # เก็บสิ่งที่ AI ได้ยินแต่ไม่มีในเนื้อเพลงเว็บ (คอรัส/ad-lib) เป็นแถวเสียงประสานตัวเล็ก
    ctc_first: bool = True           # จัดเวลาด้วย CTC ทั้งเพลงก่อน (เร็ว+แม่น) ไม่ผ่านการตรวจ = Whisper + MMS รายบรรทัด
    batched_whisper: bool = True     # ถอดเสียงทั้งเพลงครั้งเดียวแบบ batch (เร็วกว่า ~4 เท่า) · false = ทีละช่วงพร้อมส่งผลทยอย
    detect_singers: bool = True      # นับนักร้องจากลายเสียง: ≥2 คน = คนรองชิดขวา (ECAPA ~84 MB)
    detect_backing: bool = True      # AI ตรวจบรรทัดเสียงประสาน/คอรัส (เบา/สะท้อนบรรทัดข้างเคียง) แสดงเป็นแถวเล็ก
    prefer_heard: bool = False       # ยึดเนื้อเพลงเว็บเป็นหลัก แล้วให้ AI จัดเวลา (ผู้ใช้สั่ง 2026-10-20) · True = แสดงตามเสียงที่ AI ได้ยินแทน
    reconstruct_below: float = 0.5   # จับคู่ตามลำดับได้น้อยกว่านี้ ลองสร้างบรรทัดตามลำดับที่ร้องจริง (รีมิกซ์/โครงสร้างต่าง)
    reconstruct_gain: float = 0.08   # ใช้ผลที่สร้างตามเสียงจริงเมื่อจับคู่ข้อความได้มากกว่าแบบเรียงลำดับอย่างน้อยเท่านี้
    transcript_version: int = 2  # เปลี่ยนเมื่อวิธีแยกเสียง/ถอดเสียงเปลี่ยน -> ต้องฟังเสียงใหม่ (ไม่เกี่ยวกับ algo_version)
    algo_version: int = 5       # เปลี่ยนเมื่อวิธีจัดเวลาเปลี่ยน -> ผลที่เก็บไว้เก่าหมดอายุ


class ModelsConfig(_Model):
    version: int = 1
    preload: bool = True  # โหลด Demucs/Whisper ค้างใน VRAM ตอนเปิดโปรแกรม (ไม่บล็อก UI) · VRAM ว่าง < 3.5 GB ข้าม
    site_dir: str = ""    # โฟลเดอร์ site-packages ของ AI (torch ฯลฯ) ที่ worker ต่อเข้า sys.path · ว่าง = <โปรเจกต์>/ai_runtime/site ถ้ามี ไม่งั้นใช้ของ .venv หลัก
    model_dir: str = ""   # ที่เก็บน้ำหนักโมเดล (HF_HOME/TORCH_HOME) · ว่าง = <โปรเจกต์>/ai_runtime/models ถ้ามี · path สัมพัทธ์อิงโฟลเดอร์โปรเจกต์
    device: Literal["auto", "cuda", "cpu"] = "auto"
    vram_budget_mb: int = 6500
    vram_reserve_mb: int = 1200  # เหลือไว้ให้ UI/shader/วิดีโอ
    cudnn_benchmark: bool = False  # ปิด: ความยาวอินพุตไม่คงที่ (alignment ทีละบรรทัด) benchmark ซ้ำทุกครั้งช้ามาก
    empty_cache_after_track: bool = True
    worker_priority: Literal["below_normal", "idle", "normal"] = "below_normal"
    watchdog_timeout_s: float = 20.0
    demucs: DemucsCfg = DemucsCfg()
    align: AlignCfg = AlignCfg()
    whisper: WhisperCfg = WhisperCfg()
    beats: BeatsCfg = BeatsCfg()
    progressive: ProgressiveCfg = ProgressiveCfg()
    translate: TranslateCfg = TranslateCfg()
    emphasis: EmphasisCfg = EmphasisCfg()
    analysis: AnalysisCfg = AnalysisCfg()

    @model_validator(mode="before")
    @classmethod
    def _resolve_ai_dirs(cls, data: Any) -> Any:
        """หาโฟลเดอร์ AI: ค่าที่ตั้ง (สัมพัทธ์ = อิงโปรเจกต์) หรือค่าเริ่มต้น <โปรเจกต์>/ai_runtime
        ทำไมไม่ใช้ %LOCALAPPDATA%: เซสชันที่ผมติดตั้งรันในแพ็กเกจ MSIX ของ Claude ซึ่ง "เสมือน" AppData — ไฟล์ที่เขียนที่นั่นแอปปกติมองไม่เห็น"""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        runtime = PROJECT_ROOT / "ai_runtime"
        for key, sub in (("site_dir", "site"), ("model_dir", "models")):
            val = data.get(key) or ""
            if val:
                path = Path(str(val))
                data[key] = str(path if path.is_absolute() else PROJECT_ROOT / path)
            elif (runtime / sub).is_dir():
                data[key] = str(runtime / sub)
        return data


# ---------------------------------------------------------------------------
# automix_rules.yaml — เก็บเป็น dict ที่ตรวจเฉพาะส่วนสำคัญ (planner อ่านค่าโดยตรง)
# ---------------------------------------------------------------------------
class AutomixRules(_Model):
    model_config = ConfigDict(extra="allow")
    version: int = 1
    iron_rules: dict[str, Any]
    compatibility: dict[str, Any]
    thresholds: dict[str, Any]
    styles: dict[str, Any]
    learning: dict[str, Any]


M = TypeVar("M", bound=BaseModel)


# ---------------------------------------------------------------------------
# การโหลด
# ---------------------------------------------------------------------------
def read_raw(path: Path) -> dict[str, Any]:
    """อ่านไฟล์ YAML/JSON เป็น dict (ไฟล์ว่าง = {})"""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: ระดับบนสุดต้องเป็น mapping")
    return data


def migrate_raw(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """แปลงข้อมูลจากเวอร์ชันเก่าเป็นเวอร์ชันปัจจุบัน"""
    target = CURRENT_VERSIONS[name]
    v = int(data.get("version", 1))
    if v > target:
        raise ConfigError(f"{name} เวอร์ชัน {v} ใหม่กว่าโปรแกรม ({target})")
    while v < target:
        step = MIGRATORS[name].get(v)
        if step is None:
            raise ConfigError(f"ไม่มีตัวแปลง {name} จาก v{v}")
        data = step(copy.deepcopy(data))
        v += 1
        data["version"] = v
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """รวม override ทับ base แบบลึก (list ถูกแทนทั้งก้อน)"""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_raw(paths: AppPaths, name: str) -> tuple[dict[str, Any], list[str]]:
    """ค่าเริ่มต้นรวมกับของผู้ใช้ คืน (ข้อมูล, คำเตือน) — ไม่โยน error ถ้าไฟล์ผู้ใช้พัง"""
    warnings: list[str] = []
    default_path = paths.default_config_dir / name
    data = migrate_raw(name, read_raw(default_path)) if default_path.exists() else {}
    user_path = paths.settings_file if name == "settings.yaml" else paths.user_config_dir / name
    if user_path.exists():
        try:
            data = deep_merge(data, migrate_raw(name, read_raw(user_path)))
        except Exception as e:  # ไฟล์ผู้ใช้พัง -> ใช้ค่าเริ่มต้น
            warnings.append(f"{user_path.name} ใช้ไม่ได้ ({e}) — ใช้ค่าเริ่มต้นแทน")
    data["version"] = CURRENT_VERSIONS[name]
    return data, warnings


def load_model(paths: AppPaths, name: str, model: type[M]) -> tuple[M, list[str]]:
    """โหลดและตรวจด้วย pydantic ถ้ารวมแล้วไม่ผ่าน ลองค่าเริ่มต้นล้วน"""
    data, warnings = load_raw(paths, name)
    try:
        return model.model_validate(data), warnings
    except Exception as e:
        warnings.append(f"{name} ผิดรูปแบบ ({e}) — ใช้ค่าเริ่มต้น")
        default_path = paths.default_config_dir / name
        base = migrate_raw(name, read_raw(default_path)) if default_path.exists() else {}
        return model.model_validate(base), warnings


def save_settings(paths: AppPaths, settings: Settings) -> None:
    """บันทึกการตั้งค่าของผู้ใช้แบบ atomic (เขียนไฟล์ชั่วคราวแล้ว rename)"""
    paths.settings_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.settings_file.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(settings.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(paths.settings_file)
