"""QRC ของ QQ Music: ข้อมูลเข้ารหัส (3DES แบบปรับแต่งของ QQ) + zlib
หลังถอดได้ XML ที่มี LyricContent: [line_start,line_dur]คำ(word_start,word_dur)...

สถานะเฟส 1: parse_qrc อ่านข้อความที่ถอดรหัสแล้วได้ครบ (มี test)
แต่ decrypt_qrc ยังไม่รองรับ — QQ ใช้ DES เวอร์ชันดัดแปลง (ตาราง S-box ไม่ตรงมาตรฐาน)
ที่ตรวจความถูกต้องแบบออฟไลน์ไม่ได้ source qqmusic จึงใช้ LRC ระดับบรรทัดจาก API แทน
(ดู docs/DECISIONS.md) ถ้าจะเพิ่ม: ใส่ตัวถอดรหัสใน decrypt_qrc แล้ว qqmusic.py จะใช้อัตโนมัติ
"""

from __future__ import annotations

import html
import re

from app.core.errors import SourceUnavailable
from app.core.models import Line, Lyrics, TimingLevel, Word, WordTimingSource
from app.lyrics.parsers.lrc import is_credit_line
from app.lyrics.parsers.yrc import attach_translation
from app.lyrics.thai import detect_language

_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_WORD_RE = re.compile(r"(.*?)\((\d+),(\d+)\)")
_CONTENT_RE = re.compile(r'LyricContent="(.*?)"\s*/?>', re.S)


def decrypt_qrc(hex_payload: str) -> str:
    """ยังไม่รองรับ (เฟส 1) — โยน SourceUnavailable ให้ source ข้ามเงียบๆ"""
    raise SourceUnavailable("qqmusic", "ยังไม่รองรับถอดรหัส QRC", hint="ใช้ LRC ระดับบรรทัดแทน")


def parse_qrc(text: str, translation_lrc: str | None = None, source: str = "qqmusic") -> Lyrics:
    """แปลงข้อความ QRC ที่ถอดรหัสแล้ว (XML หรือเนื้อหาล้วน) เป็น Lyrics ทีละคำ"""
    m = _CONTENT_RE.search(text)
    body = html.unescape(m.group(1)) if m else text
    lines: list[Line] = []
    for raw in body.replace("\r\n", "\n").split("\n"):
        raw = raw.strip()
        lm = _LINE_RE.match(raw)
        if not lm:
            continue
        line_start = int(lm.group(1)) / 1000.0
        line_end = (int(lm.group(1)) + int(lm.group(2))) / 1000.0
        words: list[Word] = []
        for wm in _WORD_RE.finditer(lm.group(3)):
            seg = wm.group(1)
            if not seg.strip():
                continue
            ws = int(wm.group(2)) / 1000.0
            we = (int(wm.group(2)) + int(wm.group(3))) / 1000.0
            words.append(Word(seg.strip(), ws, max(we, ws), timing=WordTimingSource.SOURCE,
                              trailing_space=seg.endswith(" ")))
        if not words or is_credit_line("".join(w.text + (" " if w.trailing_space else "") for w in words)):
            continue
        words[-1].trailing_space = False
        lines.append(Line(start=words[0].start, end=max(line_end, words[-1].end), words=words))
    has_tr = attach_translation(lines, translation_lrc)
    return Lyrics(
        lines=lines, timing=TimingLevel.WORD if lines else TimingLevel.NONE, source=source,
        language=detect_language(" ".join(ln.text for ln in lines[:20])), has_translation=has_tr,
    )
