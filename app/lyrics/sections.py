"""หาโครงสร้างท่อนของเพลงจากตัวเนื้อเพลงเอง (ไม่ใช้ AI/GPU — ผลเดิมทุกครั้ง เร็วทันที)

ท่อนที่ซ้ำกันทั้งก้อน = ท่อนฮุก (chorus) · ช่องว่างของเวลานานผิดปกติ = ขอบท่อน · ใช้บอกว่าบรรทัดไหนอยู่ท่อนเดียวกัน
(UI ใช้ไม่ให้ "ท่อนที่ค้างความสว่าง" ข้ามขอบท่อน) ทดลองโมเดลภาษา 1.7B แล้วแบ่งท่อนได้แย่กว่า (เดาเป็นก้อน 4 บรรทัดตายตัว) จึงใช้วิธีนี้
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

SIMILAR = 90          # บรรทัดสองบรรทัดนับว่า "ซ้ำ" เมื่อคล้ายกันเกินนี้
MIN_BLOCK = 2         # ก้อนซ้ำต้องยาวอย่างน้อยกี่บรรทัด
GAP_FACTOR = 2.0      # ช่องว่างยาวกว่าค่ากลางของเพลงกี่เท่าถือเป็นขอบท่อน
GAP_MIN_S = 2.5


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a == b or fuzz.ratio(a, b) >= SIMILAR)


def detect_sections(texts: list[str], starts: list[float], ends: list[float]) -> list[int]:
    """หมายเลขท่อนของแต่ละบรรทัด (เริ่ม 0 เพิ่มขึ้นทุกครั้งที่ขึ้นท่อนใหม่) · บรรทัดน้อยกว่า 4 = ท่อนเดียว"""
    n = len(texts)
    if n < 4:
        return [0] * n
    keys = [_key(t) for t in texts]
    boundary = [False] * (n + 1)        # boundary[i] = มีขอบท่อนก่อนบรรทัด i
    # 1) ก้อนที่ซ้ำ: เริ่มที่ i แล้ว j>i ที่ขึ้นต้นเหมือนกัน ยืดไปทั้งคู่จนต่างกัน
    best: list[tuple[int, int, int]] = []
    for i in range(n):
        for j in range(i + MIN_BLOCK, n):
            if not _same(keys[i], keys[j]):
                continue
            length = 0
            while j + length < n and i + length < j and _same(keys[i + length], keys[j + length]):
                length += 1
            if length >= MIN_BLOCK:
                best.append((length, i, j))
    covered = [False] * n
    for length, i, j in sorted(best, reverse=True):
        if all(covered[k] for k in range(i, i + length)) and all(covered[k] for k in range(j, j + length)):
            continue
        for a in (i, j):
            boundary[a] = True
            boundary[a + length] = True
            for k in range(a, a + length):
                covered[k] = True
    # 2) ช่องว่างของเวลา
    gaps = [max(0.0, starts[k + 1] - ends[k]) for k in range(n - 1)]
    pos = sorted(g for g in gaps if g > 0.0)
    med = pos[len(pos) // 2] if pos else 0.0
    for k, g in enumerate(gaps):
        if g >= GAP_MIN_S and g >= GAP_FACTOR * max(med, 0.3):
            boundary[k + 1] = True
    sec: list[int] = []
    cur = 0
    for i in range(n):
        if i > 0 and boundary[i]:
            cur += 1
        sec.append(cur)
    return sec
