"""SettingsBridge — เชื่อม SettingsStore กับ QML ผ่าน QQmlPropertyMap ชื่อ `cfg`

QML อ่าน/เขียน cfg.ov_mode = "full" ได้ตรงๆ (ทุกส่วนที่ผูกค่าไว้อัปเดตทันที) ส่วนนี้:
  - ตรวจค่าที่ QML เขียนผ่าน SettingsStore ผิด = คืนค่าเดิมให้ QML + log
  - ค่าที่เปลี่ยนตามมา (เช่นเลือกธีม) ใส่กลับเข้า cfg
  - บันทึกลงไฟล์แบบ debounce 0.5 วิ (ไม่เซฟทุกครั้งที่ลาก slider)
  - ผลข้างเคียง: เปิดพร้อม Windows, คีย์ลัด
กฎ: import PySide6 ในฟังก์ชันเท่านั้น (test_smoke_imports)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.log import get_logger
from app.ui.settings_presets import PresetStore
from app.ui.settings_store import SettingsStore

_log = get_logger("ui")
_CLASS: type | None = None

# การกระทำของคีย์ลัด -> ชื่อใน HotkeySettings (ลำดับ = ลำดับลงทะเบียน)
HOTKEY_NAMES = ("show_hide", "click_through", "lock", "full_toggle", "translation", "font_up", "font_down",
                "offset_later", "offset_earlier", "offset_reset")


def make_settings_bridge_class() -> type:
    global _CLASS
    if _CLASS is not None:
        return _CLASS

    from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
    from PySide6.QtQml import QQmlPropertyMap

    class SettingsBridge(QObject):
        quittingChanged = Signal()
        presetsChanged = Signal()

        def __init__(self, store: SettingsStore, save: Callable[[], None] | None = None, data_dir: str = "",
                     on_quit: Callable[[], None] | None = None, parent: Any = None) -> None:
            super().__init__(parent)
            self.store = store
            self._presets = PresetStore(Path(data_dir) / "settings_presets.json" if data_dir else None)
            self._save = save
            self._data_dir = data_dir
            self._on_quit = on_quit
            self._side_effects: list[Callable[[str, Any], None]] = []
            self._pushing = False
            self._quitting = False
            self.cfg = QQmlPropertyMap(self)
            for k, v in store.flat().items():
                self.cfg.insert(k, v)
            self.cfg.insert("hk_status", "")  # ข้อความผิดพลาดของคีย์ลัด (ไม่ใช่ค่าตั้ง — Python เขียน QML อ่าน)
            self.cfg.valueChanged.connect(self._on_qml_changed)
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(500)
            self._timer.timeout.connect(self.flush)
            store.on_change = self._schedule_save

        # ---------- เชื่อมกับส่วนอื่น ----------
        def add_side_effect(self, fn: Callable[[str, Any], None]) -> None:
            """fn(key, value) ถูกเรียกหลังค่าเปลี่ยนและตรวจผ่านแล้ว (ทั้งจาก QML และ set_from_python)"""
            self._side_effects.append(fn)

        def set_status(self, key: str, text: str) -> None:
            self.cfg.insert(key, text)

        def set_from_python(self, key: str, value: Any) -> None:
            """ตั้งค่าจากฝั่ง Python (คีย์ลัด/tray) — ผ่านการตรวจเหมือนค่าจาก QML"""
            self._apply(key, value)

        def get(self, key: str) -> Any:
            return self.store.get(key)

        # ---------- ภายใน ----------
        def _on_qml_changed(self, key: str, value: Any) -> None:
            if self._pushing or key == "hk_status":
                return
            self._apply(key, value)

        def _apply(self, key: str, value: Any) -> None:
            try:
                changed = self.store.set(key, value)
            except ValueError as e:
                _log.warning("ค่าตั้งไม่ถูกต้อง ใช้ค่าเดิม", extra={"data": {"key": key, "err": str(e)}})
                changed = {key: self.store.flat().get(key)}
            self._push(changed)
            for k, v in changed.items():
                for fn in self._side_effects:
                    try:
                        fn(k, v)
                    except Exception:
                        _log.exception("ผลข้างเคียงของการตั้งค่าพัง")

        def _push(self, changed: dict[str, Any]) -> None:
            self._pushing = True
            try:
                for k, v in changed.items():
                    if self.cfg.value(k) != v:
                        self.cfg.insert(k, v)
            finally:
                self._pushing = False

        def _schedule_save(self) -> None:
            self._timer.start()

        @Slot()
        def flush(self) -> None:
            """บันทึกทันที (เรียกตอนปิดโปรแกรมด้วย)"""
            self._timer.stop()
            if self._save is not None:
                try:
                    self._save()
                except Exception:
                    _log.exception("บันทึกการตั้งค่าไม่สำเร็จ")

        # ---------- เบลอฉากหลังจริง (acrylic) ----------
        def set_window_provider(self, fn: Callable[[], Any]) -> None:
            """fn() -> หน้าต่างเนื้อเพลงลอย (QWindow) — app_window ตั้งให้หลังสร้าง UI"""
            self._window_provider = fn

        @Slot(bool, int)
        def applyBlurBehind(self, enabled: bool, radius: int) -> None:
            """QML เรียกเมื่อสไตล์/ขนาด/การมองเห็นของหน้าต่างเปลี่ยน — ใช้เอฟเฟกต์กับหน้าต่างจริง (พิกเซลอุปกรณ์)"""
            provider = getattr(self, "_window_provider", None)
            if provider is None:
                return
            try:
                from app.ui import winfx

                win = provider()
                if win is None or not win.isVisible():
                    return
                dpr = float(win.devicePixelRatio())
                pad = 12 if False else 0
                winfx.apply_blur_behind(int(win.winId()), bool(enabled), int(win.width() * dpr), int(win.height() * dpr),
                                        int(radius * dpr))
            except Exception:
                _log.exception("ตั้งค่าเบลอฉากหลังไม่สำเร็จ")

        # ---------- สำหรับ QML ----------
        @Slot(str)
        def resetGroup(self, prefix: str) -> None:
            self._after_reset(self.store.reset_group(prefix))

        @Slot(str)
        def resetPage(self, page: str) -> None:
            """ปุ่ม "คืนค่าหมวดนี้" ของหน้าตั้งค่า: general/full/float/font/theme/lyrics/anim/hotkeys"""
            self._after_reset(self.store.reset_page(page))

        @Slot()
        def resetAll(self) -> None:
            self._after_reset(self.store.reset_all())

        @Slot(str, "QVariant", result=bool)
        def isDefault(self, key: str, value: Any) -> bool:
            """QML ส่งค่าปัจจุบันมาด้วย เพื่อให้ binding ในหน้าตั้งค่าคำนวณใหม่ทุกครั้งที่ค่าเปลี่ยน (ปุ่ม ↺ โผล่เมื่อไม่ใช่ค่าเริ่มต้น)"""
            return self.store.is_default(key, value)

        @Slot(str)
        def resetKey(self, key: str) -> None:
            """ปุ่ม ↺ ข้างตัวเลือกเดียว: คืนค่าเริ่มต้นของตัวเลือกนั้นอย่างเดียว"""
            try:
                self._after_reset(self.store.reset_key(key))
            except ValueError as e:
                _log.warning("คืนค่าตัวเลือกไม่สำเร็จ", extra={"data": {"key": key, "err": str(e)}})

        # ---------- ชุดการตั้งค่าที่ตั้งชื่อไว้ ----------
        @Slot(str, result=str)
        def savePreset(self, name: str) -> str:
            """บันทึกค่าปัจจุบันเป็นชุดชื่อ name (ชื่อซ้ำ = เขียนทับ) คืนข้อความผิดพลาด ("" = สำเร็จ)"""
            err = self._presets.save(name, self.store.snapshot())
            if not err:
                self.presetsChanged.emit()
            return err

        @Slot(str, result=bool)
        def loadPreset(self, name: str) -> bool:
            values = self._presets.get(name)
            if values is None:
                return False
            self._after_reset(self.store.apply_snapshot(values))
            return True

        @Slot(str)
        def deletePreset(self, name: str) -> None:
            if self._presets.delete(name):
                self.presetsChanged.emit()

        @Slot()
        def resetSize(self) -> None:
            """คืนขนาดเริ่มต้นของโหมดปัจจุบัน"""
            from app.core.config import OverlaySettings

            d = OverlaySettings()
            mode = self.store.settings.overlay.mode
            for k in (f"w_{mode}", f"h_{mode}"):
                self._apply(f"ov_{k}", getattr(d, k))

        def _after_reset(self, changed: dict[str, Any]) -> None:
            self._push(changed)
            for k, v in changed.items():
                for fn in self._side_effects:
                    try:
                        fn(k, v)
                    except Exception:
                        _log.exception("ผลข้างเคียงของการรีเซ็ตพัง")

        @Slot()
        def quit(self) -> None:
            """ออกจากโปรแกรม: ตั้งธงก่อน เพื่อให้หน้าต่างที่ปกติซ่อนลงถาด (ปฏิเสธการปิด) ยอมปิดจริง"""
            self._quitting = True
            self.quittingChanged.emit()
            if self._on_quit is not None:
                self._on_quit()

        presetNames = Property(list, lambda s: s._presets.names(), notify=presetsChanged)
        dataDir = Property(str, lambda s: s._data_dir, constant=True)
        quitting = Property(bool, lambda s: s._quitting, notify=quittingChanged)

    _CLASS = SettingsBridge
    return SettingsBridge
