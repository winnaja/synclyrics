"""จับคู่เนื้อเพลงกับ "คำที่ AI ฟังได้" (transcript จาก Whisper) เพื่อหาเวลาจริงของทุกบรรทัด/ทุกคำ

ไม่พึ่ง torch/numpy — ทดสอบได้ตรงๆ และใช้ได้ทั้งใน worker และ process หลัก

หลักคิด (เนื้อเพลงสำเร็จรูป = ข้อความที่ถูกต้อง, เสียงจริง = เวลาที่ถูกต้อง):
  1. แตกเนื้อเพลงและ transcript เป็นสตรีมตัวอักษรที่ normalize แล้ว (ไม่สนช่องว่าง/วรรคตอน/ตัวพิมพ์ — ภาษาไทย/ญี่ปุ่น/จีน
     ไม่มีช่องว่างคั่นคำ จึงจับคู่ระดับตัวอักษรเหมือนกันทุกภาษา)
  2. difflib.SequenceMatcher หาช่วงที่ตรงกัน (เรียงตามลำดับเสมอ ไม่ไขว้) — ทน Whisper ฟังผิดบางคำ/ข้ามบางช่วง
  3. ตัวอักษรที่จับคู่ได้ ได้เวลาจากคำที่ Whisper ฟัง (ตัวอักษรในคำกระจายเท่าๆ กันตลอดความยาวคำ)
  4. บรรทัดที่จับคู่ได้พอ = "resolved" เวลาตามเสียงจริง · บรรทัดที่เหลือ = ใช้เวลาต้นฉบับ (ถ้ามี) ที่ยืด/เลื่อนตามจุดยึดข้างเคียง
     ถ้าต้นฉบับไม่มีเวลาเลย กระจายตามจำนวนตัวอักษรในช่องว่างระหว่างจุดยึด
ผลคือแก้ได้ทั้งเวลาเลื่อนทั้งเพลง (MV มีฉากเปิดเรื่อง) และโครงสร้างต่างจากต้นฉบับ (รีมิกซ์) โดยไม่เชื่อเวลาต้นฉบับเกินจำเป็น
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import median

# เวลาต่อตัวอักษรเมื่อต้องเดา (วินาที) — ใช้ขยายหัว/ท้ายบรรทัดที่จับคู่ได้ไม่ครบ และกระจายบรรทัดที่ไม่มีเวลาเลย
DEFAULT_CHAR_S = 0.11
MAX_CHAR_S = 0.30
MIN_BLOCK = 3            # ช่วงที่ตรงกันสั้นกว่านี้ถือเป็นบังเอิญ (ตัวอักษรซ้ำๆ)
RESOLVE_RATIO = 0.4      # บรรทัดที่จับคู่ได้ ≥ สัดส่วนนี้ของตัวอักษร = resolved
MIN_WORD_S = 0.04
MAX_SCAN_CHARS = 9000    # SequenceMatcher เป็น O(n²) — เกินนี้ตัดทิ้งท้าย (เพลงจริงไม่ถึง)


@dataclass(slots=True)
class TWord:
    """คำที่ AI ฟังได้ (เวลาสัมบูรณ์ของเพลง)"""

    text: str
    start: float
    end: float
    prob: float = 1.0


@dataclass(slots=True)
class InLine:
    """บรรทัดเนื้อเพลงขาเข้า: ข้อความของแต่ละคำ + เวลาต้นฉบับ (None = ไม่มี)"""

    words: list[str]
    start: float | None = None
    end: float | None = None
    word_times: list[tuple[float, float]] | None = None   # เวลาต้นฉบับรายคำ (ถ้ามี) ใช้ยืด/เลื่อนตามบรรทัดที่ไม่ resolved
    word_probs: list[float] | None = None                 # ความมั่นใจของ Whisper รายคำ (เฉพาะบรรทัดที่สร้างจาก transcript)


@dataclass(slots=True)
class OutLine:
    start: float
    end: float
    words: list[tuple[float, float, float]]   # (start, end, confidence)
    resolved: bool                             # True = เวลามาจากเสียงจริงของบรรทัดนี้เอง
    quality: float                             # สัดส่วนตัวอักษรที่จับคู่ได้ 0-1


@dataclass(slots=True)
class MatchResult:
    lines: list[OutLine]
    coverage: float                            # ตัวอักษรเนื้อเพลงที่จับคู่ได้ทั้งหมด / ทั้งหมด (ต่ำ = เนื้อเพลงอาจเป็นคนละเวอร์ชัน)
    offset_s: float | None = None              # ค่ามัธยฐานของ (เวลาจริง − เวลาต้นฉบับ) ของบรรทัด resolved
    scale: float | None = None                 # อัตราส่วนความยาว (เวลาจริง/ต้นฉบับ) คร่าวๆ จากบรรทัดแรก-สุดท้ายที่ resolved
    notes: list[str] = field(default_factory=list)


def _has_cjk(text: str) -> bool:
    return any("一" <= c <= "鿿" for c in text)


def _to_simplified(text: str) -> str:
    """จีนตัวเต็ม -> ตัวย่อ (Whisper ตอบตัวเต็ม/ตัวย่อสลับกันตามอำเภอใจ แต่เนื้อเพลงอาจเป็นอีกแบบ) · ไม่มี zhconv = ไม่แปลง (ไม่พัง)"""
    try:
        from zhconv import convert

        return convert(text, "zh-cn")
    except Exception:  # noqa: BLE001
        return text


def norm_chars(text: str) -> str:
    """เก็บเฉพาะตัวอักษร/ตัวเลข/เครื่องหมายประกอบ (สระ-วรรณยุกต์ไทย) แปลงเป็นตัวพิมพ์เล็กแบบ NFKC · จีนแปลงเป็นตัวย่อก่อน"""
    if _has_cjk(text):
        text = _to_simplified(text)
    out = []
    for c in unicodedata.normalize("NFKC", text).casefold():
        if unicodedata.category(c)[0] in "LNM":
            out.append(c)
    return "".join(out)


def _transcript_stream(words: list[TWord]) -> tuple[str, list[tuple[float, float]], list[float]]:
    chars: list[str] = []
    times: list[tuple[float, float]] = []
    probs: list[float] = []
    for w in words:
        t = norm_chars(w.text)
        n = len(t)
        if n == 0:
            continue
        dur = max(w.end - w.start, MIN_WORD_S)
        for k, c in enumerate(t):
            chars.append(c)
            times.append((w.start + dur * k / n, w.start + dur * (k + 1) / n))
            probs.append(w.prob)
    return "".join(chars), times, probs


def ctc_to_result(glob: list[list[tuple[float, float, float]] | None], lines: list[InLine], tol_s: float = 1.5, min_frac: float = 0.7,
                  min_lines: int = 4) -> MatchResult | None:
    """ผล CTC แบบทั้งเพลง (align_global: เสียงร้อง + ข้อความเนื้อเพลง ไม่พึ่ง Whisper) -> MatchResult ถ้า "เชื่อถือได้"
    ตรวจด้วยเวลาเดิมของเนื้อเพลง: ส่วนต่าง (CTC − เว็บ) ของบรรทัดส่วนใหญ่ต้องใกล้ค่ากลาง (เว็บมักเลื่อนทั้งเพลงคงที่) — ถ้าโครงสร้างเพลงต่าง/เนื้อผิด
    ผลจะกระจายมั่ว → คืน None (ให้ใช้เส้นทาง Whisper แทน) · บรรทัดที่ไม่ผ่าน = เวลาเว็บ + ค่ากลาง (resolved=False)"""
    timed = [i for i, ln in enumerate(lines) if ln.start is not None and i < len(glob) and glob[i]]
    if len(timed) < max(min_lines, int(0.6 * len(lines))):
        return None
    deltas = {i: float(glob[i][0][0]) - float(lines[i].start) for i in timed}   # type: ignore[index,arg-type]
    ordered = sorted(deltas.values())
    med = ordered[len(ordered) // 2]
    ok = {i for i, d in deltas.items() if abs(d - med) <= tol_s}
    if len(ok) / len(timed) < min_frac:
        return None
    out: list[OutLine] = []
    for i, ln in enumerate(lines):
        g = glob[i] if i < len(glob) else None
        if g and i in ok:
            conf = float(sum(c for _s, _e, c in g) / len(g))
            out.append(OutLine(float(g[0][0]), float(g[-1][1]), list(g), True, conf))
            continue
        if ln.start is None or not ln.words:
            out.append(OutLine(0.0, 0.0, [], False, 0.0))
            continue
        end = float(ln.end if ln.end is not None else ln.start + 3.0)
        words = _spread(ln, float(ln.start) + med, end + med)
        out.append(OutLine(words[0][0], words[-1][1], words, False, 0.0))
    return MatchResult(lines=out, coverage=len(ok) / max(1, len(lines)), offset_s=float(med), scale=None, notes=["ctc_global"])


def match_lines(lines: list[InLine], transcript: list[TWord], min_block: int = MIN_BLOCK) -> MatchResult:
    """จับคู่เนื้อเพลงทั้งชุดกับ transcript คืนเวลาของทุกบรรทัด (บรรทัดละ 1 ผล ตามลำดับเดิม)"""
    # ---- สตรีมเนื้อเพลง ----
    lchars: list[str] = []
    lmap: list[tuple[int, int]] = []          # (บรรทัด, คำ) ของแต่ละตัวอักษร
    for li, ln in enumerate(lines):
        for wi, w in enumerate(ln.words):
            for c in norm_chars(w):
                lchars.append(c)
                lmap.append((li, wi))
    lyric_s = "".join(lchars)
    trans_s, ttimes, tprobs = _transcript_stream(transcript)
    total = len(lyric_s)

    ctime: list[tuple[float, float] | None] = [None] * total
    if total and trans_s:
        sm = SequenceMatcher(None, lyric_s[:MAX_SCAN_CHARS], trans_s[:MAX_SCAN_CHARS], autojunk=False)
        for i, j, n in sm.get_matching_blocks():
            if n < min_block:
                continue
            for k in range(n):
                ctime[i + k] = ttimes[j + k]

    # ---- ต่อบรรทัด ----
    per_line: list[list[int]] = [[] for _ in lines]      # ดัชนีตัวอักษรของแต่ละบรรทัด
    for idx, (li, _wi) in enumerate(lmap):
        per_line[li].append(idx)

    results: list[OutLine | None] = [None] * len(lines)
    matched_total = 0
    for li, idxs in enumerate(per_line):
        if not idxs:
            continue
        hit = _dominant_cluster([k for k in idxs if ctime[k] is not None], ctime)
        for k in idxs:       # ตัวอักษรที่จับคู่ไปติดกับเสียงอีกช่วงหนึ่ง (บังเอิญตรงกับท่อนซ้ำ) ไม่นับเป็นของบรรทัดนี้
            if ctime[k] is not None and k not in hit:
                ctime[k] = None
        matched_total += len(hit)
        quality = len(hit) / len(idxs)
        if len(hit) >= 2 and quality >= RESOLVE_RATIO:
            results[li] = _resolve_line(lines[li], idxs, ctime, lmap, quality)

    notes: list[str] = []
    _reject_outliers(lines, results)
    resolved_idx = [i for i, r in enumerate(results) if r is not None]
    _fill_unresolved(lines, results, resolved_idx, notes)

    coverage = matched_total / total if total else 0.0
    offs = [results[i].start - lines[i].start for i in resolved_idx if lines[i].start is not None]  # type: ignore[union-attr]
    offset = float(median(offs)) if offs else None
    scale = None
    srcs = [i for i in resolved_idx if lines[i].start is not None]
    if len(srcs) >= 2:
        a, b = srcs[0], srcs[-1]
        d_src = lines[b].start - lines[a].start  # type: ignore[operator]
        if d_src > 10:
            scale = (results[b].start - results[a].start) / d_src  # type: ignore[union-attr]
    final = [r if r is not None else OutLine(0.0, 0.0, [], False, 0.0) for r in results]
    return MatchResult(lines=final, coverage=coverage, offset_s=offset, scale=scale, notes=notes)


MAX_CLUSTER_GAP_S = 3.5   # ตัวอักษรของบรรทัดเดียวกันที่จับคู่ได้ ห่างกันเกินนี้ = ติดกับเสียงคนละช่วง


def _dominant_cluster(hit: list[int], ctime: list[tuple[float, float] | None]) -> list[int]:
    """ตัวอักษรที่จับคู่ได้ของบรรทัดหนึ่ง อาจกระจายไปหลายช่วงเสียง (เช่นคำซ้ำในฮุกคนละท่อน) — เก็บเฉพาะกลุ่มที่อยู่ใกล้กันและมากที่สุด"""
    if len(hit) <= 1:
        return hit
    clusters: list[list[int]] = [[hit[0]]]
    for a, b in zip(hit, hit[1:]):
        if ctime[b][0] - ctime[a][1] > MAX_CLUSTER_GAP_S:  # type: ignore[index]
            clusters.append([])
        clusters[-1].append(b)
    return max(clusters, key=len)


OUTLIER_S = 6.0      # เวลาที่จับคู่ได้ ต่างจาก "แนวโน้มของบรรทัดข้างเคียงที่ตรงกันเอง" เกินนี้ = จับคู่ผิด (เช่นไปติดกับฮุกอีกรอบ)
NEIGHBOR_AGREE_S = 3.0


def _reject_outliers(lines: list[InLine], results: list[OutLine | None]) -> None:
    """บรรทัดที่เลื่อนจากเวลาต้นฉบับผิดแปลกจากบรรทัดที่ resolved ทั้งสองข้าง (ซึ่งเลื่อนเท่าๆ กัน) = จับคู่ผิด ปล่อยให้ประมาณจากจุดยึดแทน
    ไม่กระทบกรณีโครงสร้างเปลี่ยนจริง (เช่น MV มีฉากแทรก): ตรงนั้นสองข้างเลื่อนต่างกัน จึงไม่ถือว่าเห็นตรงกัน"""
    idx = [i for i, r in enumerate(results) if r is not None and lines[i].start is not None]
    dev = {i: results[i].start - float(lines[i].start) for i in idx}  # type: ignore[union-attr, arg-type]
    for k in range(1, len(idx) - 1):
        a, i, b = idx[k - 1], idx[k], idx[k + 1]
        if abs(dev[a] - dev[b]) < NEIGHBOR_AGREE_S and abs(dev[i] - (dev[a] + dev[b]) / 2) > OUTLIER_S:
            results[i] = None


def _resolve_line(line: InLine, idxs: list[int], ctime: list[tuple[float, float] | None],
                  lmap: list[tuple[int, int]], quality: float) -> OutLine:
    """บรรทัดที่จับคู่ได้พอ: ทุกตัวอักษรได้เวลา (ตัวที่จับคู่ไม่ได้ interpolate ในบรรทัด) แล้วรวมเป็นเวลาของคำ"""
    first, last = idxs[0], idxs[-1]
    known = [k for k in idxs if ctime[k] is not None]
    # วินาทีต่อตัวอักษรของบรรทัดนี้ (ไว้ขยายหัว/ท้าย) — จากช่วงที่จับคู่ได้ ไม่เกินเพดาน
    span = ctime[known[-1]][1] - ctime[known[0]][0]  # type: ignore[index]
    per = max(0.03, min(MAX_CHAR_S, span / max(1, known[-1] - known[0] + 1))) if known[-1] > known[0] else DEFAULT_CHAR_S
    starts: dict[int, float] = {}
    ends: dict[int, float] = {}
    for k in known:
        starts[k], ends[k] = ctime[k]  # type: ignore[misc]
    # หัว/ท้ายที่จับคู่ไม่ได้ ขยายออกด้วย per
    for k in range(known[0] - 1, first - 1, -1):
        ends[k] = starts[k + 1]
        starts[k] = ends[k] - per
    for k in range(known[-1] + 1, last + 1):
        starts[k] = ends[k - 1]
        ends[k] = starts[k] + per
    # ช่องกลางที่จับคู่ไม่ได้ interpolate ระหว่างตัวที่รู้เวลาสองข้าง
    for a, b in zip(known, known[1:]):
        gap = b - a - 1
        if gap <= 0:
            continue
        t0, t1 = ends[a], starts[b]
        step = (t1 - t0) / gap if t1 > t0 else 0.0
        step = min(step, MAX_CHAR_S)
        for n in range(gap):
            starts[a + 1 + n] = t0 + step * n
            ends[a + 1 + n] = t0 + step * (n + 1)
    # รวมเป็นคำ
    by_word: dict[int, list[int]] = {}
    for k in idxs:
        by_word.setdefault(lmap[k][1], []).append(k)
    words: list[tuple[float, float, float]] = []
    prev_end = -1e9
    for wi in range(len(line.words)):
        ks = by_word.get(wi)
        if not ks:  # คำที่ไม่มีตัวอักษรเลย (เช่นเครื่องหมายล้วน) — ให้อยู่ท้ายคำก่อนหน้า
            t = prev_end if prev_end > -1e8 else starts[first]
            words.append((t, t, 0.2))
            continue
        s, e = starts[ks[0]], ends[ks[-1]]
        s = max(s, prev_end) if prev_end > -1e8 else s
        e = max(e, s + MIN_WORD_S)
        conf = max(0.3, sum(1 for k in ks if ctime[k] is not None) / len(ks))
        words.append((s, e, conf))
        prev_end = e
    return OutLine(words[0][0], words[-1][1], words, True, quality)


def _fill_unresolved(lines: list[InLine], results: list[OutLine | None], resolved: list[int], notes: list[str]) -> None:
    """บรรทัดที่ไม่ resolved: ยืด/เลื่อนเวลาต้นฉบับตามบรรทัด resolved ที่ใกล้ที่สุดสองข้าง (หรือกระจายตามตัวอักษรถ้าไม่มีเวลาเลย)"""
    n = len(lines)
    if not resolved:
        notes.append("no_anchor")
        return
    for i in range(n):
        if results[i] is not None:
            continue
        prev = max((r for r in resolved if r < i), default=None)
        nxt = min((r for r in resolved if r > i), default=None)
        results[i] = _estimate_line(lines, results, i, prev, nxt)


def _line_chars(line: InLine) -> int:
    return max(1, sum(len(norm_chars(w)) for w in line.words))


def _estimate_line(lines: list[InLine], results: list[OutLine | None], i: int, prev: int | None, nxt: int | None) -> OutLine:
    ln = lines[i]
    if not ln.words:  # บรรทัดว่าง (ไม่มีคำ) — เก็บตำแหน่งไว้เฉยๆ
        t = float(ln.start) if ln.start is not None else (results[prev].end if prev is not None else 0.0)  # type: ignore[union-attr]
        return OutLine(t, t, [], False, 0.0)
    has_src = ln.start is not None
    pts: list[tuple[float, float]] = []   # (เวลาต้นฉบับ, เวลาใหม่) ของจุดยึด
    for j in (prev, nxt):
        if j is not None and lines[j].start is not None:
            pts.append((float(lines[j].start), float(results[j].start)))  # type: ignore[arg-type, union-attr]
    if has_src and pts:
        if len(pts) == 2 and pts[1][0] - pts[0][0] > 1e-6:
            k = (pts[1][1] - pts[0][1]) / (pts[1][0] - pts[0][0])
            k = max(0.7, min(1.4, k))
            ref_src, ref_new = pts[0]
        else:
            k, (ref_src, ref_new) = 1.0, pts[0]

        def conv(t: float) -> float:
            return ref_new + (t - ref_src) * k

        s0 = conv(float(ln.start))  # type: ignore[arg-type]
        if ln.word_times and len(ln.word_times) == len(ln.words):
            words = [(conv(a), max(conv(b), conv(a) + MIN_WORD_S), 0.25) for a, b in ln.word_times]
        else:
            e0 = conv(float(ln.end if ln.end is not None else ln.start + DEFAULT_CHAR_S * _line_chars(ln)))  # type: ignore[operator]
            words = _spread(ln, s0, max(e0, s0 + MIN_WORD_S))
        return OutLine(words[0][0], words[-1][1], words, False, 0.0)
    # ไม่มีเวลาต้นฉบับ: กระจายตามตัวอักษรหลังบรรทัดที่ resolved ก่อนหน้า (หรือก่อนบรรทัดถัดไป)
    chars = _line_chars(ln)
    dur = min(chars * DEFAULT_CHAR_S, 8.0)
    if prev is not None:
        s0 = results[prev].end + 0.2  # type: ignore[union-attr]
    elif nxt is not None:
        s0 = results[nxt].start - dur - 0.2  # type: ignore[union-attr]
    else:
        s0 = 0.0
    if nxt is not None:
        room = results[nxt].start - s0 - 0.1  # type: ignore[union-attr]
        if room > 0.3:
            dur = min(dur, room)
    words = _spread(ln, s0, s0 + dur)
    return OutLine(words[0][0], words[-1][1], words, False, 0.0)


def _spread(line: InLine, start: float, end: float) -> list[tuple[float, float, float]]:
    """กระจายเวลาให้คำตามจำนวนตัวอักษร"""
    weights = [max(1, len(norm_chars(w))) for w in line.words] or [1]
    tot = sum(weights)
    out: list[tuple[float, float, float]] = []
    t = start
    for w in weights:
        d = (end - start) * w / tot
        out.append((t, t + d, 0.25))
        t += d
    return out


def group_words_into_lines(words: list[TWord], max_gap_s: float = 0.7, max_chars: int = 44, max_words: int = 9) -> list[InLine]:
    """transcript ล้วน -> บรรทัดเนื้อเพลง (ใช้เมื่อไม่เจอเนื้อเพลงที่ไหนเลย หรือโครงสร้างต่างจากเนื้อเพลงสำเร็จรูป)
    ตัดบรรทัดเมื่อ: เว้นนาน · จบประโยค (. ? ! ที่ Whisper ใส่) · ลูกน้ำเมื่อบรรทัดยาวพอ · ยาวเกิน"""
    lines: list[InLine] = []
    cur: list[TWord] = []
    chars = 0

    def flush() -> None:
        nonlocal cur, chars
        if cur:
            lines.append(InLine(words=[w.text for w in cur], start=cur[0].start, end=cur[-1].end,
                                word_times=[(w.start, w.end) for w in cur], word_probs=[w.prob for w in cur]))
        cur, chars = [], 0

    for w in sorted(words, key=lambda x: x.start):
        if cur and (w.start - cur[-1].end > max_gap_s or chars + len(w.text) > max_chars or len(cur) >= max_words):
            flush()
        cur.append(w)
        chars += len(w.text)
        t = w.text.rstrip()
        if t.endswith((".", "?", "!", "。", "？", "！")) or (t.endswith((",", "，", "、")) and len(cur) >= 4):
            flush()
    flush()
    return lines


# ---------------------------------------------------------------------------
# เพลงที่โครงสร้างต่างจากเนื้อเพลงสำเร็จรูป (รีมิกซ์: สลับท่อน/ซ้ำฮุกต่างจำนวน/มีท่อนแร็ปเพิ่ม)
# ---------------------------------------------------------------------------
def clean_transcript(words: list[TWord], max_run: int = 3) -> list[TWord]:
    """ตัดคำที่ Whisper มั่วตอนไม่มีเสียงร้อง: คำเดิมซ้ำติดกันเกิน max_run ("yeah yeah ..." วนเป็นร้อยคำ) และ "คำ" ยาวผิดปกติ"""
    out: list[TWord] = []
    prev, run = None, 0
    for w in words:
        k = norm_chars(w.text)
        if not k or len(k) > 25:
            continue
        run = run + 1 if k == prev else 1
        prev = k
        if run <= max_run:
            out.append(w)
    return out


@dataclass(slots=True)
class ReLine:
    """บรรทัดที่สร้างใหม่ตามลำดับที่ร้องจริง (รีมิกซ์) — src = ดัชนีบรรทัดเนื้อเพลงที่ใช้ข้อความ (None = ข้อความจากที่ AI ฟังได้)"""

    start: float
    end: float
    words: list[tuple[float, float, float]]
    text_words: list[str]
    src: list[int] | None


@dataclass(slots=True)
class ReResult:
    lines: list[ReLine]
    coverage: float          # สัดส่วนตัวอักษรใน transcript ที่ไปตรงกับข้อความเนื้อเพลง (ไม่สนลำดับ)


def _best_lyric_span(text: str, lyric_norm: list[str], max_span: int = 3) -> tuple[float, int, int]:
    """บรรทัดที่ AI ฟังได้ ตรงกับเนื้อเพลงบรรทัดไหน (หรือบรรทัดติดกัน 2-3 บรรทัด) มากสุด คืน (ความคล้าย, เริ่ม, จบ ไม่รวม)"""
    best = (0.0, 0, 0)
    n = len(lyric_norm)
    for i in range(n):
        joined = ""
        for j in range(i, min(n, i + max_span)):
            joined += lyric_norm[j]
            if not joined:
                continue
            sm = SequenceMatcher(None, joined, text, autojunk=False)
            if sm.real_quick_ratio() < best[0] or sm.quick_ratio() < best[0]:
                continue
            r = sm.ratio()
            if r > best[0]:
                best = (r, i, j + 1)
    return best


NOSPACE_LANGS = frozenset({"th", "ja", "zh", "yue", "lo", "km", "my"})   # ภาษาที่เขียนไม่เว้นวรรคระหว่างคำ (Whisper ให้ "คำ" เป็นชิ้นย่อยๆ)


def _plausible_ai_line(words: list[str], probs: list[float], min_prob: float = 0.55) -> bool:
    """บรรทัดที่ AI ฟังได้เองน่าเชื่อถือพอจะแสดงไหม: มั่นใจเฉลี่ยพอ · ไม่ใช่คำเดิมวนๆ (เช่น "中 原 中 原 中")"""
    if not words or sum(probs) / max(1, len(probs)) < min_prob:
        return False
    toks = [norm_chars(w) for w in words if norm_chars(w)]
    return len(toks) < 4 or len(set(toks)) >= max(2, len(toks) // 3)


def reconstruct_by_transcript(lines: list[InLine], transcript: list[TWord], min_ratio: float = 0.62, nospace: bool = False,
                              web_only: bool = False) -> ReResult:
    """web_only=True: ใช้เฉพาะข้อความเนื้อเพลงเว็บ (บรรทัดที่ AI ฟังได้แต่ไม่ตรงเนื้อเพลงถูกทิ้ง — ผู้ใช้สั่งให้ยึดเว็บเป็นหลัก)
    สร้างบรรทัดตามลำดับ "ที่ร้องจริง" จาก transcript แล้วแทนข้อความด้วยบรรทัดเนื้อเพลงที่ตรงที่สุด (สะกดถูก) ถ้าคล้ายพอ
    ใช้เมื่อโครงสร้างเพลงต่างจากเนื้อเพลง (จับคู่แบบเรียงลำดับไม่ได้) — เวลาถูกต้องเสมอเพราะมาจากเสียง"""
    clean = clean_transcript(transcript)
    tlines = group_words_into_lines(clean, max_words=30 if nospace else 9, max_chars=36 if nospace else 44)
    lyric_norm = [norm_chars("".join(ln.words)) for ln in lines]
    out: list[ReLine] = []
    covered = total = 0
    for tl in tlines:
        tnorm = norm_chars("".join(tl.words))
        total += len(tnorm)
        wt = tl.word_times or []
        probs = tl.word_probs or [0.7] * len(wt)
        ai_words = [(a, b, p) for (a, b), p in zip(wt, probs)]
        ai_line = ReLine(tl.start, tl.end, ai_words, list(tl.words), None)
        if len(tnorm) < 3 or not lines:
            if not web_only and _plausible_ai_line(tl.words, probs):
                out.append(ai_line)
            continue
        ratio, i, j = _best_lyric_span(tnorm, lyric_norm)
        if ratio < min_ratio:
            if not web_only and _plausible_ai_line(tl.words, probs):   # ข้อความที่ AI ฟังได้แต่ไม่ตรงเนื้อเพลง: แสดงเฉพาะที่น่าเชื่อถือ (ไม่ใช่เสียงรบกวน/คำมั่ว)
                out.append(ai_line)
            continue
        covered += len(tnorm)
        twords = [TWord(w, a, b) for w, (a, b) in zip(tl.words, wt)]
        if j - i > 1:
            # ช่วงที่ฟังได้ครอบหลายบรรทัดเนื้อเพลง: แยกกลับเป็นบรรทัดเนื้อเพลงเดิมทีละบรรทัด (คงรูปแบบบรรทัดของเนื้อเพลง) ถ้าทุกบรรทัดหาเวลาจากเสียงได้
            sub = match_lines([InLine(words=lines[k].words) for k in range(i, j)], twords)
            if all(ol.resolved and ol.words for ol in sub.lines):
                for k, ol in zip(range(i, j), sub.lines):
                    out.append(ReLine(ol.words[0][0], ol.words[-1][1], [(a, b, c) for a, b, c in ol.words], list(lines[k].words), [k]))
                continue
        lyric_words = [w for k in range(i, j) for w in lines[k].words]
        sub = match_lines([InLine(words=lyric_words)], twords)
        ol = sub.lines[0]
        if ol.resolved:
            words = ol.words
        else:  # จับคู่ระดับตัวอักษรไม่ได้ในบรรทัดเดียว: กระจายตามช่วงเวลาของบรรทัดที่ฟังได้
            words = _spread(InLine(words=lyric_words), tl.start, tl.end)
        out.append(ReLine(words[0][0], words[-1][1], [(a, b, c) for a, b, c in words], lyric_words, list(range(i, j))))
    out = tidy_lines(out)   # เรียงตามเวลา + ตัดบรรทัดซ้ำ/เวลาทับ (UI หาบรรทัดปัจจุบันด้วยการค้นหาแบบแบ่งครึ่ง)
    return ReResult(lines=out, coverage=covered / total if total else 0.0)

# คำร้องประกอบ/ad-lib/คอรัสคำเดียวที่แสดงเป็นแถวเสียงประสานได้ (ผ่านการกรองความมั่นใจและ "ไม่ใช่ส่วนของบรรทัดข้างเคียง" แล้ว)
ADLIBS = frozenset({
    "yeah", "yea", "ye", "oh", "ooh", "oooh", "ah", "aah", "ahh", "hey", "heyy", "woah", "whoa", "woo", "wooh", "uh", "huh", "mm", "mmm", "hmm",
    "la", "na", "nah", "ayy", "aye", "yo", "ha", "haha", "ohh", "eh", "ay", "doo", "da", "hoo", "ooo", "uhh", "yah", "yup",
    "เย้", "โอ้", "อา", "เฮ้", "อู้", "ลา", "นา", "ฮึ", "เย่", "โอ", "อ๊า",
    "예", "오", "어", "아", "에이", "야", "우", "나", "라", "イェー", "オー", "ああ", "はい", "哦", "啊", "耶", "喔",
})


def heard_extras(out_lines: list[dict], lines: list[InLine], transcript: list[TWord], nospace: bool = False,
                 min_ratio: float = 0.62, max_words: int = 6, max_dur_s: float = 6.0) -> list[dict]:
    """สิ่งที่ AI "ได้ยิน" แต่ไม่มีในเนื้อเพลงเว็บ — เสียงประสาน/คอรัส/ad-lib (เช่น "oh-oh-oh", "I watch you") : ผู้ใช้ให้ AI ฟังเสียงจริงเพื่อเก็บส่วนนี้
    เอาคำใน transcript ที่ตกนอกช่วงของบรรทัดเว็บที่จับคู่ได้ มารวมเป็นบรรทัดสั้น แล้วคืนเป็นบรรทัดเสียงประสาน (voice=background, extra=True)
    กรองเข้ม: มั่นใจเฉลี่ย ≥ 0.55 · ไม่วนซ้ำ · ไม่เกิน max_words คำ/max_dur_s วินาที · ไม่ตรงกับบรรทัดเนื้อเพลงบรรทัดใดเลย (ไม่งั้นเป็นแค่คำเดียวกัน)"""
    spans = [(float(ln["start"]) - 0.25, float(ln["end"]) + 0.25) for ln in out_lines if ln.get("resolved", True) and ln.get("words")]
    spans.sort()
    clean = clean_transcript(transcript)

    def covered(t: float) -> bool:
        return any(a <= t <= b for a, b in spans)

    free = [w for w in clean if not covered((w.start + w.end) / 2.0)]
    if not free:
        return []
    lyric_norm = [norm_chars("".join(ln.words)) for ln in lines]
    groups = group_words_into_lines(free, max_gap_s=0.6, max_words=max_words, max_chars=36 if nospace else 32)
    extras: list[dict] = []
    for g in groups:
        wt = g.word_times or []
        if not g.words or not wt or len(g.words) > max_words:
            continue
        probs = g.word_probs or [0.7] * len(wt)
        text = norm_chars("".join(g.words))
        if len(text) < 3 or g.end - g.start > max_dur_s or not _plausible_ai_line(g.words, probs):
            continue
        if len(g.words) < 2 and len(text) < 5 and text not in ADLIBS:
            continue                                   # คำเดี่ยวสั้นๆ มักเป็นคำหลุดจากขอบบรรทัดข้างเคียง — ยกเว้นคำคอรัส/ad-lib ที่รู้จัก (yeah, oh, ooh ...)
        if any(float(ol["start"]) - 3.0 <= g.start <= float(ol["end"]) + 3.0 and ol["i"] < len(lines)
               and text in norm_chars("".join(lines[ol["i"]].words)) for ol in out_lines):
            continue                                   # เป็นส่วนหนึ่งของบรรทัดเนื้อเพลงที่อยู่ติดกัน (คำต้น/ท้ายบรรทัดที่เวลาเลยขอบมา) ไม่ซ้ำเป็นบรรทัดใหม่
        if lyric_norm and _best_lyric_span(text, lyric_norm, max_span=1)[0] >= min_ratio:
            continue                                   # คำเดียวกับบรรทัดเนื้อเพลง (แค่เวลาหลุดช่วง) ไม่ซ้ำ
        extras.append({"start": g.start, "end": g.end, "text_words": list(g.words), "voice": "background", "extra": True,
                       "resolved": True, "quality": round(float(sum(probs) / len(probs)), 3),
                       "words": [[a, b, float(p)] for (a, b), p in zip(wt, probs)]})
    return extras


def retime_unresolved(out_lines: list[dict], lines: list[InLine], neighbors: int = 3) -> None:
    """บรรทัดที่ AI จับคู่เสียงไม่ได้: ใช้เวลาของเว็บ + ส่วนต่าง (AI - เว็บ) ค่ากลางของบรรทัดข้างเคียงที่จับคู่ได้ (±neighbors บรรทัด)
    แทนค่าออฟเซ็ตทั้งเพลงที่อาจเพี้ยน (ข้างเคียงยังเป็นตัวแทนเวลาจริงของช่วงนั้นดีที่สุด) · แก้ out_lines ในที่"""
    by_i = {int(ln["i"]): ln for ln in out_lines}
    deltas: dict[int, float] = {}
    for i, ln in by_i.items():
        if ln.get("resolved") and ln.get("words") and i < len(lines) and lines[i].start is not None:
            deltas[i] = float(ln["words"][0][0]) - float(lines[i].start)
    if not deltas:
        return
    keys = sorted(deltas)
    for i, ln in by_i.items():
        if ln.get("resolved") or i >= len(lines) or lines[i].start is None:
            continue
        near = sorted(keys, key=lambda k: abs(k - i))[:neighbors * 2]
        near = [k for k in near if abs(k - i) <= 12]
        if not near:
            continue
        d = float(sorted(deltas[k] for k in near)[len(near) // 2])
        src = lines[i]
        wt = src.word_times if src.word_times and len(src.word_times) == len(src.words) else None
        if wt:
            words = [[float(a) + d, float(b) + d, 0.3] for a, b in wt]
        else:
            words = [list(w) for w in _spread(src, float(src.start) + d, float(src.end if src.end is not None else src.start + 3.0) + d)]
        ln["words"] = words
        ln["start"] = words[0][0]
        ln["end"] = words[-1][1]


def tidy_lines(lines: list[ReLine]) -> list[ReLine]:
    """ทำความสะอาดผลที่ประกอบจากเสียง: เรียงตามเวลา · ตัดบรรทัดซ้ำ (ข้อความอยู่ในอีกบรรทัดที่เวลาทับ/ติดกัน) · ไม่ให้เวลาทับกัน
    (UI หาบรรทัดปัจจุบันด้วยเวลา บรรทัดทับกัน = เห็นข้อความซ้ำซ้อนบนจอ)"""
    out: list[ReLine] = []
    for ln in sorted(lines, key=lambda r: (r.start, r.end)):
        if not out:
            out.append(ln)
            continue
        prev = out[-1]
        a, b = norm_chars("".join(prev.text_words)), norm_chars("".join(ln.text_words))
        overlap = min(prev.end, ln.end) - max(prev.start, ln.start)
        shorter = max(0.05, min(prev.end - prev.start, ln.end - ln.start))
        same_src = bool(prev.src and ln.src and set(ln.src) & set(prev.src))
        contained = bool(a and b and min(len(a), len(b)) >= 4 and (a in b or b in a))
        close = ln.start - prev.end < 1.0
        if (overlap > 0.3 * shorter and (same_src or contained)) or (contained and close and same_src):
            if len(b) > len(a):          # เก็บบรรทัดที่ข้อความครบกว่า
                out[-1] = ln
            continue
        if ln.start < prev.end:          # เวลาทับเล็กน้อย: ตัดท้ายบรรทัดก่อนหน้า (ไม่ให้สองบรรทัดเป็น "ปัจจุบัน" พร้อมกัน)
            new_end = max(prev.start + 0.2, ln.start)
            prev.words = [(x, min(y, new_end), c) for x, y, c in prev.words if x < new_end]
            prev.end = new_end
            if not prev.words:
                out.pop()
        out.append(ln)
    return out



def fill_missing_lines(res: ReResult, lines: list[InLine], vsegs: list[tuple[float, float]], duration: float,
                       min_voiced_per_line_s: float = 0.8) -> ReResult:
    """เติมบรรทัดเนื้อเพลงที่ AI ฟังไม่ได้ยิน (แร็พเร็ว/เสียงซ้อน/ดูเอ็ต) ลงในช่วงที่ "มีเสียงร้องจริง" ระหว่างบรรทัดที่ฟังได้ทั้งสองข้าง
    เวลากระจายตามจำนวนตัวอักษรในเวลาที่มีเสียงร้อง (ความมั่นใจต่ำ = ประมาณ) · ไม่เติมถ้าช่วงนั้นเสียงร้องน้อยเกินไป (ไม่ใช่บรรทัดนั้นแน่)"""
    if not res.lines or not lines or not vsegs:
        return res
    anchors = sorted(((min(r.src), max(r.src), r) for r in res.lines if r.src), key=lambda t: (t[0], t[1], t[2].start))
    used = {k for _a, _b, r in anchors for k in r.src or []}
    missing = [k for k in range(len(lines)) if k not in used and lines[k].words]
    if not missing:
        return res
    runs: list[list[int]] = []
    for k in missing:
        if runs and k == runs[-1][-1] + 1:
            runs[-1].append(k)
        else:
            runs.append([k])
    added: list[ReLine] = []
    for run in runs:
        k0, k1 = run[0], run[-1]
        before = [r for lo, hi, r in anchors if hi < k0]
        after = [r for lo, hi, r in anchors if lo > k1]
        if not before and not after:
            continue
        t0 = max(r.end for r in before) if before else 0.0
        t1 = min(r.start for r in after) if after else duration
        spans = [(max(a, t0), min(b, t1)) for a, b in vsegs if min(b, t1) - max(a, t0) > 0.05]
        voiced = sum(b - a for a, b in spans)
        if voiced < min_voiced_per_line_s * len(run):
            continue
        weights = [max(1, len(norm_chars("".join(lines[k].words)))) for k in run]
        tot = sum(weights)

        def to_real(x: float) -> float:
            for a, b in spans:
                if x <= b - a:
                    return a + x
                x -= b - a
            return spans[-1][1]

        acc = 0.0
        for k, w in zip(run, weights):
            a, b = to_real(voiced * acc / tot), to_real(voiced * (acc + w) / tot)
            acc += w
            if b - a < 0.2:
                continue
            words = _spread(lines[k], a, b)
            added.append(ReLine(a, b, words, list(lines[k].words), [k]))
    if not added:
        return res
    return ReResult(lines=tidy_lines(res.lines + added), coverage=res.coverage)


def transcript_reliable(words: list[TWord], min_words: int = 40, min_prob: float = 0.55) -> bool:
    """transcript น่าเชื่อถือพอจะใช้เป็นเนื้อเพลงแทนไหม: คำพอ · มั่นใจเฉลี่ยสูง · ไม่วนซ้ำคำเดียว (hallucination)"""
    ws = clean_transcript(words)
    if len(ws) < min_words:
        return False
    if sum(w.prob for w in ws) / len(ws) < min_prob:
        return False
    distinct = len({norm_chars(w.text) for w in ws})
    return distinct / len(ws) >= 0.15
