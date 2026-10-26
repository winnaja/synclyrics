"""ให้คะแนนผลเนื้อเพลงเพื่อเลือกอันที่ถูกเพลงอัตโนมัติ (ข้อ 4.3)

คะแนน 0-100 จาก:
  - ชื่อเพลงคล้าย (rapidfuzz token_set_ratio หลัง normalize)
  - ศิลปินตรง
  - ความยาวต่างไม่เกิน 3 วิ (เกิน 10 วิ = ตัดทิ้ง)
  - ระดับเวลา: ทีละคำ > ทีละบรรทัด > ไม่มีเวลา
  - version tag ต้องตรง (MV เป็น live แต่เนื้อเพลงเป็น studio = หักหนัก)
  - แหล่งที่ตรงกับวิดีโอโดยตรง (คำบรรยาย YouTube) ได้โบนัสเรื่องเวลา
น้ำหนักแต่ละข้อเก็บใน WEIGHTS ด้านล่าง (ปรับได้โดยไม่แตะ logic)
"""

from __future__ import annotations

from typing import Any

import re

from rapidfuzz import fuzz

from app.core.models import TrackMeta
from app.lyrics.sources.base import LyricsCandidate

WEIGHTS: dict[str, float] = {
    "title": 35.0,
    "artist": 20.0,
    "duration": 20.0,
    "timing": 15.0,
    "version": 10.0,
}
MAX_DURATION_DIFF_S = 3.0
# ต่างเกินนี้ (และเกิน 40% ของความยาว) ถือว่าคนละเพลง/คนละเวอร์ชันแน่ๆ -> ตัดทิ้ง
REJECT_DURATION_DIFF_S = 90.0
REJECT_DURATION_RATIO = 0.4
# MV มักยาวกว่าเสียงจริง (มีฉากเปิดเรื่อง) ต่างเกิน 10 วิยังรับได้แต่ลดคะแนน และแจ้งผู้ใช้ว่าเวลาอาจเลื่อน
SOFT_DURATION_DIFF_S = 10.0
SOFT_PENALTY_PER_S = 0.01
SOFT_PENALTY_FLOOR = 0.5
STRONG_MATCH_FLOOR = 0.8
# เนื้อเพลงเป็นเวอร์ชันอื่น (วิดีโอเป็นรีมิกซ์/สด แต่เนื้อเพลงเป็นต้นฉบับ) เวลามักไม่ตรง
VERSION_MISMATCH_FACTOR = 0.9
# ต่ำกว่านี้ถือว่า "ไม่ใช่เพลงนี้" (service จะไม่เลือก ไปทางถอดเสียงด้วย AI แทน)
MIN_ACCEPT_SCORE = 40.0
# ความคล้ายของชื่อที่ต่ำกว่านี้จะถูกลดคะแนนรวมตามสัดส่วน
TITLE_GATE = 0.6
# ศิลปินเป็นประตูกั้นเหมือนชื่อเพลง (ผู้ใช้ติติง 2026-10-26: "ไม่แมชศิลปิน ดูแต่ชื่อเพลงแล้วเอามาใส่เลย")
# เดิมศิลปินมีแค่น้ำหนัก 20/100 ชื่อเพลงตรงแต่ศิลปินคนละคนได้ 79-81 คะแนน ผ่านเกณฑ์ง่ายๆ (เช่น Everything ของ Lifehouse)
ARTIST_GATE = 0.5              # ศิลปินคล้ายกันต่ำกว่านี้ (เทียบอักษรชนิดเดียวกันได้) = คนละคน
ARTIST_MISMATCH_FACTOR = 0.3
# ศิลปินเขียนคนละระบบอักษร (The Black Skirts vs 黑裙子) เทียบข้อความไม่ได้ ห้ามตัดสินว่าผิด แต่ต้องมีหลักฐานอื่นช่วย
CROSS_SCRIPT_ARTIST_FACTOR = 0.8
CROSS_SCRIPT_SAFE_DIFF_S = 6.0  # ความยาวใกล้กันขนาดนี้ = หลักฐานพอว่าเป็นเพลงเดียวกัน ไม่ต้องลดคะแนน

# แหล่งที่ผูกกับวิดีโอโดยตรง (เวลาตรงกับ MV แน่นอน) ได้โบนัส
DIRECT_SOURCES = frozenset({"youtube_subs"})
DIRECT_SOURCE_BONUS = 8.0


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", " ", s.casefold()).strip()


# คำเสริมท้ายชื่อที่ไม่ทำให้เป็นคนละเพลง ตัดทิ้งก่อนเทียบ
_NOISE_WORDS = frozenset({
    "official", "audio", "video", "mv", "m/v", "music", "lyric", "lyrics", "visualizer", "visualiser", "hd", "hq", "4k",
    "remastered", "remaster", "explicit", "topic", "vevo", "version", "ver", "feat", "ft", "featuring", "prod", "with",
})


def _core_tokens(norm_text: str) -> list[str]:
    return [t for t in norm_text.split() if t and t not in _NOISE_WORDS]


def _similar(a: str, b: str) -> float:
    """0-1 ความคล้ายของข้อความสองชุด (ว่างข้างใดข้างหนึ่ง = ไม่รู้ ให้ 0.5)

    เดิมใช้ token_set_ratio ล้วนๆ ซึ่งให้ 100% ทันทีถ้าคำของข้อความสั้นเป็นส่วนย่อยของข้อความยาว
    ชื่อ 'EVERYTHING' จึงตรง 100% กับ 'Everything Everything - Regret (Official Audio)' (คนละเพลง คนละวง)
    และศิลปิน 'The Black Skirts' กับ 'Everything Everything' ก็ได้ 0.85 · ตอนนี้ถ้ามีคำเกินที่ไม่ใช่คำเสริมทั่วไป
    ต้องลดคะแนนตามสัดส่วนคำที่เกิน (ผู้ใช้ติติง 2026-10-26: 'หาแค่ชื่อเพลงแล้วเอามาใส่')
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.5
    base = fuzz.token_set_ratio(na, nb) / 100.0
    ta, tb = _core_tokens(na), _core_tokens(nb)
    if not ta or not tb:
        return base
    # ภาษาที่ไม่เว้นวรรค (ไทย/จีน/ญี่ปุ่น/เกาหลีติดกัน) แยกคำไม่ได้ ใช้ผลเดิม ไม่ลงโทษมั่ว
    if len(ta) < 2 and len(tb) < 2:
        return base
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    extra = [t for t in long_ if t not in short]
    if not extra:
        return base
    # คำเกินที่ซ้ำกับคำที่มีอยู่แล้ว (Everything Everything) ก็ยังนับเป็นคำเกิน — บอกว่าอีกฝั่งยาวกว่าจริง
    coverage = len(short) / len(long_)
    return min(base, 0.35 + 0.65 * coverage) if coverage < 1.0 else base


ALT_TITLE_FACTOR = 0.85  # เทียบกับชิ้นส่วนดิบของชื่อวิดีโอ (กรณีแยกลำดับศิลปิน/เพลงผิด) ได้ไม่เต็ม


_BRACKET_RE = re.compile(r"[\(\[【「『〈《][^\)\]】」』〉》]*[\)\]】」』〉》]")


def _variants(text: str) -> list[str]:
    """ข้อความเดิม + ข้อความที่ตัดเนื้อในวงเล็บออก (เช่น "ทน (Explicit)" -> "ทน")"""
    stripped = _BRACKET_RE.sub(" ", text).strip()
    return [text] if not stripped or stripped == text else [text, stripped]


def _best_similarity(text: str, primary: str, alts: tuple[str, ...]) -> float:
    """ความคล้ายของ text กับค่าที่แยกได้ หรือกับชิ้นส่วนใดชิ้นหนึ่งของชื่อวิดีโอ (ลดน้ำหนักลง)"""
    best = max(_similar(v, primary) for v in _variants(text))
    if _norm(text):
        for a in alts:
            if _norm(a):
                best = max(best, max(_similar(v, a) for v in _variants(text)) * ALT_TITLE_FACTOR)
    return best


def _candidate_tags(candidate: LyricsCandidate) -> frozenset[str]:
    from app.lyrics.title_parser import clean_title

    return clean_title(candidate.matched_title)[1]



# ---------------------------------------------------------------------------
# ตรวจตัวอักษรของเนื้อเพลงให้ตรงกับภาษาของเพลง (ผู้ใช้รายงาน 2026-10-26: เพลงเกาหลีได้เนื้อจีน/ญี่ปุ่น)
# ระบบเดิมไม่เคยดูภาษาของเนื้อเลย ดูแค่ชื่อ/ศิลปิน/ความยาว จึงปล่อยฉบับแปล ฉบับคัฟเวอร์ และฉบับคนละเพลงผ่านมาได้
# ---------------------------------------------------------------------------
SCRIPT_MISMATCH_FACTOR = 0.25   # ตัวอักษรไม่ตรงภาษาเพลง: คะแนนเหลือเท่านี้ (ต่ำกว่าเกณฑ์รับ ยกเว้นไม่มีอย่างอื่นเลย)
ROMANIZED_FACTOR = 0.6          # เพลงเกาหลี/ญี่ปุ่น/ไทย แต่เนื้อเป็นอักษรละติน (คำอ่าน/คำแปล) ลดน้อยกว่า


def _script_counts(text: str) -> dict[str, int]:
    c = {"hangul": 0, "kana": 0, "han": 0, "thai": 0, "latin": 0}
    for ch in text:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            c["hangul"] += 1
        elif 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF:
            c["kana"] += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            c["han"] += 1
        elif 0x0E00 <= o <= 0x0E7F:
            c["thai"] += 1
        elif ch.isalpha() and o < 0x250:
            c["latin"] += 1
    return c


def lyrics_scripts(lyrics: Any) -> dict[str, float]:
    """สัดส่วนตัวอักษรแต่ละชนิดในเนื้อเพลง (รวมกัน = 1) · ไม่มีตัวอักษรเลย = ว่าง"""
    c = _script_counts("".join(w.text for ln in lyrics.lines for w in ln.words))
    n = sum(c.values())
    return {k: v / n for k, v in c.items()} if n else {}


def expected_script(meta: TrackMeta) -> str | None:
    """ภาษาที่น่าจะเป็นของเพลง ดูจากตัวอักษรในชื่อเพลง/ศิลปิน (None = บอกไม่ได้ เช่นชื่อเป็นอังกฤษล้วน)"""
    # ดูชื่อเพลงเป็นหลัก: ศิลปินเกาหลี/จีนร้องเพลงอังกฤษได้ ชื่อศิลปินจึงบอกภาษาของเพลงไม่ได้
    # (วัดกับ 2,830 เพลงที่รู้ว่าเนื้อถูก: ใช้ชื่อศิลปินด้วยเตือนผิด 2% ส่วนใหญ่เป็นแบบนี้)
    # ชื่อเพลงไม่มีตัวอักษรเฉพาะภาษาเลย ค่อยดูศิลปินเฉพาะกรณีที่ชื่อทุกส่วนเป็นอักษรละติน = ไม่ตัดสิน
    c = _script_counts(" ".join([meta.title, *meta.alt_titles]))
    if c["hangul"] >= 2:
        return "hangul"
    if c["kana"] >= 2:
        return "japanese"
    if c["thai"] >= 2:
        return "thai"
    if c["han"] >= 2:
        return "han"            # คันจิ/ฮั่นจื้อ: เป็นได้ทั้งจีนและญี่ปุ่น
    return None


def script_factor(lyrics: Any, meta: TrackMeta) -> tuple[float, str]:
    """-> (ตัวคูณคะแนน, เหตุผล) · 1.0 = ไม่มีปัญหาหรือตัดสินไม่ได้"""
    want = expected_script(meta)
    if want is None:
        return 1.0, ""
    fr = lyrics_scripts(lyrics)
    if not fr:
        return 1.0, ""
    hg, kn, han, th, lat = (fr.get(k, 0.0) for k in ("hangul", "kana", "han", "thai", "latin"))
    if want == "hangul":
        if hg >= 0.15:
            return 1.0, ""
        if max(kn + han, th) >= 0.4:
            return SCRIPT_MISMATCH_FACTOR, "เพลงเกาหลีแต่เนื้อเป็นจีน/ญี่ปุ่น/ไทย"
        return ROMANIZED_FACTOR, "เพลงเกาหลีแต่เนื้อไม่ใช่ฮันกึล"
    if want == "japanese":
        if kn >= 0.08:
            return 1.0, ""
        if hg >= 0.3 or th >= 0.4:
            return SCRIPT_MISMATCH_FACTOR, "เพลงญี่ปุ่นแต่เนื้อเป็นเกาหลี/ไทย"
        if han >= 0.4:
            return SCRIPT_MISMATCH_FACTOR, "เพลงญี่ปุ่นแต่เนื้อเป็นจีน (ไม่มีคานะ)"
        return ROMANIZED_FACTOR, "เพลงญี่ปุ่นแต่เนื้อไม่ใช่ญี่ปุ่น"
    if want == "thai":
        if th >= 0.2:
            return 1.0, ""
        if max(hg, kn + han) >= 0.4:
            return SCRIPT_MISMATCH_FACTOR, "เพลงไทยแต่เนื้อเป็นเกาหลี/จีน/ญี่ปุ่น"
        return ROMANIZED_FACTOR, "เพลงไทยแต่เนื้อไม่ใช่อักษรไทย"
    # want == "han": จีนหรือญี่ปุ่น — รับทั้งฮั่นจื้อและคานะ ปฏิเสธเกาหลี/ไทย
    if han + kn >= 0.3:
        return 1.0, ""
    if hg >= 0.3 or th >= 0.3:
        return SCRIPT_MISMATCH_FACTOR, "เพลงจีน/ญี่ปุ่นแต่เนื้อเป็นเกาหลี/ไทย"
    return ROMANIZED_FACTOR, "เพลงจีน/ญี่ปุ่นแต่เนื้อเป็นอักษรละติน"



def _is_cross_script(a: str, b: str) -> bool:
    """สองชื่อใช้ระบบอักษรหลักต่างกัน (เช่นละติน vs จีน/ฮันกึล) — เทียบความคล้ายตัวอักษรไม่ได้"""
    def dom(t: str) -> str:
        c = _script_counts(t)
        c = {k: v for k, v in c.items() if v}
        return max(c, key=lambda k: c[k]) if c else ""
    da, db = dom(a), dom(b)
    return bool(da and db and da != db)


def score_candidate(candidate: LyricsCandidate, meta: TrackMeta, duration: float | None) -> float:
    """เติม candidate.score และ candidate.score_detail แล้วคืนคะแนน"""
    detail: dict[str, float] = {}
    duration_factor = 1.0
    direct = candidate.lyrics.source in DIRECT_SOURCES

    # ชื่อ / ศิลปิน (แหล่งตรงกับวิดีโอไม่มีชื่อให้เทียบ = ถือว่าตรง)
    title_sim = 1.0 if direct else _best_similarity(candidate.matched_title, meta.title, meta.alt_titles)
    detail["title"] = WEIGHTS["title"] * title_sim
    # alt_titles คือชิ้นส่วนดิบของชื่อวิดีโอ (ไว้กันกรณีแยกลำดับศิลปิน/เพลงผิด) ซึ่งมีชื่อเพลงรวมอยู่ด้วย
    # ถ้าเอามาเทียบกับศิลปินของผู้สมัครทั้งหมด ชื่อเพลง 'EVERYTHING' จะกลายเป็นหลักฐานว่าวง 'Everything Everything' ตรง (0.85)
    # จึงตัดชิ้นส่วนที่ซ้ำกับชื่อเพลงออก เหลือเฉพาะชิ้นที่อาจเป็นชื่อศิลปินจริง
    nt = _norm(meta.title)
    alt_for_artist = tuple(a for a in meta.alt_titles if nt not in _norm(a))   # ชิ้นที่มีชื่อเพลงปนอยู่ ('ศิลปิน - เพลง') ก็ไม่ใช่ชื่อศิลปิน
    if not direct and _best_similarity(candidate.matched_title, meta.artist, alt_for_artist) >= 0.8:
        alt_for_artist = meta.alt_titles       # ชื่อเพลงของผู้สมัครตรงกับ 'ศิลปิน' ที่เดามา = ลำดับถูกสลับ ชิ้นส่วนทั้งหมดใช้เทียบได้
    artist_sim = 1.0 if direct else _best_similarity(candidate.matched_artist, meta.artist, alt_for_artist)
    detail["artist"] = WEIGHTS["artist"] * artist_sim

    # ความยาว
    want = duration or meta.duration
    got = candidate.matched_duration if candidate.matched_duration else candidate.lyrics.duration
    if direct:
        detail["duration"] = WEIGHTS["duration"]
    elif want and got:
        diff = abs(want - got)
        detail["duration_diff_s"] = diff
        # ชื่อ+ศิลปินตรงกันชัดเจน = เพลงเดียวกันแน่ ความยาวต่างมากเพราะวิดีโอตัดสั้น/มีฉากเปิด/คนละฉบับตัดต่อ
        # ห้ามปฏิเสธ (เคสจริง 2026-10-26: EVERYTHING ของ The Black Skirts ยาว 293 วิ แต่วิดีโอยาว 202 วิ ต่าง 91 วิ
        # ถูกปฏิเสธทั้งที่เป็นเพลงเดียวกัน แล้วระบบไปแสดงเนื้อคนละเพลงแทน) · ให้ถ่วงคะแนนลง แล้วเสียง (CTC) เป็นคนตัดสิน
        artist_known_same = artist_sim >= 0.85 or (
            bool(meta.artist and candidate.matched_artist) and _is_cross_script(meta.artist, candidate.matched_artist))
        strong_same = title_sim >= 0.9 and artist_known_same and diff <= min(150.0, want * 0.6)
        if diff > REJECT_DURATION_DIFF_S and diff > want * REJECT_DURATION_RATIO and not strong_same:
            candidate.score = 0.0
            detail["rejected_duration"] = diff
            candidate.score_detail = detail
            return 0.0
        if diff <= MAX_DURATION_DIFF_S:
            detail["duration"] = WEIGHTS["duration"]
        elif diff <= SOFT_DURATION_DIFF_S:
            span = SOFT_DURATION_DIFF_S - MAX_DURATION_DIFF_S
            detail["duration"] = WEIGHTS["duration"] * (1.0 - (diff - MAX_DURATION_DIFF_S) / span) * 0.6
        else:
            detail["duration"] = 0.0
            # ชื่อเพลง+ศิลปินตรงกันชัดเจน = เพลงเดียวกันแน่ ความยาวต่างเพราะ MV มีฉากเปิดเรื่อง -> โทษน้อยกว่า
            floor = STRONG_MATCH_FLOOR if (title_sim >= 0.85 and artist_sim >= 0.7) else SOFT_PENALTY_FLOOR
            duration_factor = max(floor, 1.0 - (diff - SOFT_DURATION_DIFF_S) * SOFT_PENALTY_PER_S)
    else:
        detail["duration"] = WEIGHTS["duration"] * 0.5  # ไม่รู้ความยาว

    # ระดับเวลา
    detail["timing"] = WEIGHTS["timing"] * candidate.lyrics.timing.rank / 2.0

    # version (live/remix/...) ต้องตรงกัน
    cand_tags = frozenset() if direct else _candidate_tags(candidate)
    detail["version"] = WEIGHTS["version"] if cand_tags == meta.version_tags or direct else 0.0

    total = sum(v for k, v in detail.items() if k != "duration_diff_s")
    total *= duration_factor
    if detail["version"] == 0.0:
        total *= VERSION_MISMATCH_FACTOR
    if not direct and meta.artist and candidate.matched_artist:
        if _is_cross_script(meta.artist, candidate.matched_artist) and artist_sim < ARTIST_GATE:
            # เทียบไม่ได้ว่าคนเดียวกันไหม: ความยาวใกล้เคียงมากถึงจะเชื่อ ไม่งั้นลดคะแนนลงเล็กน้อยให้ฉบับที่ยืนยันศิลปินได้มาก่อน
            near = bool(want and got and abs(want - got) <= CROSS_SCRIPT_SAFE_DIFF_S)
            if not near:
                total *= CROSS_SCRIPT_ARTIST_FACTOR
                detail["artist_cross_script"] = CROSS_SCRIPT_ARTIST_FACTOR
            else:
                detail["artist"] = max(detail["artist"], WEIGHTS["artist"] * 0.6)   # ไม่ให้เสียคะแนนศิลปินเพราะเขียนคนละอักษร
        elif artist_sim < ARTIST_GATE:
            total *= ARTIST_MISMATCH_FACTOR
            detail["artist_gate"] = artist_sim / ARTIST_GATE
    if title_sim < TITLE_GATE:
        # ชื่อไม่ใกล้เคียง = ไม่ใช่เพลงนี้ แม้ความยาว/เวลาจะดีก็ไม่ควรผ่านเกณฑ์ (กันได้คะแนนฟรีจากข้ออื่น)
        # คูณทบสองครั้ง: ศิลปินตรง+ความยาวตรงให้คะแนนรวมสูงมาก (ชื่อเพลงต่างแต่ศิลปินเดียวกันเคยได้ 42.6 ผ่านเกณฑ์)
        total *= (title_sim / TITLE_GATE) ** 2
        detail["title_gate"] = title_sim / TITLE_GATE
    if not direct:    # แหล่งตรง (คำบรรยายของวิดีโอนั้นเอง) เป็นภาษาเดียวกับเสียงอยู่แล้ว
        sf, why = script_factor(candidate.lyrics, meta)
        if sf < 1.0:
            total *= sf
            detail["script_mismatch"] = sf
    if direct:
        total += DIRECT_SOURCE_BONUS
        detail["direct_bonus"] = DIRECT_SOURCE_BONUS
    total = max(0.0, min(100.0, total))
    candidate.score = total
    candidate.score_detail = detail
    return total


# ---------------------------------------------------------------------------
# ฉันทามติระหว่างแหล่ง (ผู้ใช้สั่ง 2026-10-21): เอาเนื้อเพลงของทุกแหล่งมาเทียบกัน อันที่ตรงกับแหล่งอื่นมากที่สุดคือฉบับที่น่าเชื่อถือที่สุด
# ---------------------------------------------------------------------------
CONSENSUS_WEIGHT = 25.0        # โบนัสสูงสุดที่ได้จากการตรงกับแหล่งอื่น (เพิ่มจากคะแนนปกติ)
CONSENSUS_VOTER_MIN = 30.0     # แหล่งที่มีคะแนนต่ำกว่านี้ไม่มีสิทธิ์โหวต (น่าจะคนละเพลง)
CONSENSUS_LINE_RATIO = 82      # บรรทัดสองฉบับนับว่า "ตรงกัน" เมื่อคล้ายกันเกินนี้ (rapidfuzz ratio)


def _line_keys(candidate: LyricsCandidate) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for ln in candidate.lyrics.lines:
        k = _norm("".join(w.text for w in ln.words))
        if len(k) >= 3 and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def _agreement(a: list[str], b: list[str]) -> float:
    """สัดส่วนบรรทัดของ a ที่มีบรรทัดตรงกันใน b (0-1)"""
    if not a or not b:
        return 0.0
    bset = set(b)
    hit = 0
    for x in a:
        if x in bset or any(fuzz.ratio(x, y) >= CONSENSUS_LINE_RATIO for y in b):
            hit += 1
    return hit / len(a)


def apply_consensus(candidates: list[LyricsCandidate]) -> None:
    """เติมโบนัสฉันทามติลง candidate.score (เรียกซ้ำได้ ไม่บวกซ้ำ: เก็บคะแนนเดิมไว้ใน score_detail["base"])
    ผู้โหวต = ผลที่คะแนนปกติ ≥ CONSENSUS_VOTER_MIN และมี ≥ 4 บรรทัด · ความเห็นถ่วงน้ำหนักด้วยคะแนนของผู้โหวต
    ไม่มีผู้โหวตอื่นเลย = ไม่มีโบนัส (ไม่ลงโทษผลเดี่ยว)"""
    keys = {id(c): _line_keys(c) for c in candidates}
    for c in candidates:
        c.score_detail.setdefault("base", c.score)
    voters = [c for c in candidates if c.score_detail["base"] >= CONSENSUS_VOTER_MIN and len(keys[id(c)]) >= 4]
    for c in candidates:
        base = c.score_detail["base"]
        ka = keys[id(c)]
        if base <= 0 or len(ka) < 4:
            c.score = base
            continue
        num = den = 0.0
        for v in voters:
            if v is c:
                continue
            kb = keys[id(v)]
            sym = (_agreement(ka, kb) + _agreement(kb, ka)) / 2.0
            w = max(0.2, v.score_detail["base"] / 100.0)
            num += sym * w
            den += w
        consensus = num / den if den else 0.0
        c.score_detail["consensus"] = round(consensus, 3)
        c.score = base + CONSENSUS_WEIGHT * consensus if den else base
