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
from pydantic import BaseModel, ConfigDict, Field

from app.core.paths import AppPaths

CURRENT_VERSIONS: dict[str, int] = {
    "settings.yaml": 1,
    "models.yaml": 1,
    "automix_rules.yaml": 1,
    "selectors.json": 1,
}

# MIGRATORS[ชื่อไฟล์][v] = ฟังก์ชันแปลงข้อมูลจาก v -> v+1
MIGRATORS: dict[str, dict[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    name: {} for name in CURRENT_VERSIONS
}


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
    spring_stiffness: float = Field(170.0, ge=10, le=1000)
    spring_damping: float = Field(26.0, ge=1, le=200)
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


class LyricsSourceSettings(_Model):
    # ชื่อ plugin -> เปิด/ปิด (plugin ที่ไม่มีในนี้ใช้ค่า enabled_by_default ของมันเอง)
    enabled: dict[str, bool] = {}
    allow_ai_transcribe: bool = True


class PlaybackSettings(_Model):
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


class StartupSettings(_Model):
    launch_with_windows: bool = False
    minimize_to_tray: bool = True
    open_browser: Literal["youtube", "youtube_music", "none"] = "youtube"
    extension_sends_current_video: bool = True


class Settings(_Model):
    version: int = 1
    lyrics_look: LyricsLook = LyricsLook()
    background: BackgroundSettings = BackgroundSettings()
    desktop_lyrics: DesktopLyricsSettings = DesktopLyricsSettings()
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


class WhisperCfg(_Model):
    enabled: bool = True
    model: str = "large-v3-turbo"
    compute_type: str = "float16"
    fallback_compute_type: str = "int8_float16"
    keep_loaded: bool = False  # False = โหลดเฉพาะตอนใช้แล้ว unload (ประหยัด VRAM)
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


class ModelsConfig(_Model):
    version: int = 1
    device: Literal["auto", "cuda", "cpu"] = "auto"
    vram_budget_mb: int = 6500
    vram_reserve_mb: int = 1200  # เหลือไว้ให้ UI/shader/วิดีโอ
    cudnn_benchmark: bool = True
    empty_cache_after_track: bool = True
    worker_priority: Literal["below_normal", "idle", "normal"] = "below_normal"
    watchdog_timeout_s: float = 20.0
    demucs: DemucsCfg = DemucsCfg()
    align: AlignCfg = AlignCfg()
    whisper: WhisperCfg = WhisperCfg()
    beats: BeatsCfg = BeatsCfg()
    progressive: ProgressiveCfg = ProgressiveCfg()


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
