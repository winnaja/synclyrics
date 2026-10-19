"""ปกเพลงและสีจากปก (ข้อ 3.1, 3.2, 8)

ลำดับ: iTunes Search API (https://itunes.apple.com/search ไม่ต้องใช้ key)
แทน "100x100bb" ใน artworkUrl100 ด้วย "1000x1000bb" -> ไม่เจอใช้ thumbnail ของ YouTube (maxresdefault)
สีจากปก: k-means 4-5 สีใน OKLab บนรูปย่อ 64x64 (เร็ว ทำใน thread IO)
เก็บรูปใน cache/art/<videoId>.jpg และสีใน tracks.palette
การ interpolate สีระหว่างเพลงทำใน OKLCH (ข้อ 8) — ฟังก์ชันแปลงสีอยู่ที่นี่ให้ UI ใช้
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.models import TrackMeta, TrackRef


@dataclass(slots=True)
class Artwork:
    path: Path
    source: str                         # "itunes" | "youtube"
    palette: list[tuple[float, float, float]]  # OKLCH (L 0-1, C, H องศา)


async def fetch_artwork(track: TrackRef, meta: TrackMeta, target_dir: Path) -> Artwork | None:
    """หาปก + สกัดสี — เฟส 1 (ปก) / เฟส 3 (palette)"""
    raise NotImplementedError("เฟส 1")


def srgb_to_oklch(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """แปลงสี sRGB (0-1) เป็น OKLCH — เฟส 3"""
    raise NotImplementedError("เฟส 3")


def oklch_lerp(a: tuple[float, float, float], b: tuple[float, float, float], t: float) -> tuple[float, float, float]:
    """ผสมสีใน OKLCH (hue วิ่งทางที่สั้นกว่า) — เฟส 3"""
    raise NotImplementedError("เฟส 3")
