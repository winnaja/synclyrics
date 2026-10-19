"""ชนิดข้อมูลหลักที่ไหลผ่านทั้งระบบ (เพลง, เนื้อเพลง, ผลวิเคราะห์)

กฎ: ทุก dataclass ที่นี่ต้องแปลงเป็น dict/JSON ได้ (ใช้ to_dict/from_dict)
เพราะต้องส่งข้าม process (AI worker) เก็บลง SQLite และส่งให้ UI
หน่วยเวลา = วินาที (float) เสมอ
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TimingLevel(str, Enum):
    """ระดับเวลาของเนื้อเพลง เรียงจากดีที่สุด"""

    WORD = "word"  # มีเวลาทีละคำจริง (YRC/QRC/Enhanced LRC/alignment)
    LINE = "line"  # มีเวลาทีละบรรทัด (LRC)
    NONE = "none"  # ไม่มีเวลาเลย (ต้องให้ AI จัดเวลา)

    @property
    def rank(self) -> int:
        return {"word": 2, "line": 1, "none": 0}[self.value]


class WordTimingSource(str, Enum):
    """เวลาของคำนี้มาจากไหน — UI ใช้ตัดสินว่าจะ morph ไปเวลาใหม่ไหม"""

    SOURCE = "source"  # จากแหล่งเนื้อเพลงโดยตรง
    ESTIMATED = "estimated"  # ประมาณจากจำนวนพยางค์ (ข้อ 4.4)
    ALIGNED = "aligned"  # จาก forced alignment (ข้อ 5.1 ขั้น 6)
    TAPPED = "tapped"  # ผู้ใช้กดเอง (Tap Sync)


class Voice(str, Enum):
    """เสียงของบรรทัด (ข้อ 3.3: เพลงคู่ / คอรัส)"""

    MAIN = "main"
    SECOND = "second"  # คนที่ 2 ชิดขวา
    BACKGROUND = "background"  # คอรัส/เสียงประสาน ตัวเล็กใต้บรรทัดหลัก


@dataclass(slots=True)
class Word:
    text: str
    start: float
    end: float
    confidence: float = 1.0
    timing: WordTimingSource = WordTimingSource.SOURCE
    # ช่องว่างหลังคำนี้ไหม (ภาษาไทยมักไม่มี ภาษาอังกฤษมี)
    trailing_space: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(slots=True)
class Line:
    start: float
    end: float
    words: list[Word]
    voice: Voice = Voice.MAIN
    translation: str | None = None
    romanization: str | None = None

    @property
    def text(self) -> str:
        return "".join(w.text + (" " if w.trailing_space else "") for w in self.words).rstrip()


@dataclass(slots=True)
class Lyrics:
    """เนื้อเพลงหนึ่งชุด จากแหล่งเดียว"""

    lines: list[Line]
    timing: TimingLevel
    source: str  # ชื่อ plugin เช่น "lrclib"
    source_id: str = ""  # id ในแหล่งนั้น (ใช้จำตัวเลือกของผู้ใช้)
    language: str | None = None  # "th", "en", "ja", ...
    has_translation: bool = False
    ai_transcribed: bool = False  # True = แสดงป้าย "ถอดเสียงโดย AI อาจมีคำผิด"
    title: str | None = None
    artist: str | None = None
    duration: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Lyrics":
        lines = [
            Line(
                start=ln["start"],
                end=ln["end"],
                words=[
                    Word(
                        text=w["text"], start=w["start"], end=w["end"],
                        confidence=w.get("confidence", 1.0),
                        timing=WordTimingSource(w.get("timing", "source")),
                        trailing_space=w.get("trailing_space", False),
                    )
                    for w in ln["words"]
                ],
                voice=Voice(ln.get("voice", "main")),
                translation=ln.get("translation"),
                romanization=ln.get("romanization"),
            )
            for ln in d["lines"]
        ]
        rest = {k: v for k, v in d.items() if k not in ("lines", "timing")}
        return Lyrics(lines=lines, timing=TimingLevel(d["timing"]), **rest)


@dataclass(slots=True)
class TrackRef:
    """ข้อมูลดิบของเพลงจาก YouTube / ส่วนขยาย (ก่อนแยกชื่อ)"""

    video_id: str
    title: str = ""
    channel: str = ""
    duration: float | None = None
    # ส่วน "Music" ใต้วิดีโอ เช่น {"song": "...", "artist": "...", "album": "..."}
    music_section: dict[str, str] = field(default_factory=dict)
    # metadata จาก yt-dlp (track, artist, album, release_year ...)
    ytdlp_meta: dict[str, Any] = field(default_factory=dict)
    thumbnail_url: str | None = None
    added_from: str = "unknown"  # "extension", "search", "paste", "playlist", "up_next"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TrackMeta:
    """ผลการแยกชื่อเพลง (ข้อ 4.1)"""

    title: str
    artist: str
    album: str | None = None
    duration: float | None = None
    # live / remix / cover / acoustic / sped-up ... ต้องตรงกับเนื้อเพลงที่เลือก (ข้อ 4.3)
    version_tags: frozenset[str] = frozenset()
    # คำค้นหลายแบบ เรียงจากน่าจะถูกที่สุด
    queries: tuple[str, ...] = ()


@dataclass(slots=True)
class Section:
    """ท่อนเพลง (จาก allin1 หรือตัวแบ่งท่อนแบบง่าย)"""

    start: float
    end: float
    label: str  # "intro", "verse", "chorus", "bridge", "outro", "inst", "unknown"


@dataclass(slots=True)
class Analysis:
    """ผลวิเคราะห์ดนตรีทั้งเพลง (ข้อ 5.1 ขั้น 3-5) — AutoMix ใช้ทั้งหมดนี้"""

    video_id: str
    bpm: float | None = None
    beat_confidence: float = 0.0  # 0-1 ต่ำ = ห้าม beat-match (ข้อ 7.1)
    beats: list[float] = field(default_factory=list)
    downbeats: list[float] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    key: str | None = None  # เช่น "A minor"
    camelot: str | None = None  # เช่น "8A"
    key_confidence: float = 0.0
    lufs: float | None = None  # integrated loudness
    vocal_segments: list[tuple[float, float]] = field(default_factory=list)
    # พลังงาน (RMS แบบ normalize 0-1) ท้ายและต้นเพลง สำหรับให้คะแนนความเข้ากัน
    energy_start: float | None = None
    energy_end: float | None = None
    ends_with_fade: bool | None = None
    is_music: bool = True  # False = พอดแคสต์/ไม่มี beat ชัด -> เฟดธรรมดา
    analyzer: str = ""  # "allin1" / "beat_this" — เก็บไว้ debug
    version: int = 1  # เปลี่ยนเมื่อวิธีวิเคราะห์เปลี่ยน -> cache เก่าถือว่าหมดอายุ

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
