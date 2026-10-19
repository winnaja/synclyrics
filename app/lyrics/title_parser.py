"""แยกชื่อเพลง/ศิลปินจากข้อมูล YouTube ให้แม่น (ข้อ 4.1)

ลำดับความน่าเชื่อถือ: ส่วน "Music" ใต้วิดีโอ > metadata ของ yt-dlp (track/artist) >
ชื่อช่องแบบ "<ศิลปิน> - Topic" > แยกจากชื่อวิดีโอ
ตัดคำขยะ: (Official MV), [Lyrics], Official Audio/Video, 4K, HD, ft./feat., Prod. by, VEVO, - Topic ...
เก็บ version tag: live / remix / cover / acoustic / sped up / slowed / instrumental / karaoke
คำค้นหลายแบบ: "ศิลปิน เพลง", "เพลง", ชื่อไทย/อังกฤษแยกกัน (ชื่อแบบ "ชื่อไทย (English Title)"), สลับลำดับ

ทดสอบด้วย tests/fixtures/titles.json (เพิ่มกรณีที่เคยแยกผิดทุกครั้ง)
"""

from __future__ import annotations

from app.core.models import TrackMeta, TrackRef


def parse_track(track: TrackRef) -> TrackMeta:
    """คืน TrackMeta พร้อมคำค้นเรียงตามความน่าจะถูก — เฟส 1"""
    raise NotImplementedError("เฟส 1")


def clean_title(title: str) -> tuple[str, frozenset[str]]:
    """ตัดคำขยะออกจากชื่อ คืน (ชื่อที่สะอาด, version tags) — เฟส 1"""
    raise NotImplementedError("เฟส 1")
