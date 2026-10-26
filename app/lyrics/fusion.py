"""รวมเนื้อเพลงจากหลายแหล่งเป็น "ฉบับเดียวของ SyncLyrics" ด้วยฉันทามติถ่วงน้ำหนัก

ทำไมต้องมี: ระบบเดิมให้คะแนนแต่ละฉบับแล้วเลือกฉบับที่คะแนนสูงสุดมาแสดง "ทั้งฉบับ" ถ้าฉบับนั้นมีบรรทัดผิด
อยู่สองสามบรรทัด ผู้ใช้ก็เห็นผิดตามนั้น ทั้งที่แหล่งอื่นอาจมีบรรทัดเดียวกันถูก · ตัวนี้จึงตัดสิน "ทีละบรรทัด"
จากหลักฐานที่มีจริง แล้วประกอบเป็นเนื้อเพลงฉบับใหม่

หลักที่ยึด (ตามที่ผู้ใช้กำหนด):
- ห้ามเอาคนละเวอร์ชันมารวมกัน (live/remix/acoustic ต้องตรงกับฉบับหลัก)
- ฉบับที่เหมือนกันเป๊ะ = คัดลอกต่อกันมา นับเป็นเสียงเดียว ไม่ใช่หลายเสียง
- ห้ามแต่งคำขึ้นเอง เลือกได้เฉพาะข้อความที่มีอยู่จริงในฉบับใดฉบับหนึ่ง
- เก็บข้อความต้นฉบับไว้แสดงผล (normalize ใช้เทียบเท่านั้น)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from app.core.models import Lyrics, TimingLevel
from app.lyrics import scoring
from app.lyrics.sources.base import LyricsCandidate
from app.lyrics.timing_estimate import estimate_line

if TYPE_CHECKING:
    from app.core.models import Line, TrackMeta

FUSION_VERSION = 1          # เปลี่ยนเมื่อวิธีรวมเปลี่ยน -> cache เดิมถือว่าหมดอายุ
SOURCE_NAME = "fusion"

MIN_VOTERS = 2              # น้อยกว่านี้ไม่มีอะไรให้เทียบ = ไม่ต้องรวม
MIN_LINES = 4
LINE_MATCH = 82             # ถือว่าเป็น "ข้อความเดียวกัน" เมื่อคล้ายกันเกินนี้
# เกณฑ์ "บรรทัดเดียวกันของเพลง" ตอนจัดแนว ต้องต่ำกว่ามาก เพราะบรรทัดที่เราอยากเทียบคือบรรทัดที่แต่ละแหล่ง
# เขียนไม่เหมือนกัน ถ้าใช้เกณฑ์เดียวกับข้างบน บรรทัดที่เห็นต่างกันจะจับคู่ไม่ติดและไม่มีวันถูกโหวตเลย
ALIGN_FLOOR = 0.45
SWAP_MARGIN = 1.10          # ข้อความอื่นต้องมีน้ำหนักมากกว่าของฉบับหลักเท่านี้ จึงจะเปลี่ยน (กันสลับไปมาเพราะเสียงปริ่ม)
GAP = -0.4                  # ค่าปรับการข้ามบรรทัดตอนจัดแนว (DP)


@dataclass(slots=True)
class FusionReport:
    """ไว้ตรวจย้อนหลังว่าฉบับสุดท้ายประกอบมาจากอะไร — ไม่ได้เอาไปแสดงบนหน้าหลัก"""

    voters: int                     # จำนวนเสียงที่ใช้จริง (หลังยุบฉบับซ้ำ)
    spine: str                      # แหล่งที่ใช้เป็นโครงของเพลง
    lines_total: int
    lines_replaced: int             # บรรทัดที่เปลี่ยนข้อความตามเสียงข้างมาก
    lines_agreed: int               # บรรทัดที่ทุกเสียงตรงกัน
    contributors: dict[str, int]    # แหล่ง -> จำนวนบรรทัดที่ถูกเลือกมาจากแหล่งนั้น


def _key(line: Line) -> str:
    return scoring._norm("".join(w.text for w in line.words))


def _candidate_keys(c: LyricsCandidate) -> list[str]:
    return [_key(ln) for ln in c.lyrics.lines]


def _version_ok(a: LyricsCandidate, b: LyricsCandidate) -> bool:
    """เวอร์ชันเข้ากันได้ไหม — live/remix/acoustic ของคนละฉบับห้ามรวมกัน"""
    if scoring._candidate_tags(a) != scoring._candidate_tags(b):
        return False
    # คนละตัวอักษรหลัก (เกาหลี vs จีน) = คนละภาษา/ฉบับแปล ห้ามเอาบรรทัดมาปนกัน
    return _main_script(a) == _main_script(b)


def _main_script(c: LyricsCandidate) -> str:
    fr = scoring.lyrics_scripts(c.lyrics)
    if not fr:
        return ""
    # คานะปนคันจิ = ญี่ปุ่น · ฮั่นจื้อล้วน = จีน
    if fr.get("kana", 0.0) >= 0.08:
        return "japanese"
    top = max(fr, key=lambda k: fr[k])
    return top


def _weight(c: LyricsCandidate) -> float:
    """น้ำหนักของเสียงหนึ่ง = คะแนนก่อนโบนัสฉันทามติ

    ใช้ base ไม่ใช่ score เพราะโบนัสฉันทามติคำนวณจากกลุ่มเดียวกันนี้ ถ้าเอามาถ่วงน้ำหนักอีกรอบ
    จะกลายเป็นยืนยันตัวเองวนซ้ำ
    """
    return max(0.0, float(c.score_detail.get("base", c.score)))


def _dedupe(voters: list[LyricsCandidate]) -> list[LyricsCandidate]:
    """ฉบับที่ข้อความเหมือนกันทั้งฉบับ = คัดลอกต่อกันมา เก็บตัวที่คะแนนสูงสุดไว้ตัวเดียว"""
    best: dict[str, LyricsCandidate] = {}
    for c in voters:
        sig = "\n".join(k for k in _candidate_keys(c) if k)
        cur = best.get(sig)
        if cur is None or _weight(c) > _weight(cur):
            best[sig] = c
    return list(best.values())


def _align(a: list[str], b: list[str]) -> list[int | None]:
    """จัดแนวบรรทัดสองฉบับ -> สำหรับแต่ละบรรทัดของ a บอกว่าตรงกับบรรทัดไหนของ b (None = ไม่มี)

    ใช้ DP แบบ Needleman-Wunsch เพราะแต่ละเว็บแบ่งบรรทัดไม่เหมือนกัน มีบรรทัดขาด/เกิน/สลับ
    เทียบด้วย index ตรงๆ ไม่ได้
    """
    n, m = len(a), len(b)
    if not n or not m:
        return [None] * n
    sim = [[0.0] * m for _ in range(n)]
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            if not x or not y:
                continue
            r = 1.0 if x == y else fuzz.ratio(x, y) / 100.0
            sim[i][j] = r if r >= ALIGN_FLOOR else 0.0
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(dp[i - 1][j - 1] + sim[i - 1][j - 1], dp[i - 1][j] + GAP, dp[i][j - 1] + GAP)
    out: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        if dp[i][j] == dp[i - 1][j - 1] + sim[i - 1][j - 1]:
            if sim[i - 1][j - 1] > 0:
                out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif dp[i][j] == dp[i - 1][j] + GAP:
            i -= 1
        else:
            j -= 1
    return out


def fuse(candidates: list[LyricsCandidate], meta: TrackMeta | None = None,
         duration: float | None = None) -> tuple[LyricsCandidate, FusionReport] | None:
    """-> (ฉบับที่รวมแล้ว, รายงาน) หรือ None เมื่อหลักฐานไม่พอให้รวม (ผู้เรียกใช้ฉบับเดิมต่อ)"""
    usable = [c for c in candidates
              if _weight(c) >= scoring.CONSENSUS_VOTER_MIN and len(c.lyrics.lines) >= MIN_LINES]
    if len(usable) < MIN_VOTERS:
        return None
    spine = max(usable, key=_weight)
    group = _dedupe([c for c in usable if _version_ok(c, spine)])
    if len(group) < MIN_VOTERS:
        return None
    spine = max(group, key=_weight)            # หลังยุบฉบับซ้ำแล้ว ตัวนำอาจเปลี่ยน
    others = [c for c in group if c is not spine]

    spine_keys = _candidate_keys(spine)
    maps = [(c, _align(spine_keys, _candidate_keys(c))) for c in others]

    lines: list[Line] = []
    replaced = agreed = 0
    contributors: dict[str, int] = {}
    for i, base_line in enumerate(spine.lyrics.lines):
        base_key = spine_keys[i]
        # รวบรวมข้อความที่แต่ละเสียงบอกสำหรับบรรทัดนี้ (ข้อความต้นฉบับ ไม่ใช่ normalized)
        votes: dict[str, float] = {base_key: _weight(spine)}
        texts: dict[str, tuple[str, LyricsCandidate]] = {base_key: (base_line.text, spine)}
        for cand, amap in maps:
            j = amap[i]
            if j is None:
                continue
            ln = cand.lyrics.lines[j]
            k = _key(ln)
            if not k:
                continue
            votes[k] = votes.get(k, 0.0) + _weight(cand)
            if k not in texts or _weight(cand) > _weight(texts[k][1]):
                texts[k] = (ln.text, cand)
        if len(votes) == 1:
            agreed += 1
        win_key = max(votes, key=lambda k: votes[k])
        # เปลี่ยนข้อความเฉพาะตอนเสียงข้างมากชนะชัดเจน — ปริ่มๆ ให้ยึดฉบับหลักไว้
        if win_key != base_key and votes[win_key] < votes[base_key] * SWAP_MARGIN:
            win_key = base_key
        win_text, win_from = texts[win_key]
        contributors[win_from.lyrics.source] = contributors.get(win_from.lyrics.source, 0) + 1
        if win_key == base_key:
            lines.append(copy.copy(base_line))
        else:
            replaced += 1
            # ข้อความเปลี่ยน = เวลาทีละคำของฉบับหลักใช้กับข้อความใหม่ไม่ได้ ต้องประมาณใหม่จากช่วงเวลาเดิม
            new_line = copy.copy(base_line)
            new_line.words = []
            src_line = next(ln for ln in win_from.lyrics.lines if _key(ln) == win_key)
            new_line.words = [copy.copy(w) for w in src_line.words]
            new_line = estimate_line(type(base_line)(
                start=base_line.start, end=base_line.end, words=new_line.words,
                voice=base_line.voice, translation=base_line.translation,
                romanization=base_line.romanization))
            lines.append(new_line)
    if not lines:
        return None

    fused = Lyrics(
        lines=lines,
        timing=spine.lyrics.timing if replaced == 0 else _downgrade(spine.lyrics.timing),
        source=SOURCE_NAME,
        source_id=f"v{FUSION_VERSION}:{spine.lyrics.source}:{spine.lyrics.source_id}",
        language=spine.lyrics.language,
        has_translation=spine.lyrics.has_translation,
        title=spine.lyrics.title, artist=spine.lyrics.artist, duration=spine.lyrics.duration,
    )
    out = LyricsCandidate(lyrics=fused, matched_title=spine.matched_title,
                          matched_artist=spine.matched_artist, matched_duration=spine.matched_duration)
    out.score = max(_weight(c) for c in group)
    out.score_detail = {"base": out.score, "fusion_version": float(FUSION_VERSION),
                        "voters": float(len(group)), "replaced": float(replaced)}
    report = FusionReport(voters=len(group), spine=spine.lyrics.source, lines_total=len(lines),
                          lines_replaced=replaced, lines_agreed=agreed, contributors=contributors)
    return out, report


def _downgrade(level: TimingLevel) -> TimingLevel:
    """มีบรรทัดที่ข้อความเปลี่ยน = เวลาทีละคำของบรรทัดนั้นเป็นค่าประมาณแล้ว บอกตามจริง"""
    return TimingLevel.LINE if level == TimingLevel.WORD else level
