"""เวลาแบบประมาณ — ใช้ระหว่างรอ AI และเมื่อ AI ไม่มั่นใจ (ข้อ 4.4)

- กระจายเวลาในบรรทัดตามจำนวนพยางค์/ตัวอักษรของแต่ละคำ (ไทย: นับพยางค์ด้วย pythainlp)
- คำท้ายบรรทัดได้น้ำหนักมากกว่า (มักลากเสียง)
- เนื้อเพลงไม่มีเวลาเลย: กระจายบรรทัดตลอดช่วงที่มีเสียงร้อง (ถ้ารู้) หรือทั้งเพลง
ต้องเร็วมาก (< 50ms ต่อเพลง) เพราะต้องขึ้นจอภายใน 1 วิหลังกดเล่น
"""

from __future__ import annotations

import copy

from app.core.models import Line, Lyrics, TimingLevel, Word, WordTimingSource
from app.lyrics.thai import syllable_count, tokenize_with_spaces

LAST_WORD_WEIGHT = 1.6
# เพดานเวลาร้องต่อบรรทัด: บรรทัดสั้นที่ห่างจากบรรทัดถัดไปมากๆ (ช่วงดนตรี) ไม่ควรยืดคำให้ช้าผิดจริง
MIN_SING_S = 3.0
SING_S_PER_CHAR = 0.3
SING_S_BASE = 1.5
# เพลงที่ไม่มีเวลาเลย: เผื่อ intro/outro เมื่อไม่รู้ช่วงเสียงร้อง
DEFAULT_INTRO_FRAC = 0.06
DEFAULT_OUTRO_FRAC = 0.06


def _effective_end(line: Line, text: str) -> float:
    cap = line.start + max(MIN_SING_S, SING_S_PER_CHAR * len(text) + SING_S_BASE)
    return min(line.end, cap) if line.end > line.start else cap


def estimate_line(line: Line) -> Line:
    """ใส่เวลาทีละคำให้บรรทัดที่มีเวลาเริ่ม/จบแล้ว (คืนบรรทัดใหม่ ไม่แก้ของเดิม)"""
    text = line.text
    toks = tokenize_with_spaces(text)
    if not toks:
        return copy.copy(line)
    weights = [float(syllable_count(w)) for w, _ in toks]
    weights[-1] *= LAST_WORD_WEIGHT
    total = sum(weights)
    end = _effective_end(line, text)
    span = max(0.0, end - line.start)
    words: list[Word] = []
    t = line.start
    for (w, space), weight in zip(toks, weights, strict=True):
        dur = span * weight / total
        words.append(Word(w, t, t + dur, timing=WordTimingSource.ESTIMATED, trailing_space=space))
        t += dur
    return Line(
        start=line.start, end=line.end, words=words, voice=line.voice,
        translation=line.translation, romanization=line.romanization,
    )


def _distribute_untimed(lines: list[Line], t0: float, t1: float) -> None:
    """เนื้อเพลงไม่มีเวลา: กระจายบรรทัดตามจำนวนตัวอักษร ระหว่าง t0..t1 (แก้ start/end ในที่เดิม)"""
    weights = [max(4, len(ln.text)) + 6 for ln in lines]  # +6 = เวลาหายใจระหว่างบรรทัด
    total = sum(weights)
    t = t0
    for ln, w in zip(lines, weights, strict=True):
        dur = (t1 - t0) * w / total
        ln.start, ln.end = t, t + dur
        t += dur


def estimate_lyrics(lyrics: Lyrics, duration: float,
                    vocal_segments: list[tuple[float, float]] | None = None) -> Lyrics:
    """ทั้งเพลง: บรรทัดที่ไม่มีเวลาจะถูกกระจายก่อน แล้วค่อยกระจายคำ (คืน Lyrics ใหม่)

    คำที่ได้ถูกทำเครื่องหมาย ESTIMATED — ส่วน lyrics.timing ยังคงระดับเดิม (NONE/LINE)
    เพื่อให้ AI รู้ว่ายังต้อง align
    """
    if lyrics.timing == TimingLevel.WORD or not lyrics.lines:
        return lyrics
    out = copy.deepcopy(lyrics)
    if out.timing == TimingLevel.NONE:
        if vocal_segments:
            t0, t1 = vocal_segments[0][0], vocal_segments[-1][1]
        else:
            t0, t1 = duration * DEFAULT_INTRO_FRAC, duration * (1 - DEFAULT_OUTRO_FRAC)
        _distribute_untimed(out.lines, t0, max(t1, t0 + 1.0))
    out.lines = [estimate_line(ln) for ln in out.lines]
    return out
