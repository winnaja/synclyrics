"""โหลดชุดข้อมูลสอนจาก dataset/songs/ (สร้างโดย scripts/harvest.py และการเก็บอัตโนมัติของแอป)

เพลงจาก harvest: meta.json มี "ref" = เนื้อเพลงรายคำที่มนุษย์จัดไว้ (NetEase) [{start,end,words:[[text,start,end]]}] + ref_offset_s (ค่าเลื่อนคงที่เทียบกับเสียง YouTube)
  ติดธง suspect = เฉลยไม่เข้ากับเสียง (คนละเวอร์ชัน/ตัดต่างกัน) → ไม่ใช้สอน/วัดผล
แบ่ง train/val ตามค่าแฮชของรหัสเพลง (คงที่ ไม่ปนกันข้ามรอบ): val ≈ 8%
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.core.dataset import DATASET_DIR

VAL_FRAC = 0.08


def split_of(song_id: str) -> str:
    h = int(hashlib.md5(song_id.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if h < VAL_FRAC else "train"


@dataclass
class Song:
    id: str
    dir: Path
    meta: dict[str, Any]

    @property
    def language(self) -> str | None:
        return self.meta.get("language")

    def vocals(self) -> np.ndarray:
        return np.load(self.dir / "vocals16k.npy", mmap_mode="r")

    def ref_lines(self) -> list[dict[str, Any]]:
        """เฉลยรายคำ เลื่อนเวลาให้ตรงกับเสียงของเพลงนี้แล้ว (บวก ref_offset_s)"""
        off = float(self.meta.get("ref_offset_s") or 0.0)
        out = []
        for ln in self.meta.get("ref", []):
            out.append({"start": ln["start"] + off, "end": ln["end"] + off,
                        "words": [[w[0], w[1] + off, w[2] + off] for w in ln["words"]]})
        return out


def iter_songs(split: str | None = None, only_good: bool = True) -> Iterator[Song]:
    """เพลงที่มีเฉลยรายคำ + เสียงร้อง (ไม่ suspect เมื่อ only_good)"""
    root = DATASET_DIR / "songs"
    if not root.exists():
        return
    for d in sorted(root.iterdir()):
        mp = d / "meta.json"
        if not mp.exists() or not (d / "vocals16k.npy").exists():
            continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not meta.get("ref"):
            continue
        if only_good and (meta.get("suspect") or meta.get("ref_offset_s") is None):
            continue
        if split and split_of(d.name) != split:
            continue
        yield Song(d.name, d, meta)


def make_clips(song: Song, min_s: float = 4.0, max_s: float = 16.0, pad_s: float = 0.25) -> list[dict[str, Any]]:
    """ตัดเพลงเป็นคลิปติดกันหลายบรรทัด (4-16 วิ) ให้ได้ (ช่วงเสียง, ข้อความ) สำหรับ CTC — เสียงยาวไปกินหน่วยความจำ ไม่พอเปรียบเทียบกับบริบท"""
    lines = song.ref_lines()
    clips: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for ln in lines:
        if not ln["words"]:
            continue
        if cur and (ln["end"] - cur[0]["start"] > max_s or ln["start"] - cur[-1]["end"] > 2.5):
            if cur[-1]["end"] - cur[0]["start"] >= min_s:
                clips.append(_clip(cur, pad_s))
            cur = []
        cur.append(ln)
    if cur and cur[-1]["end"] - cur[0]["start"] >= min_s:
        clips.append(_clip(cur, pad_s))
    return clips


def _clip(lines: list[dict[str, Any]], pad_s: float) -> dict[str, Any]:
    words = [w[0] for ln in lines for w in ln["words"]]
    return {"start": max(0.0, lines[0]["start"] - pad_s), "end": lines[-1]["end"] + pad_s, "words": words,
            "ref_words": [(w[0], w[1], w[2]) for ln in lines for w in ln["words"]]}
