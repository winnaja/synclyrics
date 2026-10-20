"""แบ่งบรรทัดเนื้อเพลงที่ยาวเกินไปเป็นบรรทัดสั้นๆ (แบบ Apple Music) — ผู้ใช้ว่าการแบ่งบรรทัดยังไม่ดี

เนื้อเพลงจากบางแหล่งมีทั้งประโยคในบรรทัดเดียว ("You know all that's fake and God knows why I need you") ซึ่งบนจอห่อเป็น 3 แถว
ที่นี่ตัดที่ "รอยต่อธรรมชาติ": หลังเครื่องหมายวรรคตอน · ก่อนคำเชื่อม (and/but/ที่/แต่ ...) · ไม่มี = ใกล้กึ่งกลางที่สุด
ทำหลังใส่เวลาทีละคำแล้ว (คำทุกคำมีเวลา) จึงตัดตามเวลาคำได้เลย · บรรทัดที่มีคำแปล/โรมันไม่ตัด (ต้องจับคู่ 1:1)
ความกว้างวัดเป็น "หน่วยอักษร": ตัวอักษรกว้าง (CJK) = 2 · ทั่วไป = 1
"""

from __future__ import annotations

import unicodedata

from app.core.models import Line, Lyrics, Word

# ตัดก่อนคำเชื่อมเหล่านี้ได้ (ตัวพิมพ์เล็ก/ไม่รวมเครื่องหมาย)
BREAK_BEFORE = frozenset({
    "and", "but", "or", "so", "because", "cause", "cuz", "when", "while", "if", "that", "till", "until", "then", "though", "although",
    "และ", "แต่", "หรือ", "เพราะ", "ที่", "เมื่อ", "ถ้า", "จน", "แล้ว", "ซึ่ง",
    "и", "но", "что", "если", "когда",
})
PUNCT_AFTER = ",;:—–-…!?.،、，；：。！？"
MIN_PART_WIDTH = 8


def width(text: str) -> int:
    """ความกว้างโดยประมาณของข้อความ (ตัวอักษรเต็มความกว้างนับ 2)"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _word_w(w: Word) -> int:
    return width(w.text) + (1 if w.trailing_space else 0)


def _norm_word(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


def _break_score(words: list[Word], k: int, total: int, left_w: int) -> float:
    """คะแนนการตัดก่อนคำที่ k (ยิ่งสูงยิ่งดี): สมดุลของความกว้างสองฝั่ง + โบนัสวรรคตอน/คำเชื่อม"""
    right_w = total - left_w
    balance = 1.0 - abs(left_w - right_w) / max(1, total)           # 1 = เท่ากันเป๊ะ
    score = balance * 10.0
    prev = words[k - 1].text.rstrip()
    if prev and prev[-1] in PUNCT_AFTER:
        score += 12.0
    if _norm_word(words[k].text) in BREAK_BEFORE:
        score += 8.0
    return score


def split_line(line: Line, max_width: int) -> list[Line]:
    """ตัดบรรทัดที่กว้างเกิน max_width (ซ้ำจนทุกท่อนไม่เกิน) · ตัดไม่ได้ = คืนบรรทัดเดิม"""
    words = line.words
    total = sum(_word_w(w) for w in words)
    if total <= max_width or len(words) < 4 or line.translation or line.romanization:
        return [line]
    best_k, best_score = -1, -1.0
    left = 0
    for k in range(1, len(words)):
        left += _word_w(words[k - 1])
        if left < MIN_PART_WIDTH or total - left < MIN_PART_WIDTH:
            continue
        s = _break_score(words, k, total, left)
        if s > best_score:
            best_k, best_score = k, s
    if best_k < 0:
        return [line]
    a, b = words[:best_k], words[best_k:]
    first = Line(start=a[0].start, end=b[0].start, words=list(a), voice=line.voice)
    second = Line(start=b[0].start, end=max(line.end, b[-1].end), words=list(b), voice=line.voice)
    return split_line(first, max_width) + split_line(second, max_width)


def split_long_lines(lyrics: Lyrics, max_width: int) -> Lyrics:
    """คืนเนื้อเพลงใหม่ที่ตัดบรรทัดยาวแล้ว (ไม่มีบรรทัดยาว = คืนตัวเดิม) · ต้องใส่เวลาทีละคำแล้ว"""
    changed = False
    out: list[Line] = []
    for ln in lyrics.lines:
        parts = split_line(ln, max_width) if ln.words else [ln]
        changed = changed or len(parts) > 1
        out.extend(parts)
    if not changed:
        return lyrics
    import dataclasses

    return dataclasses.replace(lyrics, lines=out)
