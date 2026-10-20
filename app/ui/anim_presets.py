"""ชุดแอนิเมชันเนื้อเพลงสำเร็จรูป (ผู้ใช้ขอให้ปรับแต่งแอนิเมชันได้ 2026-10-20)

แต่ละชุดกำหนดค่าชุดเดียวกับที่ผู้ใช้ปรับเองได้ในหน้าตั้งค่า > เนื้อเพลง > แอนิเมชัน:
  "ov"   = OverlaySettings   ("ov_*")   animation, animation_intensity, anim_speed, wave_ms, blur, falloff, idle_scale, lift_px, reduced_motion
  "look" = LyricsLook        ("look_*") spring_stiffness, spring_damping (ความหนืด/ความแข็งของสปริงเลื่อน)
ปรับค่าใดค่าหนึ่งเองเมื่อไหร่ ชุดจะกลายเป็น "custom" อัตโนมัติ (SettingsStore) · แก้ที่นี่ที่เดียว ไม่มีตัวเลขแอนิเมชันฝังในที่อื่น
"""

from __future__ import annotations

from typing import Any

PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    # นุ่มนวลแบบ Apple Music (วัดจากคลิปจริง 2026-10-20): ไหลเสร็จใน ~0.4 วิ แบบ critically damped (ไม่เด้ง) · บรรทัดล่างเริ่มช้ากว่า ~0.3 ms/px · เบลอบรรทัดที่ไกล
    "smooth": {
        "ov": {"animation": "fade_move", "animation_intensity": 1.0, "anim_speed": 1.0, "wave_ms": 30, "blur": 0.35,
               "falloff": 0.12, "idle_scale": 0.92, "lift_px": 0.0, "reduced_motion": False,
               "word_anim": "none", "word_ease": "smooth", "word_anim_ms": 420, "word_scale": 1.0, "glow_strength": 0.0, "glow_color": "#FFFFFF", "word_hold_ms": 250, "word_release_ms": 700},
        "look": {"spring_stiffness": 256.0, "spring_damping": 32.0},
    },
    "balanced": {
        "ov": {"animation": "fade_move", "animation_intensity": 1.0, "anim_speed": 1.0, "wave_ms": 0, "blur": 0.0,
               "falloff": 0.12, "idle_scale": 0.92, "lift_px": 2.0, "reduced_motion": False,
               "word_anim": "word", "word_ease": "smooth", "word_anim_ms": 320, "word_scale": 1.0, "glow_strength": 0.5, "glow_color": "#FFFFFF", "word_hold_ms": 150, "word_release_ms": 450},
        "look": {"spring_stiffness": 170.0, "spring_damping": 26.0},
    },
    # เด้งนิดๆ (ยังต่ำกว่าที่ UX UI ห้าม "เด้งแรง") + ย่อ/ขยายเห็นชัดขึ้น
    "bouncy": {
        "ov": {"animation": "fade_move", "animation_intensity": 1.2, "anim_speed": 1.0, "wave_ms": 60, "blur": 0.2,
               "falloff": 0.1, "idle_scale": 0.88, "lift_px": 3.0, "reduced_motion": False,
               "word_anim": "word", "word_ease": "spring", "word_anim_ms": 300, "word_scale": 1.12, "glow_strength": 0.5, "glow_color": "#FFFFFF", "word_hold_ms": 100, "word_release_ms": 350},
        "look": {"spring_stiffness": 260.0, "spring_damping": 15.0},
    },
    "snappy": {
        "ov": {"animation": "fade", "animation_intensity": 0.8, "anim_speed": 2.0, "wave_ms": 0, "blur": 0.0,
               "falloff": 0.15, "idle_scale": 1.0, "lift_px": 0.0, "reduced_motion": False,
               "word_anim": "none", "word_ease": "linear", "word_anim_ms": 120, "word_scale": 1.0, "glow_strength": 0.0, "glow_color": "#FFFFFF", "word_hold_ms": 0, "word_release_ms": 120},
        "look": {"spring_stiffness": 400.0, "spring_damping": 40.0},
    },
    "none": {
        "ov": {"animation": "fade", "animation_intensity": 0.0, "anim_speed": 1.0, "wave_ms": 0, "blur": 0.0,
               "falloff": 0.15, "idle_scale": 1.0, "lift_px": 0.0, "reduced_motion": True,
               "word_anim": "none", "word_ease": "linear", "word_anim_ms": 120, "word_scale": 1.0, "glow_strength": 0.0, "glow_color": "#FFFFFF", "word_hold_ms": 0, "word_release_ms": 0},
        "look": {"spring_stiffness": 170.0, "spring_damping": 26.0},
    },
    "custom": {"ov": {}, "look": {}},
}

PRESET_NAMES_TH: dict[str, str] = {
    "smooth": "นุ่มนวล (แบบ Apple)", "balanced": "สมดุล", "bouncy": "เด้งนิดๆ", "snappy": "ฉับไว",
    "none": "ไม่เคลื่อนไหว", "custom": "กำหนดเอง",
}

# คีย์แบบแบน (ov_x / look_x) ที่ชุดแอนิเมชันเป็นเจ้าของ: ผู้ใช้แก้เองแล้ว ชุดกลายเป็น custom
OWNED_KEYS: frozenset[str] = frozenset(
    {f"ov_{k}" for p in PRESETS.values() for k in p["ov"]} | {f"look_{k}" for p in PRESETS.values() for k in p["look"]})


def preset_values(name: str) -> dict[str, dict[str, Any]]:
    p = PRESETS.get(name, {"ov": {}, "look": {}})
    return {"ov": dict(p["ov"]), "look": dict(p["look"])}
