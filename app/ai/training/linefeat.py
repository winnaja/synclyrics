"""ฟีเจอร์สำหรับโมเดลแบ่งบรรทัด (จุดตัดระหว่างคำ) และโมเดลตรวจเสียงประสาน (รายบรรทัด) — ใช้ร่วมกันทั้งตอนเทรนและตอนใช้งานจริง

ฟีเจอร์ไม่พึ่งว่า "บรรทัดปัจจุบันเริ่มที่ไหน" (ตอนใช้งานยังไม่รู้บรรทัด) — ดูแค่คำรอบจุดตัด + ช่องว่างเวลา + ความลึกของรอยเว้นในเสียงร้อง + ข้อความซ้ำ
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from app.ai.pipeline.vocal_activity import ABS_FLOOR_DB, SNAP_FRAME_S, frame_db

PUNCT_SOFT = ",;:、，；：—–-"
PUNCT_HARD = ".!?。！？…"
CONJ = frozenset({"and", "but", "or", "so", "because", "cause", "cuz", "when", "while", "if", "that", "then", "และ", "แต่", "หรือ", "เพราะ", "ที่", "เมื่อ", "ถ้า"})
BOUNDARY_DIM = 12
LINE_DIM = 8


def _norm(w: str) -> str:
    return "".join(c for c in w.casefold() if c.isalnum())


def envelope(vocals16: np.ndarray) -> tuple[np.ndarray, float]:
    db = frame_db(np.asarray(vocals16, dtype=np.float32), 16000, SNAP_FRAME_S)
    loud = db[db > ABS_FLOOR_DB]
    ref = float(np.percentile(loud, 90)) if len(loud) else -20.0
    return db, ref


def dip_depth(db: np.ndarray, ref: float, t0: float, t1: float) -> float:
    """ช่วงเวลา [t0,t1] เสียงร้องเบาลงจากระดับปกติเท่าไร (dB, 0..40) — ช่องว่างจริงลึกกว่าการสะดุดกลางประโยค"""
    if t1 <= t0:
        return 0.0
    a, b = int(t0 / SNAP_FRAME_S), max(int(t0 / SNAP_FRAME_S) + 1, int(t1 / SNAP_FRAME_S))
    seg = db[max(0, a):min(len(db), b)]
    if len(seg) == 0:
        return 0.0
    return float(min(40.0, max(0.0, ref - float(np.min(seg)))))


def boundary_features(words: list[tuple[str, float, float]], db: np.ndarray | None, ref: float) -> np.ndarray:
    """words = [(text,start,end)] ทั้งเพลงเรียงเวลา -> (n-1, BOUNDARY_DIM) ฟีเจอร์ของจุดตัดระหว่างคำ i และ i+1"""
    n = len(words)
    if n < 2:
        return np.zeros((0, BOUNDARY_DIM), dtype=np.float32)
    gaps = np.array([max(0.0, words[i + 1][1] - words[i][2]) for i in range(n - 1)])
    med = float(np.median(gaps[gaps > 0])) if np.any(gaps > 0) else 0.1
    norm = [_norm(w[0]) for w in words]
    tri = {}
    for i in range(n - 2):
        tri.setdefault(tuple(norm[i:i + 3]), []).append(i)
    feats = np.zeros((n - 1, BOUNDARY_DIM), dtype=np.float32)
    for i in range(n - 1):
        prev, nxt = words[i], words[i + 1]
        pt = prev[0].rstrip()
        f = feats[i]
        f[0] = min(gaps[i], 5.0)
        f[1] = min(gaps[i] / max(med, 0.05), 20.0)
        f[2] = min(prev[2] - prev[1], 3.0)
        f[3] = min(nxt[2] - nxt[1], 3.0)
        f[4] = 1.0 if pt and pt[-1] in PUNCT_SOFT else 0.0
        f[5] = 1.0 if pt and pt[-1] in PUNCT_HARD else 0.0
        f[6] = 1.0 if nxt[0][:1].isupper() else 0.0
        f[7] = 1.0 if _norm(nxt[0]) in CONJ else 0.0
        f[8] = dip_depth(db, ref, prev[2], nxt[1]) / 40.0 if db is not None else 0.0
        # ก้อนสามคำที่ขึ้นต้นตรงนี้ ซ้ำที่อื่นในเพลง (ฮุกมักขึ้นบรรทัดใหม่) / ก้อนสามคำที่จบตรงนี้ซ้ำ (ท้ายบรรทัดซ้ำ)
        f[9] = 1.0 if i + 1 < n - 2 + 1 and len(tri.get(tuple(norm[i + 1:i + 4]), [])) > 1 else 0.0
        f[10] = 1.0 if i - 1 >= 0 and len(tri.get(tuple(norm[i - 2:i + 1]), [])) > 1 else 0.0
        f[11] = min(i % 10, 9) / 9.0 * 0.0     # (ตำแหน่งในเพลงไม่ใช้ — กันโมเดลจำเพลง) เว้นไว้เป็นศูนย์
    return feats


def line_features(lines: list[dict[str, Any]], db: np.ndarray | None, ref: float) -> np.ndarray:
    """lines = [{"start","end","words":[str]}] -> (n, LINE_DIM) ฟีเจอร์ตรวจเสียงประสาน/คอรัส"""
    n = len(lines)
    feats = np.zeros((n, LINE_DIM), dtype=np.float32)
    texts = [_norm("".join(ln["words"])) for ln in lines]
    counts: dict[str, int] = {}
    for t in texts:
        counts[t] = counts.get(t, 0) + 1
    levels = []
    for ln in lines:
        if db is None:
            levels.append(0.0)
            continue
        a, b = int(ln["start"] / SNAP_FRAME_S), int(ln["end"] / SNAP_FRAME_S)
        seg = db[max(0, a):min(len(db), b)]
        seg = seg[seg > ABS_FLOOR_DB]
        levels.append(float(np.percentile(seg, 75)) if len(seg) >= 5 else ref)
    med_level = float(np.median(levels)) if levels else ref
    for i, ln in enumerate(lines):
        f = feats[i]
        f[0] = max(-30.0, min(10.0, levels[i] - med_level)) / 10.0              # ดังกว่า/เบากว่าค่ากลางของเพลง
        f[1] = min(len(ln["words"]), 12) / 12.0
        f[2] = min(max(ln["end"] - ln["start"], 0.0), 8.0) / 8.0
        prev_end = lines[i - 1]["end"] if i > 0 else -9.0
        f[3] = max(-3.0, min(3.0, ln["start"] - prev_end)) / 3.0                # ซ้อน (<0) / ห่าง (>0) เทียบบรรทัดก่อน
        f[4] = 1.0 if (i > 0 and texts[i] and texts[i] in texts[i - 1] and texts[i] != texts[i - 1]) else 0.0
        f[5] = 1.0 if (i + 1 < n and texts[i] and texts[i] in texts[i + 1] and texts[i] != texts[i + 1]) else 0.0
        f[6] = min(counts.get(texts[i], 1), 6) / 6.0
        raw = "".join(ln["words"]).strip()
        f[7] = 1.0 if raw.startswith(("(", "（")) and raw.endswith((")", "）")) else 0.0
    return feats


def line_break_labels(ref_lines: list[dict[str, Any]]) -> tuple[list[tuple[str, float, float]], np.ndarray]:
    """เฉลยบรรทัดของมนุษย์ -> (คำทั้งเพลง, ป้ายจุดตัด 1 = คำถัดไปขึ้นบรรทัดใหม่)"""
    words: list[tuple[str, float, float]] = []
    starts: list[bool] = []
    for ln in ref_lines:
        for k, w in enumerate(ln["words"]):
            words.append((w[0], float(w[1]), float(w[2])))
            starts.append(k == 0)
    labels = np.array(starts[1:], dtype=np.float32) if len(starts) > 1 else np.zeros(0, dtype=np.float32)
    return words, labels


_PAREN = re.compile(r"^\s*[\(（].*[\)）]\s*$")


def backing_labels(ref_lines: list[dict[str, Any]]) -> np.ndarray:
    """ป้ายอ่อน: บรรทัดที่อยู่ในวงเล็บทั้งบรรทัด = เสียงประสาน (NetEase มักทำแบบนี้)"""
    out = []
    for ln in ref_lines:
        text = "".join(w[0] for w in ln["words"])
        out.append(1.0 if _PAREN.match(text) else 0.0)
    return np.array(out, dtype=np.float32)
