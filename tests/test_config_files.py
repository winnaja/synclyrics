"""ไฟล์ config ทุกไฟล์ต้องอ่านได้ ผ่านการตรวจ และมีเลขเวอร์ชัน (ข้อ 11.2)"""

from __future__ import annotations

import json

import pytest
import yaml

from app.core import config as cfg
from app.core.paths import PROJECT_ROOT, AppPaths


def test_all_config_files_have_current_version() -> None:
    for name, version in cfg.CURRENT_VERSIONS.items():
        path = PROJECT_ROOT / "config" / name
        assert path.exists(), f"ไม่มี config/{name}"
        data = cfg.read_raw(path)
        assert data.get("version") == version, f"{name} version ไม่ตรง"


def test_models_yaml_valid(app_paths: AppPaths) -> None:
    m, warnings = cfg.load_model(app_paths, "models.yaml", cfg.ModelsConfig)
    assert warnings == []
    assert m.vram_budget_mb <= 6500  # ข้อ 5.3: งบ VRAM รวมไม่เกินประมาณ 6.5 GB (RTX 4060)
    assert m.demucs.fp16 and m.align.fp16
    assert m.whisper.model == "large-v3-turbo"


def test_automix_rules_valid(app_paths: AppPaths) -> None:
    r, warnings = cfg.load_model(app_paths, "automix_rules.yaml", cfg.AutomixRules)
    assert warnings == []
    weights = r.compatibility["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-6, "น้ำหนักความเข้ากันต้องรวมได้ 1.0"
    assert r.thresholds["soft_crossfade_min_score"] == 40  # ข้อ 7.2
    assert r.learning["no_explore_below_score"] == 40  # ข้อ 7.5
    stars = r.learning["rewards"]["stars"]
    assert stars == {1: -1.0, 2: -0.5, 3: 0.0, 4: 0.5, 5: 1.0}


def test_settings_default_file_matches_model(app_paths: AppPaths) -> None:
    s, warnings = cfg.load_model(app_paths, "settings.yaml", cfg.Settings)
    assert warnings == []
    assert s.model_dump(mode="json") == cfg.Settings().model_dump(mode="json"), (
        "config/settings.yaml ไม่ตรงกับค่าเริ่มต้นใน Settings — สร้างใหม่ด้วย scripts/gen_default_settings.py"
    )


def test_user_settings_override_and_broken_file(app_paths: AppPaths) -> None:
    app_paths.settings_file.write_text("version: 1\nplayback:\n  preload_at_percent: 70\n", encoding="utf-8")
    s, warnings = cfg.load_model(app_paths, "settings.yaml", cfg.Settings)
    assert s.playback.preload_at_percent == 70
    assert s.playback.first_chunk_s == 25.0  # ค่าอื่นยังเป็นค่าเริ่มต้น
    assert warnings == []

    # ไฟล์ผู้ใช้พัง (YAML ผิด syntax / ชนิดข้อมูลผิด) -> ค่าเริ่มต้น + คำเตือน ไม่ crash
    for broken in ("playback: [1, 2", "playback: 5"):
        app_paths.settings_file.write_text(broken, encoding="utf-8")
        s, warnings = cfg.load_model(app_paths, "settings.yaml", cfg.Settings)
        assert s.playback.preload_at_percent == 50, broken
        assert warnings, broken


def test_newer_config_version_rejected() -> None:
    with pytest.raises(cfg.ConfigError):
        cfg.migrate_raw("models.yaml", {"version": 999})


def test_save_settings_roundtrip(app_paths: AppPaths) -> None:
    s = cfg.Settings()
    s.automix.boldness = "dj"
    cfg.save_settings(app_paths, s)
    loaded, _ = cfg.load_model(app_paths, "settings.yaml", cfg.Settings)
    assert loaded.automix.boldness == "dj"


def test_selectors_json_parses() -> None:
    data = json.loads((PROJECT_ROOT / "config" / "selectors.json").read_text(encoding="utf-8"))
    assert "youtube" in data and "youtube_music" in data


def test_themes_parse() -> None:
    for f in (PROJECT_ROOT / "themes").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["version"] == 1 and data["id"] == f.stem
        # key ในธีมต้องเป็น key ที่ Settings รู้จัก
        cfg.LyricsLook.model_validate(data.get("lyrics_look", {}))
        cfg.BackgroundSettings.model_validate(data.get("background", {}))


def test_yaml_files_utf8_thai_comments() -> None:
    # คอมเมนต์ภาษาไทยต้องอ่านได้ (กันไฟล์ถูกบันทึกเป็น ANSI)
    text = (PROJECT_ROOT / "config" / "automix_rules.yaml").read_text(encoding="utf-8")
    assert "กฎเหล็ก" in text
    yaml.safe_load(text)
