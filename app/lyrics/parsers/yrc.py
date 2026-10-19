"""YRC ของ NetEase: [line_start_ms,line_dur_ms](word_start_ms,word_dur_ms,0)คำ...

บรรทัดที่ขึ้นต้นด้วย {"t":..,"c":[..]} เป็น metadata (ผู้แต่ง/ผู้เรียบเรียง) ต้องข้าม
รวมคำแปลจาก tlyric (LRC) เข้ากับบรรทัดตามเวลาที่ใกล้ที่สุด
"""

from __future__ import annotations

import re

from app.core.models import Line, Lyrics, TimingLevel, Word, WordTimingSource
from app.lyrics.parsers.lrc import is_credit_line, parse_lrc
from app.lyrics.thai import detect_language

_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_WORD_RE = re.compile(r"\((\d+),(\d+),-?\d+\)")
MAX_TRANSLATION_GAP_S = 1.5


def attach_translation(lines: list[Line], translation_lrc: str | None) -> bool:
    """ใส่คำแปล (LRC ระดับบรรทัด) ให้บรรทัดที่เวลาใกล้ที่สุด (ห่างไม่เกิน 1.5 วิ) คืน True ถ้าใส่ได้"""
    if not translation_lrc or not lines:
        return False
    tr = parse_lrc(translation_lrc, source="translation")
    used = False
    for t in tr.lines:
        text = t.text.strip()
        if not text:
            continue
        best = min(lines, key=lambda ln: abs(ln.start - t.start))
        if abs(best.start - t.start) <= MAX_TRANSLATION_GAP_S and best.translation is None:
            best.translation = text
            used = True
    return used


def parse_yrc(text: str, translation_lrc: str | None = None, source: str = "netease") -> Lyrics:
    lines: list[Line] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        raw = raw.strip()
        if not raw or raw.startswith("{"):
            continue
        m = _LINE_RE.match(raw)
        if not m:
            continue
        line_start = int(m.group(1)) / 1000.0
        line_end = (int(m.group(1)) + int(m.group(2))) / 1000.0
        body = m.group(3)
        marks = list(_WORD_RE.finditer(body))
        words: list[Word] = []
        for i, mk in enumerate(marks):
            seg_end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            seg = body[mk.end():seg_end]
            if not seg.strip():
                continue
            ws = int(mk.group(1)) / 1000.0
            we = (int(mk.group(1)) + int(mk.group(2))) / 1000.0
            words.append(
                Word(seg.strip(), ws, max(we, ws), timing=WordTimingSource.SOURCE,
                     trailing_space=seg.endswith(" "))
            )
        if not words or is_credit_line("".join(w.text + (" " if w.trailing_space else "") for w in words)):
            continue
        words[-1].trailing_space = False
        lines.append(Line(start=words[0].start, end=max(line_end, words[-1].end), words=words))
    has_tr = attach_translation(lines, translation_lrc)
    return Lyrics(
        lines=lines,
        timing=TimingLevel.WORD if lines else TimingLevel.NONE,
        source=source,
        language=detect_language(" ".join(ln.text for ln in lines[:20])),
        has_translation=has_tr,
    )
