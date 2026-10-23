"""SettingsStore — ตัวกลางระหว่างหน้าตั้งค่า (QML) กับโมเดล Settings (pydantic) โดยไม่ผูกกับ Qt

QML อ่าน/เขียนค่าแบบแบน (flat) ผ่าน QQmlPropertyMap ด้วยคีย์ "<กลุ่ม>_<ชื่อฟิลด์>":
  ov_*   OverlaySettings (หน้าต่างลอย)      look_* LyricsLook (ฟอนต์/ขนาด/เอฟเฟกต์ไฮไลต์ตัวหลัก)
  hk_*   HotkeySettings (คีย์ลัด)            st_*   StartupSettings (เริ่มพร้อม Windows/tray ฯลฯ)
  ai_*   AiSettings (AI ฟังเสียง/แปลไทย)
set() ตรวจค่าด้วย pydantic (ค่าผิด = ValueError ผู้เรียกคืนค่าเดิมให้ UI) และคืน "ค่าที่เปลี่ยนตามมา"
เช่น เลือกธีม -> สี/ความโปร่งใสเปลี่ยนตาม · แก้สีเอง -> ธีมกลายเป็น custom
เก็บลงไฟล์ผ่าน on_change (ผู้เรียกทำ debounce) — โมดูลนี้ห้าม import PySide6
"""

from __future__ import annotations

import typing
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.ui import anim_presets, themes

GROUPS: dict[str, str] = {"ov": "overlay", "fw": "fullwindow", "look": "lyrics_look", "hk": "hotkeys", "st": "startup", "ai": "ai",
                          "ls": "lyrics_sources"}
# คีย์ที่ไม่ควรให้ธีมเปลี่ยนเป็น custom เมื่อถูกเขียน (ตำแหน่ง/สถานะหน้าต่าง ฯลฯ ไม่ใช่เรื่องหน้าตา)
_NON_APPEARANCE = {"blur_behind", "anim_preset", "mode", "visible", "start_position", "monitor", "window_opacity", "weight_boost", "always_on_top", "locked", "click_through", "remember_position", "x", "y",
                   "w_minimal", "h_minimal", "w_focus", "h_focus", "w_full", "h_full", "theme", "show_translation",
                   "auto_scroll", "hover_controls", "reduced_motion", "visible_lines", "animation",
                   "animation_intensity", "highlight", "translation_size"}


def split_key(key: str) -> tuple[str, str]:
    prefix, _, name = key.partition("_")
    if prefix not in GROUPS or not name:
        raise KeyError(key)
    return prefix, name


def _accepts(annotation: Any, typ: type) -> bool:
    """annotation (รวม Optional/Union) รับชนิด typ ไหม"""
    if annotation is typ:
        return True
    return any(_accepts(a, typ) for a in typing.get_args(annotation) if a is not Ellipsis)


def coerce(model: BaseModel, name: str, value: Any) -> Any:
    """แปลงค่าที่มาจาก QML (QML ส่งตัวเลขเป็น float เสมอ) ให้ตรงชนิดของฟิลด์"""
    ann = type(model).model_fields[name].annotation
    if isinstance(value, float) and _accepts(ann, int) and not _accepts(ann, float):
        value = int(round(value))
    if value == "" and _accepts(ann, type(None)):
        return None
    return value


_MIRROR_TO_FULL = {"ov_text_color": "text_color", "ov_accent_color": "accent_color", "ov_inactive_color": "inactive_color",
                   "ov_secondary_color": "secondary_color"}


class SettingsStore:
    """เก็บ Settings ที่กำลังใช้งาน + ให้อ่าน/เขียนแบบแบน"""

    def __init__(self, settings: Settings, on_change: Callable[[], None] | None = None) -> None:
        self.settings = settings
        self.on_change = on_change or (lambda: None)
        self._defaults = Settings()

    # ---------- อ่าน ----------
    def _model(self, prefix: str) -> BaseModel:
        return getattr(self.settings, GROUPS[prefix])

    def flat(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for prefix in GROUPS:
            for name, value in self._model(prefix).model_dump().items():
                if isinstance(value, dict):      # (เช่น ls_enabled) QML ไม่ได้ใช้ · แผนที่ซ้อนทำให้ค่าเปรียบเทียบยุ่ง
                    continue
                out[f"{prefix}_{name}"] = "" if value is None else value
        return out

    def get(self, key: str) -> Any:
        prefix, name = split_key(key)
        return getattr(self._model(prefix), name)

    # ---------- เขียน ----------
    def set(self, key: str, value: Any) -> dict[str, Any]:
        """ตั้งค่า คืน {คีย์: ค่าใหม่} ของทุกคีย์ที่เปลี่ยน (รวมที่เปลี่ยนตามมา) · ค่าผิด/ไม่รู้จัก = ValueError"""
        try:
            prefix, name = split_key(key)
            model = self._model(prefix)
            if name not in type(model).model_fields:
                raise KeyError(key)
        except KeyError:
            raise ValueError(f"ไม่รู้จักการตั้งค่า {key!r}") from None
        before = self.flat()
        try:
            setattr(model, name, coerce(model, name, value))
        except ValidationError as e:
            raise ValueError(f"ค่าของ {key} ไม่ถูกต้อง: {e.errors()[0]['msg']}") from None
        if prefix == "ov":
            if name == "theme":
                self._apply_theme(model.theme)
            elif name == "anim_preset":
                self._apply_anim_preset(model.anim_preset)
            elif name in themes.THEME_OWNED_KEYS and name not in _NON_APPEARANCE and model.theme != "custom":
                model.theme = "custom"  # ผู้ใช้ปรับเอง = กลายเป็นธีมกำหนดเอง
        if key in _MIRROR_TO_FULL:  # สีเนื้อเพลงที่ตั้งในหมวดตัวอักษร ใช้กับโหมดเต็มด้วย (ตั้งที่เดียว) · โหมดเต็มตั้งแยกได้ในโหมดละเอียด
            setattr(self.settings.fullwindow, _MIRROR_TO_FULL[key], getattr(model, name))
        if key in anim_presets.OWNED_KEYS and key != "ov_anim_preset" and self.settings.overlay.anim_preset != "custom":
            self.settings.overlay.anim_preset = "custom"  # แก้ค่าแอนิเมชันเอง = ชุดกลายเป็นกำหนดเอง
        after = self.flat()
        changed = {k: v for k, v in after.items() if before.get(k) != v}
        if changed:
            self.on_change()
        return changed

    def _apply_anim_preset(self, name: str) -> None:
        vals = anim_presets.preset_values(name)
        for field, value in vals["ov"].items():
            setattr(self.settings.overlay, field, value)
        for field, value in vals["look"].items():
            setattr(self.settings.lyrics_look, field, value)

    def _apply_theme(self, name: str) -> None:
        for field, value in themes.preset_values(name).items():
            setattr(self.settings.overlay, field, value)

    def reset_group(self, prefix: str) -> dict[str, Any]:
        """คืนค่าเริ่มต้นของทั้งกลุ่ม คืนคีย์ที่เปลี่ยน"""
        before = self.flat()
        setattr(self.settings, GROUPS[prefix], type(self._model(prefix))())
        after = self.flat()
        changed = {k: v for k, v in after.items() if before.get(k) != v}
        if changed:
            self.on_change()
        return changed

    def reset_keys(self, keys: list[str]) -> dict[str, Any]:
        """คืนค่าเริ่มต้นเฉพาะคีย์ที่ระบุ (ตั้งตรงๆ ไม่ผ่านผลข้างเคียงของธีม/ชุดแอนิเมชัน เพราะค่าเริ่มต้นสอดคล้องกันอยู่แล้ว)"""
        before = self.flat()
        for key in keys:
            try:
                prefix, name = split_key(key)
                setattr(self._model(prefix), name, getattr(getattr(self._defaults, GROUPS[prefix]), name))
            except (KeyError, AttributeError):
                continue
        after = self.flat()
        changed = {k: v for k, v in after.items() if before.get(k) != v}
        if changed:
            self.on_change()
        return changed

    def page_keys(self, page: str) -> list[str]:
        """คีย์ของแต่ละหมวดในหน้าตั้งค่า (ปุ่ม "คืนค่าหมวดนี้") — ไม่รวมตำแหน่ง/สถานะเปิดปิดหน้าต่าง"""
        flat = self.flat()
        ov = lambda *names: [f"ov_{n}" for n in names]
        if page == "general":
            return [k for k in flat if k.startswith("st_")] + ["fw_start_full"]
        if page == "full":
            skip = {"fw_x", "fw_y", "fw_w", "fw_h", "fw_open", "fw_fullscreen", "fw_start_full"}
            return [k for k in flat if k.startswith("fw_") and k not in skip]
        if page == "float":
            return ov("mode", "visible", "always_on_top", "locked", "click_through", "remember_position", "visible_lines",
                      "align", "hover_controls", "start_position", "monitor") + [k for k in flat if k.startswith(("ov_w_", "ov_h_"))]
        if page == "font":
            return ov("font_size", "text_width", "font_weight", "weight_boost", "line_spacing", "letter_spacing", "text_shadow",
                      "text_color", "accent_color", "inactive_color", "secondary_color", "text_opacity", "inactive_opacity") + ["look_font_family"]
        if page == "theme":
            names = {f"ov_{n}" for n in themes.THEME_OWNED_KEYS} | set(ov("theme", "bg_style", "blur_behind", "bg_color", "bg_color2", "bg_opacity",
                                                          "window_opacity", "border_opacity", "shadow", "corner_radius"))
            return sorted(k for k in names if k in flat and k not in set(ov("text_color", "accent_color", "inactive_color", "secondary_color", "text_opacity", "inactive_opacity", "text_shadow", "font_size", "font_weight")))
        if page == "lyrics":
            return ov("highlight", "auto_scroll", "resume_s", "click_seek", "show_source", "show_translation", "translation_size") + ["look_show_romanization"]
        if page == "anim":
            return sorted(set(anim_presets.OWNED_KEYS) | set(ov("anim_preset", "animation", "animation_intensity", "reduced_motion", "word_anim", "word_ease",
                          "word_anim_ms", "word_scale", "word_stay", "glow_strength", "glow_color", "word_hold_ms", "word_release_ms", "lift_px", "emph_on", "emph_min_s", "emph_glow", "emph_scale")))
        if page == "sync":
            return ov("latency_ms", "scroll_lead_s")
        if page == "hotkeys":
            return [k for k in flat if k.startswith("hk_")]
        if page == "sources":
            return [k for k in flat if k.startswith("ls_")]
        if page == "ai":
            return [k for k in flat if k.startswith("ai_")]
        return []

    def reset_page(self, page: str) -> dict[str, Any]:
        return self.reset_keys(self.page_keys(page))

    # ---------- ค่าเริ่มต้นรายตัว (ปุ่ม ↺ ข้างแต่ละตัวเลือก) ----------
    def default_of(self, key: str) -> Any:
        prefix, name = split_key(key)
        value = getattr(getattr(self._defaults, GROUPS[prefix]), name)  # ไม่มีฟิลด์ = AttributeError
        return "" if value is None else value

    def is_default(self, key: str, value: Any) -> bool:
        """value (ค่าที่ UI เห็นอยู่) เท่าค่าเริ่มต้นไหม — สีไม่สนตัวพิมพ์ ตัวเลขเผื่อทศนิยมคลาด · คีย์ไม่รู้จัก = ถือว่าเป็นค่าเริ่มต้น (ไม่แสดงปุ่ม)"""
        try:
            default = self.default_of(key)
        except (KeyError, AttributeError):
            return True
        if isinstance(default, bool) or isinstance(value, bool):
            return default is value
        if isinstance(default, str) and isinstance(value, str):
            return default.lower() == value.lower()
        if isinstance(default, (int, float)) and isinstance(value, (int, float)):
            return abs(default - value) < 1e-6
        return default == value

    def reset_key(self, key: str) -> dict[str, Any]:
        """คืนค่าเริ่มต้นของตัวเลือกเดียว ผ่าน set() เพื่อให้ผลข้างเคียงทำงานเหมือนผู้ใช้ปรับเอง (ชุดแอนิเมชัน/ธีมกลายเป็น custom ตามจริง)"""
        try:
            default = self.default_of(key)
        except (KeyError, AttributeError):
            raise ValueError(f"ไม่รู้จักการตั้งค่า {key!r}") from None
        return self.set(key, default)

    # ---------- ชุดการตั้งค่าที่ตั้งชื่อไว้ ----------
    # หมวดที่เข้าชุด = หน้าตา/พฤติกรรมของเนื้อเพลง · ไม่รวมการเริ่มต้นระบบ (เปิดพร้อม Windows ฯลฯ) คีย์ลัด และสถานะหน้าต่าง (ตำแหน่ง/เปิด/จอ)
    PRESET_PAGES = ("full", "float", "font", "theme", "lyrics", "anim", "sync")
    PRESET_EXCLUDE = frozenset({"ov_visible", "ov_monitor", "fw_maximized", "ov_latency_ms"})   # ความหน่วงเสียงเป็นค่าของลำโพง/บลูทูธ ไม่ใช่หน้าตา

    def preset_keys(self) -> list[str]:
        flat = self.flat()
        keys: set[str] = set()
        for page in self.PRESET_PAGES:
            keys.update(self.page_keys(page))
        return sorted(k for k in keys if k in flat and k not in self.PRESET_EXCLUDE)

    def snapshot(self) -> dict[str, Any]:
        """ค่าปัจจุบันของทุกคีย์ที่เข้าชุด (ใช้บันทึกเป็นชุด)"""
        flat = self.flat()
        return {k: flat[k] for k in self.preset_keys()}

    def apply_snapshot(self, values: dict[str, Any]) -> dict[str, Any]:
        """ใช้ชุดที่บันทึกไว้: ตั้งตรงๆ ไม่ผ่านผลข้างเคียงของธีม/ชุดแอนิเมชัน (ภาพนิ่งนั้นสอดคล้องกันในตัวเองอยู่แล้ว)
        คีย์ที่หายไป/ไม่รู้จัก/ค่าผิด (ชุดเก่าจากรุ่นก่อน) ถูกข้ามเงียบๆ · คืนคีย์ที่เปลี่ยน"""
        allowed = set(self.preset_keys())
        before = self.flat()
        for key, value in values.items():
            if key not in allowed:
                continue
            prefix, name = split_key(key)
            model = self._model(prefix)
            try:
                setattr(model, name, coerce(model, name, value))
            except ValidationError:
                continue
        after = self.flat()
        changed = {k: v for k, v in after.items() if before.get(k) != v}
        if changed:
            self.on_change()
        return changed

    def reset_all(self) -> dict[str, Any]:
        changed: dict[str, Any] = {}
        for prefix in GROUPS:
            changed.update(self.reset_group(prefix))
        return changed
