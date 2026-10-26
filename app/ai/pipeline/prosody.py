"""แยก "ร้อง" ออกจาก "พูด" จากลักษณะระดับเสียง (ไม่ใช้โมเดลเพิ่ม ใช้ numpy ล้วน)

ทำไมต้องมี: ระบบเดิมแยกได้แค่เสียงหลัก/คนที่สอง/เสียงประสาน ไม่มีประเภท "คำพูดแทรก" เลย
บทพูดที่แทรกในเพลงจึงถูกยัดเข้าไปเป็นเนื้อร้องหลัก

หลักการ: การร้องจะ "ค้างโน้ต" — ระดับเสียงนิ่งอยู่ที่ค่าหนึ่งนานพอสมควรแล้วค่อยเปลี่ยน
ส่วนการพูดระดับเสียงไหลลงตลอดและมีช่วงที่ไม่มีระดับเสียงชัด (เสียงพยัญชนะ) มากกว่า
วัดสองอย่าง: สัดส่วนเฟรมที่มีระดับเสียงชัด และสัดส่วนที่อยู่ใน "ช่วงค้างโน้ต"

*** สถานะ: ยังไม่ได้ต่อเข้าไปป์ไลน์ เพราะวัดแล้วยังแยกไม่ได้ ***

วัด 2026-10-26: เอาบรรทัดที่อยู่หลังคำกำกับ [Spoken]/旁白/독백 ในคลัง เทียบกับบรรทัดอื่น
  hold   AUC 0.442  (0.5 = แยกไม่ได้เลย)
  voiced AUC 0.532
ตัวอย่างมีแค่ 4 เพลง 18 บรรทัด เทียบ 46 บรรทัด — น้อยเกินกว่าจะสรุปว่าวิธีนี้ใช้ไม่ได้จริง
แต่ก็ไม่มีหลักฐานว่าใช้ได้ จึงยังไม่เอาไปตัดสินอะไรในแอป

ถ้าจะทำต่อ ต้องมีคำตอบจริงก่อน: ให้ผู้ใช้ระบุเพลงที่มีบทพูดและช่วงเวลาคร่าวๆ สัก 10-20 เพลง
แล้วค่อยวัดว่าสัญญาณไหนแยกได้ (อาจต้องดูอย่างอื่น เช่น ความเร็วการเปลี่ยนระดับเสียง หรือรูปแบบฟอร์แมนต์)
"""

from __future__ import annotations

from typing import Any

import numpy as np

FRAME_S = 0.040          # หน้าต่างหาระดับเสียง
HOP_S = 0.010
F0_MIN, F0_MAX = 70.0, 1000.0
VOICED_MIN = 0.35        # ค่าสหสัมพันธ์ต่ำกว่านี้ = ไม่มีระดับเสียงชัด (เสียงพยัญชนะ/เงียบ)
HOLD_TOL = 0.035         # ระดับเสียงเปลี่ยนไม่เกินเท่านี้ (สัดส่วน) ยังนับว่าค้างโน้ตเดิมอยู่
HOLD_MIN_S = 0.12        # ค้างนานเท่านี้ขึ้นไปจึงนับเป็นโน้ต


def f0_track(x: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """-> ระดับเสียง (Hz) ต่อเฟรม · 0 = ไม่มีระดับเสียงชัด · หาด้วยสหสัมพันธ์ในตัว (autocorrelation)"""
    x = np.asarray(x, dtype=np.float32)
    n = int(FRAME_S * sample_rate)
    hop = int(HOP_S * sample_rate)
    if len(x) < n:
        return np.zeros(0, dtype=np.float32)
    lo, hi = int(sample_rate / F0_MAX), int(sample_rate / F0_MIN)
    hi = min(hi, n - 1)
    if hi <= lo:
        return np.zeros(0, dtype=np.float32)
    m = 1 + (len(x) - n) // hop
    out = np.zeros(m, dtype=np.float32)
    frames = np.lib.stride_tricks.as_strided(
        x, shape=(m, n), strides=(x.strides[0] * hop, x.strides[0]), writeable=False)
    win = np.hanning(n).astype(np.float32)
    for i in range(m):
        f = frames[i] * win
        e = float(np.dot(f, f))
        if e < 1e-7:
            continue
        ac = np.correlate(f, f, mode="full")[n - 1:]
        seg = ac[lo:hi + 1]
        if seg.size == 0:
            continue
        k = int(np.argmax(seg))
        if ac[0] <= 0 or seg[k] / ac[0] < VOICED_MIN:
            continue
        out[i] = sample_rate / float(lo + k)
    return out


def sung_score(x: np.ndarray, sample_rate: int = 16000) -> dict[str, float]:
    """-> {"voiced": สัดส่วนเฟรมที่มีระดับเสียงชัด, "hold": สัดส่วนที่อยู่ในช่วงค้างโน้ต}

    ร้อง = ทั้งสองค่าสูง · พูด = ทั้งสองค่าต่ำ (โดยเฉพาะ hold เพราะพูดไม่ค้างโน้ต)
    """
    f0 = f0_track(x, sample_rate)
    if f0.size == 0:
        return {"voiced": 0.0, "hold": 0.0}
    voiced = f0 > 0
    frac_voiced = float(voiced.mean())
    need = max(2, int(HOLD_MIN_S / HOP_S))
    held = 0
    i = 0
    while i < len(f0):
        if f0[i] <= 0:
            i += 1
            continue
        j = i + 1
        while j < len(f0) and f0[j] > 0 and abs(f0[j] - f0[i]) <= HOLD_TOL * f0[i]:
            j += 1
        if j - i >= need:
            held += j - i
        i = j
    return {"voiced": round(frac_voiced, 4), "hold": round(held / len(f0), 4)}


def classify_spoken(lines: list[dict[str, Any]], vocals: Any, sample_rate: int = 16000,
                    hold_max: float = 0.12, voiced_max: float = 0.55) -> list[bool]:
    """บรรทัดไหนเป็น "คำพูดแทรก" — ค้างโน้ตน้อยและมีระดับเสียงชัดน้อย

    ตั้งเกณฑ์ให้เข้มไว้ก่อน: ตีเนื้อร้องหลักเป็นบทพูดผิดเห็นชัดกว่าการพลาดบทพูด
    """
    x = np.asarray(vocals, dtype=np.float32)
    out: list[bool] = []
    for ln in lines:
        a, b = int(float(ln["start"]) * sample_rate), int(float(ln["end"]) * sample_rate)
        seg = x[max(0, a):min(len(x), b)]
        if len(seg) < int(0.35 * sample_rate):      # สั้นเกินไป วัดระดับเสียงไม่น่าเชื่อถือ
            out.append(False)
            continue
        s = sung_score(seg, sample_rate)
        out.append(s["hold"] <= hold_max and s["voiced"] <= voiced_max)
    return out
