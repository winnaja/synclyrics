"""เครื่องมือภาษาไทย: ตัดคำ, นับพยางค์, ตรวจภาษา (ข้อ 3.3)

ตัดคำด้วย pythainlp (engine "newmm") — โหลดครั้งแรกช้า ~1 วิ: warm-up ตอนเปิดโปรแกรมใน background
การวาดสระ/วรรณยุกต์ให้ถูกตำแหน่งเป็นงานของ UI (Qt text shaping ด้วย HarfBuzz)
สิ่งที่ module นี้ต้องรับประกัน: ห้ามตัดคำแยกสระบน/ล่าง/วรรณยุกต์ออกจากพยัญชนะ
(ตัด grapheme cluster เท่านั้น — ใช้ตอน Typewriter และ wipe ทีละตัวอักษร)
"""

from __future__ import annotations

import re
import unicodedata

_THAI_RE = re.compile(r"[฀-๿]")
_LEADING_VOWELS = "เแโใไ"
_ATTACH_TO_PREV = "ำ"  # สระอำ เป็น Lo แต่ต้องติดตัวหน้า
_LATIN_VOWEL_GROUP = re.compile(r"[aeiouyAEIOUY]+")


def has_thai(text: str) -> bool:
    return _THAI_RE.search(text) is not None


def warmup() -> None:
    """โหลดพจนานุกรมตัดคำล่วงหน้า (เรียกใน background ตอนเปิดโปรแกรม)"""
    tokenize("สวัสดี")


def _newmm(text: str) -> list[str]:
    try:
        from pythainlp.tokenize import word_tokenize

        return [t for t in word_tokenize(text, engine="newmm", keep_whitespace=False) if t.strip()]
    except Exception:  # pythainlp พัง = ตัดเป็น grapheme cluster แทน (ยังใช้งานได้)
        return graphemes(text)


def tokenize_with_spaces(text: str) -> list[tuple[str, bool]]:
    """ตัดคำไทยปนอังกฤษ คืน [(คำ, มีช่องว่างตามหลังไหม)]

    ช่องว่างในต้นฉบับคือขอบวลี: คำไทยคำสุดท้ายก่อนช่องว่างจึงถือว่ามีช่องว่างตามหลัง
    """
    out: list[tuple[str, bool]] = []
    chunks = text.split()
    for i, chunk in enumerate(chunks):
        last_chunk = i == len(chunks) - 1
        if has_thai(chunk):
            toks = _newmm(chunk)
            for j, tok in enumerate(toks):
                out.append((tok, (j == len(toks) - 1) and not last_chunk))
        else:
            out.append((chunk, not last_chunk))
    return out


def tokenize(text: str) -> list[str]:
    """ตัดคำไทยปนอังกฤษ คืนรายการคำ (ช่องว่างไม่รวม)"""
    return [w for w, _ in tokenize_with_spaces(text)]


def syllable_count(word: str) -> int:
    """จำนวนพยางค์โดยประมาณ (ไทยนับกลุ่มตัวอักษร TCC แล้วลดทอน, อังกฤษนับกลุ่มสระ)"""
    if has_thai(word):
        try:
            from pythainlp.tokenize import subword_tokenize

            n = len(subword_tokenize(word, engine="tcc"))
        except Exception:
            n = len(graphemes(word))
        # TCC ละเอียดกว่าพยางค์จริงราว 1.5 เท่า
        return max(1, round(n / 1.5))
    groups = _LATIN_VOWEL_GROUP.findall(word.lower())
    n = len(groups)
    if word.lower().endswith("e") and n > 1:
        n -= 1  # "love" = 1 พยางค์
    return max(1, n)


def graphemes(text: str) -> list[str]:
    """แยกเป็นกลุ่มตัวอักษรที่ห้ามแยกกัน (สระนำ + พยัญชนะ + สระบน/ล่าง + วรรณยุกต์)"""
    out: list[str] = []
    pending = ""  # สระนำ (เ แ โ ใ ไ) รอติดกับพยัญชนะถัดไป
    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith("M") or ch == _ATTACH_TO_PREV:
            if out:
                out[-1] += ch
            else:
                pending += ch
            continue
        if ch in _LEADING_VOWELS:
            pending += ch
            continue
        out.append(pending + ch)
        pending = ""
    if pending:
        out.append(pending)
    return out


def detect_language(text: str) -> str | None:
    """เดาภาษาจากสัดส่วนอักษร ("th", "en", "ja", "ko", "zh")"""
    counts = {"th": 0, "ja": 0, "ko": 0, "zh": 0, "en": 0}
    for ch in text:
        o = ord(ch)
        if 0x0E00 <= o <= 0x0E7F:
            counts["th"] += 1
        elif 0x3040 <= o <= 0x30FF:
            counts["ja"] += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            counts["ko"] += 1
        elif 0x4E00 <= o <= 0x9FFF:
            counts["zh"] += 1
        elif ch.isascii() and ch.isalpha():
            counts["en"] += 1
    total = sum(counts.values())
    if total == 0:
        return None
    if counts["ja"] > 0 and counts["ja"] + counts["zh"] >= total * 0.3:
        return "ja"  # ญี่ปุ่นปนคันจิ
    lang = max(counts, key=lambda k: counts[k])
    return lang if counts[lang] >= total * 0.3 else None
