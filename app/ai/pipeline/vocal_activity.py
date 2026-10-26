"""หาช่วงที่มีเสียงร้องจาก stem vocals (ข้อ 5.1 ขั้น 5) และช่วงดนตรีล้วน (อินโทร/โซโล่/เอาท์โทร)

RMS ต่อ frame (dB) + ค่าเกณฑ์ที่ปรับตามความดังของเพลง + hysteresis + รวมช่วงที่ห่างกันน้อยกว่า 0.3 วิ
ใช้ numpy ล้วน (ไม่พึ่ง torch) — worker เรียกกับ vocals ที่แยกแล้ว · ถ้าไม่ได้แยก (Demucs ปิด) เสียงรวมจะได้ช่วงที่ "ดังพอ"
ซึ่งไม่ใช่เสียงร้องจริง จึงต้องบอก (`from_stem=False`) ให้ผู้ใช้ผลระวัง
"""

from __future__ import annotations

from typing import Any

import numpy as np

FRAME_S = 0.05
MERGE_GAP_S = 0.3
MIN_SEGMENT_S = 0.15
REL_DB = 24.0       # เกณฑ์ = ระดับเสียงร้องปกติ (เปอร์เซ็นไทล์ 90) ลบเท่านี้
ABS_FLOOR_DB = -55.0


def frame_db(x: np.ndarray, sample_rate: int, frame_s: float = FRAME_S) -> np.ndarray:
    """RMS ต่อ frame เป็น dBFS (x เป็น mono float32)"""
    n = max(1, int(sample_rate * frame_s))
    count = len(x) // n
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    frames = x[: count * n].reshape(count, n).astype(np.float64)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    return (20.0 * np.log10(rms + 1e-9)).astype(np.float32)


def vocal_segments(vocals: Any, sample_rate: int) -> list[tuple[float, float]]:
    """คืน [(start, end), ...] วินาที เรียงตามเวลา · เสียงเงียบทั้งเพลง = []"""
    x = np.asarray(vocals, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1 if x.shape[1] <= 8 else 0)
    db = frame_db(x, sample_rate)
    if len(db) == 0:
        return []
    loud = db[db > ABS_FLOOR_DB]
    if len(loud) == 0:
        return []
    ref = float(np.percentile(loud, 90))
    on = max(ABS_FLOOR_DB, ref - REL_DB)
    off = on - 4.0                       # hysteresis: เริ่มที่ on หยุดที่ off (กันกะพริบ)
    active = np.zeros(len(db), dtype=bool)
    state = False
    for i, v in enumerate(db):
        if not state and v >= on:
            state = True
        elif state and v < off:
            state = False
        active[i] = state
    segs: list[list[float]] = []
    i = 0
    while i < len(active):
        if active[i]:
            j = i
            while j < len(active) and active[j]:
                j += 1
            segs.append([i * FRAME_S, j * FRAME_S])
            i = j
        else:
            i += 1
    merged: list[list[float]] = []
    for s, e in segs:
        if merged and s - merged[-1][1] < MERGE_GAP_S:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in merged if e - s >= MIN_SEGMENT_S]


SNAP_FRAME_S = 0.01
SNAP_REL_DB = 30.0      # เสียงร้อง "เริ่มดัง" = สูงกว่าระดับปกติ (เปอร์เซ็นไทล์ 90) ลบเท่านี้
SNAP_MIN_MOVE_S = 0.04


def snap_words_to_voice(words: list[list[float]], vocals: Any, sample_rate: int = 16000, max_shift_s: float = 1.5) -> list[list[float]]:
    """ขยับเวลาเริ่ม/จบของคำให้ตรงกับเสียงร้องจริงใน stem: Whisper/MMS มักให้คำแรกของวลีเริ่ม "ก่อน" เสียงร้อง (รวมความเงียบก่อนหน้า)
    คำที่เริ่มในช่วงเงียบจะถูกเลื่อนไปยังจุดที่เสียงร้องเริ่มดังจริง (ไม่เกิน max_shift_s และไม่เกินครึ่งหลังของคำ) · คำที่เริ่มตอนร้องอยู่แล้วไม่ขยับ
    words = [[start, end, conf], ...] เรียงตามเวลา คืนรายการใหม่ (ไม่แก้ของเดิม)"""
    x = np.asarray(vocals, dtype=np.float32)
    n = max(1, int(sample_rate * SNAP_FRAME_S))
    db = frame_db(x, sample_rate, SNAP_FRAME_S)
    if len(db) == 0 or not words:
        return [list(w) for w in words]
    loud = db[db > ABS_FLOOR_DB]
    if len(loud) == 0:
        return [list(w) for w in words]
    thr = max(ABS_FLOOR_DB, float(np.percentile(loud, 90)) - SNAP_REL_DB)
    active = db >= thr
    out = [list(w) for w in words]
    prev_end = 0.0
    for w in out:
        s, e = float(w[0]), float(w[1])
        i0, i1 = int(s / SNAP_FRAME_S), int(e / SNAP_FRAME_S)
        if i1 > i0 and i0 >= 0 and i0 < len(active):
            seg = active[i0:min(i1, len(active))]
            if len(seg) and not seg[0]:                      # เริ่มในช่วงเงียบ
                nz = np.flatnonzero(seg)
                if len(nz):
                    t = s + nz[0] * SNAP_FRAME_S
                    if SNAP_MIN_MOVE_S <= t - s <= max_shift_s and t <= e - 0.05:
                        w[0] = max(t, prev_end)
            if len(seg) and not seg[-1] and np.any(seg):      # จบในช่วงเงียบ (Whisper ลากคำไปถึงคำถัดไป): ตัดท้ายที่เสียงร้องจบจริง
                last = int(np.flatnonzero(seg)[-1])
                t_end = s + (last + 1) * SNAP_FRAME_S + 0.03
                if e - t_end >= 0.15 and t_end > w[0] + 0.05:
                    w[1] = t_end

        prev_end = max(prev_end, float(w[0]))
        if w[1] < w[0] + 0.05:
            w[1] = w[0] + 0.05
    return out


ONSET_DIP_REL_DB = 22.0    # ช่วง "ขาดเสียง" = ต่ำกว่าระดับปกติ (เปอร์เซ็นไทล์ 90) ลบเท่านี้
ONSET_ON_REL_DB = 20.0     # เสียงร้องกลับมาดังอีกครั้ง = สูงกว่าระดับปกติ ลบเท่านี้
ONSET_MIN_DIP_S = 0.15
MID_WORD_KEEP_IF_VOICED = True    # False = พฤติกรรมเดิม (ใช้เทียบในสคริปต์วัด)
ONSET_LOOKAHEAD_S = 0.5    # เผื่อให้เสียงเริ่มช้ากว่าที่ Whisper บอกได้ไม่เกินเท่านี้หลังคำจบ


def compact_line_outliers(words: list[list[float]], max_gap_s: float = 1.5) -> list[list[float]]:
    """คำในบรรทัดเดียวกันควรอยู่ติดกัน: ถ้ามีช่องว่างกลางบรรทัดยาวกว่า max_gap_s แสดงว่ากลุ่มคำฝั่งที่เล็กกว่าถูกจับคู่ผิดที่
    (เช่น "You" ถูกจับกับคำ You ของบรรทัดก่อนหน้าที่ 37 วิ ทั้งที่คำที่เหลือของบรรทัดอยู่ที่ 40 วิ) → ย้ายกลุ่มที่เล็กกว่าไปชิดกลุ่มใหญ่
    คำนำหน้า (หัวบรรทัด) ย้ายไปก่อนกลุ่มหลัง · คำท้ายย้ายไปต่อท้ายกลุ่มหน้า · ความยาวคำคงเดิม (อย่างน้อย 0.12 วิ)"""
    out = [list(w) for w in words]
    if len(out) < 3:
        return out
    gaps = [(out[i + 1][0] - out[i][1], i) for i in range(len(out) - 1)]
    gap, k = max(gaps)
    if gap <= max_gap_s:
        return out
    head, tail = out[:k + 1], out[k + 1:]
    if len(head) <= len(tail) and len(head) * 2 <= len(out):
        t = tail[0][0]
        for w in reversed(head):
            d = max(0.12, min(0.5, w[1] - w[0]))
            w[1] = t - 0.02
            w[0] = w[1] - d
            t = w[0]
    elif len(tail) < len(head) and len(tail) * 2 <= len(out):
        t = head[-1][1]
        for w in tail:
            d = max(0.12, min(0.5, w[1] - w[0]))
            w[0] = t + 0.02
            w[1] = w[0] + d
            t = w[1]
    return out


def _last_dip_onset(db: Any, i0: int, i1: int, dip_thr: float, on_thr: float, min_len: int, first: bool = False) -> int | None:
    """ในช่วงเฟรม [i0, i1): หาช่วงเสียงขาด (ต่ำกว่า dip_thr นาน ≥ min_len) ที่ตามด้วยเสียงดัง (≥ on_thr) → คืนเฟรมที่เสียงกลับมา
    first=True: ใช้ช่วงขาดแรก (คำแรกของบรรทัด) · ไม่งั้นใช้ช่วงสุดท้าย"""
    seg = db[i0:i1]
    low = seg < dip_thr
    best = None
    k = 0
    while k < len(low):
        if low[k]:
            j = k
            while j < len(low) and low[j]:
                j += 1
            if j - k >= min_len:
                after = np.flatnonzero(seg[j:] >= on_thr)
                if len(after):
                    best = i0 + j + int(after[0])
                    if first:
                        return best
            k = j
        else:
            k += 1
    return best


def snap_line_onset(words: list[list[float]], vocals: Any, sample_rate: int = 16000, max_shift_s: float = 6.0) -> list[list[float]]:
    """Whisper มักให้คำที่ตามหลังช่วงเงียบเริ่ม "ทันทีหลังคำก่อนหน้า" (ลากย้อนไปคลุมช่วงเงียบ/หางเสียงเก่า นานได้เป็นวินาที) ทั้งที่เสียงร้องจริงเริ่มทีหลัง
    หาช่วงเสียงขาด (dip) ในช่วงของคำ แล้วเลื่อนเวลาเริ่มไปที่จุดที่เสียงกลับมาดัง (onset):
      · คำแรกของบรรทัด: dip สั้นแค่ 40 ms ก็เลื่อน (วลีใหม่เริ่มหลังเว้น)
      · คำอื่นในบรรทัด: ต้อง dip ≥ 250 ms (กันพยางค์ที่เบาลงชั่วขณะ)
    ไม่มี dip = ไม่ขยับ · คำถัดไปถูกดันให้ไม่ซ้อนกัน"""
    out = [list(w) for w in words]
    if not out:
        return out
    x = np.asarray(vocals, dtype=np.float32)
    db = frame_db(x, sample_rate, SNAP_FRAME_S)
    loud = db[db > ABS_FLOOR_DB] if len(db) else db
    if len(loud) == 0:
        return out
    ref = float(np.percentile(loud, 90))
    dip_thr, on_thr = ref - ONSET_DIP_REL_DB, ref - ONSET_ON_REL_DB
    first_len = max(1, int(ONSET_MIN_DIP_S / SNAP_FRAME_S))   # คำแรกของบรรทัด: เว้นอย่างน้อย ONSET_MIN_DIP_S
    mid_len = max(1, int(0.25 / SNAP_FRAME_S))
    prev_end = 0.0
    for idx, w in enumerate(out):
        s, e = float(w[0]), float(w[1])
        i0 = max(0, int(s / SNAP_FRAME_S))
        # คำท้ายบรรทัด (ไม่ใช่คำแรก) ห้ามมองเลยจุดจบของคำ: end ของมันถูกต่อ (ลากค้าง) ไปจนเกือบถึงบรรทัดถัดไปอยู่แล้ว
        # ถ้าเผื่อมองล่วงหน้า จะไปเจอ "เสียงขาด→กลับมาดัง" ของบรรทัดถัดไปแล้วลากคำท้ายไปเริ่มที่นั่น (เคสจริง EVERYTHING 78.8→80.82
        # คำ 날엔 ที่ร้องจบไปแล้วเพิ่งขึ้นสีตอนบรรทัดถัดไปจะเริ่ม — เกือบทุกเพลง)
        look = ONSET_LOOKAHEAD_S if idx < len(out) - 1 or idx == 0 else 0.0
        i1 = min(len(db), int((e + look) / SNAP_FRAME_S))
        # คำกลางบรรทัดที่ "เริ่มตอนมีเสียงร้องอยู่แล้ว" ไม่ต้องหาจุดเริ่มใหม่: dip กลางคำยาวคือพักหายใจ/โน้ตลากที่เบาลงชั่วขณะ
        # ไม่ใช่ช่วงเงียบที่ Whisper ลากคำคลุมมา (เคสจริง: 'me' ที่ลากโน้ต 3 วิ ถูกเลื่อนไปเริ่มตอนคำถัดไปเริ่ม)
        voiced_start = MID_WORD_KEEP_IF_VOICED and idx > 0 and bool(np.any(db[i0:i0 + 5] >= on_thr))
        if i1 - i0 >= 3 and (idx == 0 or e - s >= 0.6) and not voiced_start:
            best = _last_dip_onset(db, i0, i1, dip_thr, on_thr, first_len if idx == 0 else mid_len, first=idx == 0)
            if best is not None:
                t = best * SNAP_FRAME_S
                if SNAP_MIN_MOVE_S <= t - s <= max_shift_s:
                    w[0] = max(t, prev_end)
                    if w[1] < w[0] + 0.12:
                        w[1] = w[0] + 0.12
        elif w[0] < prev_end:
            w[0] = prev_end
        if w[1] < w[0] + 0.05:
            w[1] = w[0] + 0.05
        prev_end = float(w[1]) if idx + 1 < len(out) and out[idx + 1][0] < w[1] else float(w[0])
    return out


def remap_curves(curves: list[list[float] | None], old: list[list[float]], new: list[list[float]]) -> list[list[float] | None]:
    """เวลาของคำถูกขยับ/ย่อ (snap, compact) → ยืดเส้นโค้งการร้องในคำให้ตรงช่วงใหม่ [start, end] ของคำนั้น"""
    out: list[list[float] | None] = []
    for cv, o, n in zip(curves, old, new):
        if not cv or len(cv) < 4:
            out.append(None)
            continue
        o0, o1, n0, n1 = float(o[0]), float(o[1]), float(n[0]), float(n[1])
        if o1 - o0 < 1e-6 or n1 - n0 < 0.1:
            out.append(None)
            continue
        k = (n1 - n0) / (o1 - o0)
        pts = list(cv)
        for i in range(0, len(pts), 2):
            pts[i] = round(n0 + (pts[i] - o0) * k, 3)
        pts[0], pts[-2] = n0, n1
        out.append(pts)
    return out


# ปรับ 2026-10-26 จากการวัดกับ 160 เพลง (8,595 บรรทัด) ที่เฉลยใส่วงเล็บกำกับเสียงประสานไว้ — scripts/eval_backing.py
# ของเดิมเทียบความดังกับ "ค่ากลางทั้งเพลง" ทำให้ท่อนที่ร้องเบาทั้งท่อนถูกตีเป็นประสานยกท่อน และตัดบรรทัดยาวเกิน 6 คำทิ้ง
# ทั้งที่จำนวนคำไม่มีประโยชน์เลย (AUC 0.475 เท่าเดาสุ่ม) จึงพลาดเสียงประสานไป 85%
# ของใหม่เทียบกับค่ากลาง "แถวนั้น" (AUC 0.725 เทียบ 0.684) · ผล: จับได้ 14% -> 35% โดยเสียงร้องหลักยังไม่ถูกตีผิด 95%
BACKING_QUIET_DB = 3.5         # เบากว่าบรรทัดรอบข้างเท่านี้ = น่าจะเป็นเสียงประสาน/คอรัส
BACKING_ECHO_QUIET_DB = 1.5    # บรรทัดที่เป็นเสียงสะท้อนของบรรทัดข้างเคียง ใช้เกณฑ์เบากว่านี้ก็พอ
BACKING_NEAR_LINES = 8         # กี่บรรทัดรอบข้างที่ใช้หาค่ากลาง "แถวนั้น"


def _norm_text(words: list[str]) -> str:
    return "".join(c for c in "".join(words).casefold() if c.isalnum())


def classify_backing(lines: list[dict[str, Any]], vocals: Any, sample_rate: int = 16000,
                     quiet_db: float | None = None) -> list[bool]:
    """บรรทัดไหนเป็นเสียงประสาน/คอรัส (แสดงเป็นแถวเล็กใต้บรรทัดหลัก แบบ Apple Music)
    ดูจาก (1) ความดังของ stem เสียงร้องในช่วงบรรทัด เทียบค่ากลางของ "บรรทัดรอบข้าง" — เสียงประสานเบากว่าเสียงนำ
          (เทียบทั้งเพลงไม่ได้: ท่อนที่ร้องเบาทั้งท่อนจะถูกตีเป็นประสานยกท่อน)
          (2) ข้อความสะท้อนบรรทัดข้างเคียง (เช่น "I watch you" ซ้ำท้ายบรรทัดก่อนหน้า) ที่ร้องซ้อน/ติดกัน
    lines = [{"start","end","words":[str,...]}] · คืน bool ต่อบรรทัด (เพลงมีบรรทัดน้อยกว่า 8 = ไม่ตัดสิน)"""
    quiet = BACKING_QUIET_DB if quiet_db is None else float(quiet_db)
    echo_quiet = max(0.0, quiet - (BACKING_QUIET_DB - BACKING_ECHO_QUIET_DB))
    n = len(lines)
    flags = [False] * n
    if n < 8:
        return flags
    x = np.asarray(vocals, dtype=np.float32)
    db = frame_db(x, sample_rate, SNAP_FRAME_S)
    if len(db) == 0:
        return flags
    levels: list[float | None] = []
    for ln in lines:
        i0, i1 = int(float(ln["start"]) / SNAP_FRAME_S), int(float(ln["end"]) / SNAP_FRAME_S)
        seg = db[max(0, i0):min(len(db), i1)]
        seg = seg[seg > ABS_FLOOR_DB]
        levels.append(float(np.percentile(seg, 75)) if len(seg) >= 5 else None)
    known = [v for v in levels if v is not None]
    if len(known) < 8:
        return flags
    gref = float(np.median(known))
    texts = [_norm_text(ln["words"]) for ln in lines]
    for i, ln in enumerate(lines):
        lv = levels[i]
        if lv is None or len(ln["words"]) == 0:
            continue
        near = [levels[j] for j in range(max(0, i - BACKING_NEAR_LINES), min(n, i + BACKING_NEAR_LINES + 1))
                if levels[j] is not None and j != i]
        ref = float(np.median(near)) if len(near) >= 4 else gref
        quiet_by = ref - lv
        echo = False
        for j in (i - 1, i + 1):
            if 0 <= j < n and len(texts[i]) >= 3 and texts[i] and texts[i] in texts[j] and texts[i] != texts[j]:
                gap = float(lines[j]["start"]) - float(ln["end"]) if j > i else float(ln["start"]) - float(lines[j]["end"])
                if gap < 1.5:
                    echo = True
        flags[i] = quiet_by >= quiet or (echo and quiet_by >= echo_quiet)
    return flags


def instrumental_gaps(segments: list[tuple[float, float]], duration: float, min_gap_s: float = 4.0) -> list[tuple[float, float]]:
    """ช่วงที่ไม่มีเสียงร้องต่อเนื่อง ≥ min_gap_s: ก่อนเสียงร้องแรก (อินโทร) · ระหว่างช่วง (โซโล่/เบรก) · หลังเสียงร้องสุดท้าย (เอาท์โทร)
    segments ว่าง (ไม่มีเสียงร้องเลย) = ทั้งเพลงเป็นดนตรีล้วน"""
    gaps: list[tuple[float, float]] = []
    prev_end = 0.0
    for s, e in segments:
        if s - prev_end >= min_gap_s:
            gaps.append((round(prev_end, 3), round(s, 3)))
        prev_end = max(prev_end, e)
    if duration - prev_end >= min_gap_s:
        gaps.append((round(prev_end, 3), round(duration, 3)))
    return gaps
