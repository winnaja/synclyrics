"""LRC และ Enhanced LRC (A2 extension: <mm:ss.xx> ทีละคำ)

ใช้ทั้งอ่าน (LRCLIB) และเขียน (export จาก Tap Sync ข้อ 9.4)
รองรับ: [offset:+/-ms], หลาย timestamp ต่อบรรทัด, บรรทัดว่าง = ช่วงดนตรี, [ar:] [ti:] [length:]

โครงสร้างผลลัพธ์:
  - Enhanced LRC ครบทุกบรรทัด -> TimingLevel.WORD (Word ต่อคำจริง)
  - LRC ธรรมดา -> TimingLevel.LINE โดยแต่ละบรรทัดมี Word เดียวเต็มบรรทัด
    (timing_estimate จะแตกเป็นคำตอนประมาณเวลา)
"""

from __future__ import annotations

import re

from app.core.models import Line, Lyrics, TimingLevel, Word, WordTimingSource
from app.lyrics.thai import detect_language

_TS = r"(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?"
_LINE_TS_RE = re.compile(r"\[" + _TS + r"\]")
_WORD_TS_RE = re.compile(r"<" + _TS + r">")
_TAG_RE = re.compile(r"^\[([A-Za-z]+):(.*)\]\s*$")
_DEFAULT_LAST_LINE_S = 4.0
# บรรทัดเครดิตที่แหล่งเนื้อเพลง (โดยเฉพาะ NetEase/QQ) ใส่ไว้ต้นเพลง เช่น "作词 : ..." "Produced by: ..." ไม่ใช่เนื้อร้อง
_CREDIT_RE = re.compile(
    r"^\s*(?:作词|作詞|作曲|编曲|編曲|制作人|製作人|监制|混音|母带|录音|和声|吉他|贝斯|鼓|弦乐|策划|出品|发行|词|曲|"
    r"lyrics?(?:\s+by)?|words?\s+by|music(?:\s+by)?|composed?\s+by|composer|written\s+by|writers?|"
    r"produced?\s+by|producers?|arranged?\s+by|arrangement|mixed?\s+by|mastered?\s+by|recorded?\s+by|"
    r"vocals?\s+by|เนื้อร้อง|ทำนอง|เรียบเรียง|โปรดิวเซอร์|ผลิตโดย)\s*[:：]",
    re.I,
)


def is_credit_line(text: str) -> bool:
    """บรรทัดนี้เป็นเครดิต (ผู้แต่ง/ผู้ผลิต) ไม่ใช่เนื้อเพลงใช่ไหม — ทุก parser ใช้กรองออก"""
    return _CREDIT_RE.match(text) is not None


def _is_header_line(text: str, t: float, next_t: float | None) -> bool:
    """บรรทัดหัวเพลง 'ชื่อเพลง - ศิลปิน' ที่ QQ/NetEase ใส่ไว้ที่ 0 วิ (เช่น '사랑이 잘 - IU (아이유)/吴赫 (오혁)') ไม่ใช่เนื้อร้อง

    ดูเฉพาะบรรทัดแรก: เริ่มก่อน 1 วิ มี ' - ' คั่น และบรรทัดถัดไปห่างออกไปอย่างน้อย 3 วิ (เนื้อร้องจริงยังไม่เริ่ม)
    """
    return t < 1.0 and " - " in text and (next_t is None or next_t - t >= 3.0)


def _to_seconds(m: re.Match[str]) -> float:
    minutes, seconds, frac = m.group(1), m.group(2), m.group(3)
    value = int(minutes) * 60 + int(seconds)
    if frac:
        value += int(frac) / (10 ** len(frac))
    return float(value)


def parse_time_tag(text: str) -> float | None:
    """แปลง "mm:ss.xx" (ไม่มีวงเล็บ) เป็นวินาที — ใช้ร่วมกับ parser อื่น"""
    m = re.fullmatch(_TS, text.strip())
    return _to_seconds(m) if m else None


def _parse_enhanced(body: str, line_start: float) -> list[Word] | None:
    """แยกคำจาก "<t>คำ <t>คำ <t>" คืน None ถ้าบรรทัดนี้ไม่มีเวลาทีละคำ"""
    marks = list(_WORD_TS_RE.finditer(body))
    if not marks:
        return None
    words: list[Word] = []
    # ข้อความก่อน tag แรก (ถ้ามี) นับเป็นคำแรกเริ่มที่เวลาของบรรทัด
    lead = body[: marks[0].start()]
    segments: list[tuple[float, str]] = []
    if lead.strip():
        segments.append((line_start, lead))
    for i, m in enumerate(marks):
        end_text = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        segments.append((_to_seconds(m), body[m.end():end_text]))
    # tag สุดท้ายที่ไม่มีข้อความตามหลัง = เวลาจบคำสุดท้าย
    for i, (t, text) in enumerate(segments):
        if not text.strip():
            continue
        nxt = segments[i + 1][0] if i + 1 < len(segments) else t + 0.5
        words.append(
            Word(
                text=text.strip(), start=t, end=max(nxt, t),
                timing=WordTimingSource.SOURCE,
                trailing_space=text.endswith((" ", "　")),
            )
        )
    if words:
        words[-1].trailing_space = False
    return words or None


def parse_lrc(text: str, source: str = "lrc", duration: float | None = None) -> Lyrics:
    """แปลง LRC/Enhanced LRC เป็น Lyrics (timing = WORD ถ้ามีเวลาทีละคำครบ)"""
    meta: dict[str, str] = {}
    entries: list[tuple[float, str]] = []  # (เวลา, ข้อความดิบ) ข้อความว่าง = ตัวบอกจบบรรทัด
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        raw = raw.strip("﻿ \t")
        if not raw:
            continue
        stamps = list(_LINE_TS_RE.finditer(raw))
        if not stamps:
            tag = _TAG_RE.match(raw)
            if tag:
                meta[tag.group(1).lower()] = tag.group(2).strip()
            continue
        # timestamp ต้องอยู่ต้นบรรทัดติดกัน
        pos = 0
        times: list[float] = []
        for m in stamps:
            if m.start() != pos:
                break
            times.append(_to_seconds(m))
            pos = m.end()
        if not times:
            continue
        body = raw[pos:]
        for t in times:
            entries.append((t, body))

    offset = 0.0
    if "offset" in meta:
        try:
            offset = int(meta["offset"].replace("+", "")) / 1000.0
        except ValueError:
            offset = 0.0
    entries = [(max(0.0, t - offset), body) for t, body in entries]
    entries.sort(key=lambda e: e[0])

    lines: list[Line] = []
    word_lines = 0
    for i, (t, body) in enumerate(entries):
        plain = _WORD_TS_RE.sub("", body).strip()
        if not plain or is_credit_line(plain):
            continue
        if not lines and _is_header_line(plain, t, entries[i + 1][0] if i + 1 < len(entries) else None):
            continue
        nxt = entries[i + 1][0] if i + 1 < len(entries) else (duration if duration and duration > t else t + _DEFAULT_LAST_LINE_S)
        words = _parse_enhanced(body, t)
        if words:
            word_lines += 1
            lines.append(Line(start=words[0].start, end=max(nxt, words[-1].end), words=words))
        else:
            lines.append(Line(start=t, end=max(nxt, t), words=[Word(plain, t, max(nxt, t))]))

    timing = TimingLevel.NONE
    if lines:
        timing = TimingLevel.WORD if word_lines >= max(1, int(len(lines) * 0.8)) else TimingLevel.LINE
    dur = None
    if "length" in meta:
        length = parse_time_tag(meta["length"])
        dur = length
    return Lyrics(
        lines=lines, timing=timing, source=source,
        language=detect_language(" ".join(ln.text for ln in lines[:20])),
        title=meta.get("ti"), artist=meta.get("ar"), duration=dur,
    )


def parse_plain(text: str, source: str = "plain") -> Lyrics:
    """เนื้อเพลงไม่มีเวลา: หนึ่งบรรทัดข้อความ = หนึ่ง Line (เวลาเป็น 0 รอ timing_estimate)"""
    lines = [
        Line(start=0.0, end=0.0, words=[Word(s, 0.0, 0.0)])
        for s in (raw.strip() for raw in text.replace("\r\n", "\n").split("\n"))
        if s and not is_credit_line(s)
    ]
    return Lyrics(
        lines=lines, timing=TimingLevel.NONE, source=source,
        language=detect_language(" ".join(ln.text for ln in lines[:20])),
    )


def to_enhanced_lrc(lyrics: Lyrics) -> str:
    """เขียน Lyrics เป็น Enhanced LRC (ใช้ export ใน Tap Sync) — เฟส 8"""
    raise NotImplementedError("เฟส 8")
