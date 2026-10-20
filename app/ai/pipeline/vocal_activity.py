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
