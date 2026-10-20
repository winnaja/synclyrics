"""คำบรรยาย YouTube (WebVTT) -> Lyrics ทีละบรรทัด

กรองบรรทัดที่ไม่ใช่เนื้อเพลง ([Music], ♪ อย่างเดียว, เสียงประกอบ) และรวมบรรทัดซ้ำที่ซ้อนเวลากัน
"""

from __future__ import annotations

import html
import re

from app.core.models import Line, Lyrics, TimingLevel, Word
from app.lyrics.thai import detect_language

_CUE_RE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")
_NOISE_RE = re.compile(r"^[\[(（【♪♫\s]*(music|instrumental|applause|เพลง|ดนตรี|เสียง.*)[\])）】♪♫\s]*$|^\s*[\[【][^\]】]{0,40}[\]】]\s*$", re.I)  # รวมคำบรรยายเสียงในวงเล็บเหลี่ยมล้วนๆ เช่น [Ring] [Laughter]


def _secs(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_vtt(text: str, source: str = "youtube_subs") -> Lyrics:
    cues: list[tuple[float, float, str]] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        rows = block.strip().split("\n")
        for i, row in enumerate(rows):
            m = _CUE_RE.search(row)
            if not m:
                continue
            start = _secs(m.group(1), m.group(2), m.group(3), m.group(4))
            end = _secs(m.group(5), m.group(6), m.group(7), m.group(8))
            body = html.unescape(_TAG_RE.sub("", " ".join(rows[i + 1:]))).strip()
            body = re.sub(r"\s+", " ", body)
            if body and not _NOISE_RE.match(body) and set(body) - set("♪♫ "):
                cues.append((start, end, body.strip("♪♫ ")))
            break
    cues.sort(key=lambda c: c[0])
    lines: list[Line] = []
    for start, end, body in cues:
        if lines and lines[-1].text == body and start <= lines[-1].end + 0.05:
            lines[-1].end = max(lines[-1].end, end)  # รวมบรรทัดซ้ำที่ต่อเนื่องกัน
            continue
        lines.append(Line(start=start, end=end, words=[Word(body, start, end)]))
    return Lyrics(
        lines=lines, timing=TimingLevel.LINE if lines else TimingLevel.NONE, source=source,
        language=detect_language(" ".join(ln.text for ln in lines[:20])),
    )
