"""SettingsStore + ธีม: ค่าจากหน้าตั้งค่า (QML) -> Settings โดยไม่ต้องมี Qt"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.ui import themes
from app.ui.settings_store import SettingsStore


def make() -> tuple[SettingsStore, list[int]]:
    calls: list[int] = []
    return SettingsStore(Settings(), lambda: calls.append(1)), calls


def test_flat_has_all_groups_and_none_becomes_empty_string() -> None:
    st, _ = make()
    flat = st.flat()
    assert flat["ov_mode"] == "focus" and flat["look_font_size"] == 44 and flat["hk_show_hide"] == "Ctrl+Alt+L"
    assert flat["st_close_to_tray"] is False       # ค่าเริ่มต้น: ปุ่มปิด = ปิดโปรแกรมจริง
    assert flat["ov_x"] == ""  # None -> "" (QML ไม่มี null ในแผนที่ค่า)


def test_set_coerces_qml_floats_and_reports_changes() -> None:
    st, calls = make()
    changed = st.set("ov_font_size", 40.0)  # QML ส่งเลขเป็น float
    assert st.settings.overlay.font_size == 40 and isinstance(st.settings.overlay.font_size, int)
    assert changed["ov_font_size"] == 40 and calls == [1]
    assert st.set("ov_font_size", 40) == {} and calls == [1]  # ไม่เปลี่ยน = ไม่เรียก on_change (ไม่เซฟซ้ำ)
    st.set("ov_x", 120.4)
    assert st.settings.overlay.x == 120
    st.set("ov_x", "")  # ว่าง = None
    assert st.settings.overlay.x is None


def test_invalid_values_are_rejected_and_state_is_untouched() -> None:
    st, calls = make()
    for key, bad in [("ov_font_size", 9999), ("ov_mode", "huge"), ("ov_bg_opacity", 2), ("nope_x", 1), ("ov_nothing", 1)]:
        with pytest.raises(ValueError):
            st.set(key, bad)
    assert st.settings.overlay.font_size == 34 and st.settings.overlay.mode == "focus" and calls == []


def test_choosing_theme_applies_its_values_and_editing_color_makes_it_custom() -> None:
    st, _ = make()
    changed = st.set("ov_theme", "light")
    assert changed["ov_text_color"] == "#1C1C1E" and st.settings.overlay.bg_style == "solid"
    assert all(st.get(f"ov_{k}") == v for k, v in themes.PRESETS["light"].items())
    changed = st.set("ov_text_color", "#112233")
    assert st.settings.overlay.theme == "custom" and changed["ov_theme"] == "custom"
    # ค่าที่ไม่ใช่เรื่องหน้าตา (โหมด/ล็อก/ตำแหน่ง) ไม่ทำให้ธีมเปลี่ยน
    st.set("ov_theme", "frosted")
    for k, v in [("ov_mode", "full"), ("ov_locked", True), ("ov_x", 10), ("ov_show_translation", False)]:
        st.set(k, v)
    assert st.settings.overlay.theme == "frosted"
    st.set("ov_theme", "custom")  # custom ไม่ทับค่าอะไร
    assert st.settings.overlay.text_color == themes.PRESETS["frosted"]["text_color"]


def test_every_preset_only_sets_valid_overlay_fields() -> None:
    st, _ = make()
    for name in themes.PRESETS:
        st.set("ov_theme", name)  # ถ้า preset มีค่านอกช่วง pydantic จะโยน error ที่นี่


def test_reset_group_and_all() -> None:
    st, calls = make()
    st.set("ov_font_size", 80)
    st.set("look_font_size", 60)
    st.set("hk_show_hide", "Ctrl+Alt+Q")
    changed = st.reset_group("ov")
    assert changed["ov_font_size"] == 34 and st.settings.lyrics_look.font_size == 60
    st.reset_all()
    assert st.settings.lyrics_look.font_size == 44 and st.settings.hotkeys.show_hide == "Ctrl+Alt+L"


def test_animation_preset_applies_values_in_both_groups_and_custom_on_edit() -> None:
    from app.ui import anim_presets

    st, _ = make()
    changed = st.set("ov_anim_preset", "bouncy")   # ค่าเริ่มต้นคือ smooth จึงเลือกชุดอื่นเพื่อให้เห็นการเปลี่ยน
    assert st.settings.overlay.wave_ms == 60 and st.settings.overlay.blur == 0.2
    assert st.settings.lyrics_look.spring_stiffness == 260.0 and changed["look_spring_stiffness"] == 260.0
    # ปรับค่าแอนิเมชันเอง (แม้เป็นของกลุ่ม look) = ชุดกลายเป็น custom และไม่ทับค่าที่เพิ่งปรับ
    changed = st.set("look_spring_stiffness", 300)
    assert st.settings.overlay.anim_preset == "custom" and changed["ov_anim_preset"] == "custom"
    assert st.settings.lyrics_look.spring_stiffness == 300
    st.set("ov_anim_preset", "custom")  # custom ไม่ทับอะไร
    assert st.settings.lyrics_look.spring_stiffness == 300
    # ค่าที่ไม่ใช่เรื่องแอนิเมชัน (ธีม/โหมด) ไม่ทำให้ชุดเปลี่ยน
    st.set("ov_anim_preset", "bouncy")
    st.set("ov_theme", "light")
    st.set("ov_mode", "minimal")
    assert st.settings.overlay.anim_preset == "bouncy"


def test_every_animation_preset_is_valid_and_within_ui_spec() -> None:
    from app.ui import anim_presets

    st, _ = make()
    for name in anim_presets.PRESETS:
        st.set("ov_anim_preset", name)  # ค่าในชุดต้องผ่านการตรวจช่วงของ pydantic
    # UX UI ข้อ 4.2: หลีกเลี่ยงการเด้งแรง/ซูมเข้าออกบ่อย -> ไม่มีชุดไหนย่อบรรทัดเกินครึ่งหรือเด้งเกินสปริงที่กำหนด
    for p in anim_presets.PRESETS.values():
        if p["ov"]:
            assert p["ov"]["idle_scale"] >= 0.85 and p["ov"]["lift_px"] <= 3.0
            assert p["look"]["spring_damping"] >= 14


def test_default_animation_matches_the_smooth_preset() -> None:
    """ค่าเริ่มต้นใน config ต้องตรงกับชุด "smooth" ใน anim_presets (ไม่งั้นชุดที่แสดงว่าเลือกอยู่กับค่าจริงไม่ตรงกัน)"""
    from app.ui import anim_presets

    s = Settings()
    assert s.overlay.anim_preset == "smooth"
    for k, v in anim_presets.PRESETS["smooth"]["ov"].items():
        assert getattr(s.overlay, k) == v, k
    for k, v in anim_presets.PRESETS["smooth"]["look"].items():
        assert getattr(s.lyrics_look, k) == v, k


def test_reset_page_restores_only_that_pages_keys():
    from app.core.config import Settings
    from app.ui.settings_store import SettingsStore

    store = SettingsStore(Settings())
    defaults = Settings()
    store.set("ov_font_size", 60)
    store.set("ov_bg_opacity", 0.1)
    store.set("ov_word_anim", "char")
    store.set("fw_font_scale", 1.7)
    store.set("hk_show_hide", "Ctrl+Alt+Z")
    store.settings.fullwindow.w = 1500          # ขนาดหน้าต่างไม่ถูกแตะโดย "คืนค่าหมวดนี้"
    store.reset_page("font")
    assert store.get("ov_font_size") == defaults.overlay.font_size
    assert store.get("ov_bg_opacity") == 0.1    # หมวดอื่นไม่ถูกแตะ
    store.reset_page("anim")
    assert store.get("ov_word_anim") == defaults.overlay.word_anim and store.get("ov_anim_preset") == "smooth"
    store.reset_page("theme")
    assert store.get("ov_bg_opacity") == defaults.overlay.bg_opacity
    store.reset_page("full")
    assert store.get("fw_font_scale") == 1.0 and store.settings.fullwindow.w == 1500
    store.reset_page("hotkeys")
    assert store.get("hk_show_hide") == defaults.hotkeys.show_hide
    assert store.page_keys("nope") == []


def test_lyric_colors_set_in_font_page_also_apply_to_full_window():
    from app.core.config import Settings
    from app.ui.settings_store import SettingsStore

    store = SettingsStore(Settings())
    changed = store.set("ov_text_color", "#FCD34D")
    assert store.get("fw_text_color") == "#FCD34D" and "fw_text_color" in changed
    store.set("fw_text_color", "#00FF00")           # โหมดเต็มตั้งแยกเองได้ และไม่ย้อนไปเปลี่ยนหน้าต่างลอย
    assert store.get("ov_text_color") == "#FCD34D"


def test_is_default_and_reset_key_single_option():
    store, calls = make()
    assert store.is_default("ov_anim_speed", 1.0)
    store.set("ov_anim_speed", 2.0)
    assert not store.is_default("ov_anim_speed", store.get("ov_anim_speed"))
    store.set("ov_bg_opacity", 0.2)
    changed = store.reset_key("ov_anim_speed")
    assert store.get("ov_anim_speed") == 1.0 and "ov_anim_speed" in changed
    assert store.get("ov_bg_opacity") == 0.2                 # ตัวอื่นไม่ถูกแตะ
    assert store.is_default("ov_text_color", store.default_of("ov_text_color").lower())  # สีไม่สนตัวพิมพ์
    assert store.is_default("ov_nope", 1)                    # คีย์ไม่รู้จัก = ไม่แสดงปุ่ม
    with pytest.raises(ValueError):
        store.reset_key("ov_nope")


def test_reset_key_on_animation_value_marks_preset_custom_like_a_manual_edit():
    store, _ = make()
    store.set("ov_anim_preset", "bouncy")
    store.reset_key("ov_wave_ms")
    assert store.get("ov_anim_preset") == "custom"


def test_every_settings_row_key_in_qml_exists_in_store():
    """ทุก key="..." ในหน้าตั้งค่ามีอยู่จริง (ไม่งั้นปุ่ม ↺ ของแถวนั้นพังเงียบๆ)"""
    import re
    from pathlib import Path

    store, _ = make()
    flat = store.flat()
    qml = (Path(__file__).resolve().parent.parent / "app" / "ui" / "qml" / "SettingsView.qml").read_text(encoding="utf-8")
    keys = set(re.findall(r'key: "((?:ov|fw|look|hk|st)_[a-z_0-9]+)"', qml))
    missing = [k for k in keys if k not in flat and not k.startswith(("ov_w_", "ov_h_"))]
    assert not missing, missing
    for k in keys:
        if k in flat:
            assert store.is_default(k, store.default_of(k))


def test_snapshot_excludes_window_state_and_system_keys():
    store, _ = make()
    keys = set(store.preset_keys())
    assert "ov_font_size" in keys and "fw_font_scale" in keys and "ov_anim_speed" in keys and "look_spring_stiffness" in keys
    for bad in ("ov_x", "ov_y", "ov_visible", "ov_monitor", "fw_open", "fw_fullscreen", "fw_x", "hk_show_hide", "st_launch_with_windows"):
        assert bad not in keys, bad


def test_apply_snapshot_restores_values_without_theme_side_effects_and_skips_bad_keys():
    store, calls = make()
    store.set("ov_theme", "frosted")
    store.set("ov_font_size", 70)
    store.set("ov_word_anim", "char")
    snap = store.snapshot()
    assert snap["ov_theme"] == "frosted"
    store.reset_all()
    snap["ov_font_size"] = "ไม่ใช่ตัวเลข"          # ค่าผิดถูกข้าม
    snap["ov_nope"] = 1                            # คีย์ไม่รู้จักถูกข้าม
    snap["hk_show_hide"] = "Ctrl+Alt+Q"            # นอกชุด ถูกข้าม
    calls.clear()
    changed = store.apply_snapshot(snap)
    assert store.get("ov_theme") == "frosted" and store.get("ov_word_anim") == "char"
    assert store.get("ov_font_size") == Settings().overlay.font_size and "ov_font_size" not in changed
    assert store.get("hk_show_hide") == Settings().hotkeys.show_hide
    assert calls                                    # สั่งบันทึกไฟล์


def test_preset_store_save_load_overwrite_delete_and_persistence(tmp_path):
    from app.ui.settings_presets import MAX_NAME_LEN, PresetStore

    path = tmp_path / "p" / "presets.json"
    ps = PresetStore(path)
    assert ps.names() == []
    assert ps.save("  ", {}) != "" and ps.save("x" * (MAX_NAME_LEN + 1), {}) != "" and ps.save("a\x01b", {}) != ""
    assert ps.save("  ดูกลางคืน  ", {"ov_font_size": 40}) == ""
    assert ps.get("ดูกลางคืน") == {"ov_font_size": 40}
    assert ps.save("ดูกลางคืน", {"ov_font_size": 50}) == "" and ps.get("ดูกลางคืน") == {"ov_font_size": 50}
    assert ps.save("ทำงาน", {"ov_font_size": 30}) == ""
    assert ps.names()[0] == "ทำงาน"                 # ใหม่สุดก่อน
    again = PresetStore(path)                       # โหลดจากไฟล์
    assert set(again.names()) == {"ดูกลางคืน", "ทำงาน"} and again.get("ทำงาน") == {"ov_font_size": 30}
    assert again.delete("ทำงาน") is True and again.delete("ทำงาน") is False
    assert PresetStore(path).names() == ["ดูกลางคืน"]


def test_preset_store_survives_corrupt_file(tmp_path):
    from app.ui.settings_presets import PresetStore

    path = tmp_path / "presets.json"
    path.write_text("{ไม่ใช่ json", encoding="utf-8")
    ps = PresetStore(path)
    assert ps.names() == [] and path.with_suffix(".bad").exists()
    assert ps.save("ok", {"a": 1}) == "" and PresetStore(path).get("ok") == {"a": 1}
