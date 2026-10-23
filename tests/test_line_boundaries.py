"""รอยต่อระหว่างบรรทัด: การเลือกบรรทัดไฮไลต์/บรรทัดที่จอเลื่อนไปหา และเวลาจบคำท้ายบรรทัดจาก AI
(ฟังก์ชันล้วน ไม่ใช้ Qt/torch — ส่วน QML จริงอยู่ใน test_ui_smoke: รอยต่อบรรทัด)

อาการที่ต้องกัน: คำท้ายบรรทัดค้างบนจอนานก่อนขึ้นบรรทัดถัดไปเป็นระยะ
สาเหตุที่พิสูจน์แล้ว (1) lead ของจอเลื่อนผูกกับ "เวลาจบบรรทัด" ซึ่ง AI ต่อให้เท่ากับเวลาเริ่มบรรทัดถัดไป → lead ไม่ทำงานเลยกับบรรทัดที่ต่อกัน
(2) เอฟเฟกต์ค้างของคำ (ลอย/เรืองแสง) รอจนบรรทัดถัดไปเริ่ม แม้คำท้ายจบไปแล้วหลายวินาทีเมื่อมีช่องว่าง
"""

from __future__ import annotations

import pytest

from app.ai.pipeline import align
from app.ui.lyrics_model import find_line_index, scroll_line_index

STARTS = [10.0, 11.5, 16.0]


@pytest.mark.parametrize("pos,expected", [
    (9.999, -1),          # ก่อนบรรทัดแรก
    (10.0, 0),            # เท่ากับจุดเริ่ม = ถึงบรรทัดนั้นแล้ว
    (11.499, 0),          # ก่อนบรรทัดถัดไปนิดเดียว
    (11.5, 1),            # เท่ากับจุดเริ่มบรรทัดถัดไป
    (11.501, 1),          # ผ่านจุดเริ่มแล้ว
    (15.9, 1),            # ช่องว่าง: ยังอยู่บรรทัดก่อนหน้า
    (999.0, 2),           # เลยบรรทัดสุดท้าย
])
def test_highlight_line_follows_real_time_only(pos, expected):
    assert find_line_index(STARTS, pos) == expected


def test_highlight_with_duplicate_or_missing_timestamps():
    assert find_line_index([5.0, 5.0, 9.0], 5.0) == 1       # เวลาซ้ำ: ไปบรรทัดหลังสุดที่เริ่มแล้ว (ไม่ย้อนกลับ)
    assert find_line_index([5.0, 5.0, 9.0], 4.99) == -1
    assert find_line_index([], 1.0) == -1
    assert scroll_line_index([], 1.0, 0.8) == -1


def test_scroll_lead_applies_to_contiguous_lines():
    # บรรทัด 0 จบ = บรรทัด 1 เริ่ม (11.5) แบบที่ AI ต่อเวลาให้ · เดิม lead ไม่ทำงานเลยกรณีนี้ (ต้องรอ end - 0.05)
    assert scroll_line_index(STARTS, 10.69, 0.8) == 0
    assert scroll_line_index(STARTS, 10.71, 0.8) == 1
    assert find_line_index(STARTS, 10.71) == 0            # ไฮไลต์ยังอยู่บรรทัดเดิม ไม่ตัดคำท้าย


def test_scroll_lead_applies_across_gaps_and_never_lags_highlight():
    assert scroll_line_index(STARTS, 15.19, 0.8) == 1
    assert scroll_line_index(STARTS, 15.21, 0.8) == 2
    for t in [x / 100 for x in range(0, 2000)]:
        for lead in (0.0, 0.3, 0.8, 1.0):
            assert scroll_line_index(STARTS, t, lead) >= find_line_index(STARTS, t)   # จอไม่ตามหลังไฮไลต์เด็ดขาด


def test_scroll_lead_zero_or_negative_equals_highlight():
    for t in (0.0, 9.9, 10.0, 11.5, 12.0, 16.0, 30.0):
        assert scroll_line_index(STARTS, t, 0.0) == find_line_index(STARTS, t)
        assert scroll_line_index(STARTS, t, -1.0) == find_line_index(STARTS, t)


def test_seek_is_stateless():
    """ฟังก์ชันล้วนไม่มีสถานะ: seek ไปมาให้ผลเท่าเดิมเสมอ"""
    seq = [12.0, 5.0, 16.5, 10.0, 11.5, 0.0]
    first = [(find_line_index(STARTS, t), scroll_line_index(STARTS, t, 0.8)) for t in seq]
    assert first == [(find_line_index(STARTS, t), scroll_line_index(STARTS, t, 0.8)) for t in seq]


# ---------------- เวลาจบคำท้ายบรรทัดจาก AI (_hold_notes) ----------------
def _tok(n: int):
    from types import SimpleNamespace
    return [SimpleNamespace(start=10 + i * 3, end=10 + i * 3 + 2, score=1.0) for i in range(n)]   # เฟรมสมมติ (0.02 วิ/เฟรม)


def _raw(lines: list[list[tuple[float, float]]]):
    return [[([object()], s, e) for s, e in ln] for ln in lines]


def _flat(raw):
    return [(w[1], w[2]) for ln in raw for w in ln if w is not None]


def test_hold_notes_last_word_never_overruns_next_line_start():
    # คำท้ายบรรทัด 0 (CTC บอกจบ 11.0) ต่อไปถึงบรรทัด 1 ที่เริ่ม 11.5 แต่ไม่เกิน 11.5
    raw = _raw([[(10.0, 10.4), (10.6, 11.0)], [(11.5, 11.9), (12.0, 12.4)]])
    align._hold_notes(raw)
    (_, _), (s2, e2), (s3, _), (_, _) = _flat(raw)
    assert e2 <= s3 + 1e-9 and e2 == pytest.approx(11.5)


def test_hold_notes_caps_last_word_so_it_does_not_hang_across_long_gap():
    # ช่องว่างยาว 6 วินาที: คำท้ายยืดได้ไม่เกิน HOLD_MAX_S จากจุดเริ่มคำ (ไม่ค้างจนบรรทัดถัดไป)
    raw = _raw([[(10.0, 10.4), (10.6, 11.0)], [(17.0, 17.4)]])
    align._hold_notes(raw)
    s2, e2 = _flat(raw)[1]
    assert e2 - s2 <= align.HOLD_MAX_S + 1e-9
    assert e2 < 17.0


def test_hold_notes_invariants_on_messy_input():
    # เวลาซ้อน/ซ้ำ/คำสั้นมาก: ทุกคำต้อง start < end · ลำดับเวลาเริ่มไม่ย้อน · จบไม่เกินเริ่มคำถัดไปเกินเพดานขั้นต่ำ 0.04
    raw = _raw([[(1.0, 1.04), (1.0, 1.04), (1.5, 1.6)], [(1.5, 1.52), (3.0, 3.2)], [(3.0, 3.1)]])
    align._hold_notes(raw)
    flat = _flat(raw)
    assert all(e > s for s, e in flat)
    for (s1, e1), (s2, _) in zip(flat, flat[1:]):
        assert e1 <= max(s2, s1 + 0.04) + 1e-9
    last_s, last_e = flat[-1]
    assert last_e == pytest.approx(3.1 + align.HOLD_TAIL_S)      # คำสุดท้ายของเพลง: ต่อ HOLD_TAIL_S เท่านั้น


def test_hold_notes_skips_unaligned_words():
    raw = [[None, ([object()], 2.0, 2.3)], [([object()], 3.0, 3.3), None]]
    align._hold_notes(raw)
    assert raw[0][0] is None and raw[1][1] is None
    assert raw[0][1][2] == pytest.approx(3.0)


# ---------------- คำท้ายบรรทัด: เติมสีเต็มตามเวลาที่ร้องจริง ไม่ไล่ข้ามช่องว่างทั้งหมด ----------------
def test_last_word_fill_completes_near_sung_end_not_at_extended_end():
    # คำท้าย "moon" ร้อง 10.6-11.0 (CTC) · บรรทัดถัดไปเริ่ม 12.6 → end ถูกต่อเป็น 12.6 (เพดาน 2 วิ → 12.6) แต่ต้องเติมสีเต็มภายใน ~0.4 วิหลัง CTC จบ
    raw = _raw([[(10.0, 10.4), (10.6, 11.0)], [(12.6, 13.0)]])
    fills = align._hold_notes(raw)
    assert raw[0][1][2] == pytest.approx(12.6)                    # end ของคำยังต่อถึงบรรทัดถัดไป (ความหมายเดิม: คำเน้น/ช่องว่าง)
    fill = fills[(0, 1)]
    assert fill == pytest.approx(11.0 + align.HOLD_TAIL_S + align.HOLD_FILL_SLACK_S)
    cur = align._word_curve(_tok(4), 0.02, 10.6, 12.6, fill)
    assert cur[0] == pytest.approx(10.6) and cur[1] == 0.0
    ts, fs = cur[0::2], cur[1::2]
    assert fs[-1] == 1.0 and ts[-1] == pytest.approx(12.6)
    assert all(b >= a for a, b in zip(fs, fs[1:])) and all(b >= a for a, b in zip(ts, ts[1:]))     # ไม่ย้อน
    full_at = next(t for t, f in zip(ts, fs) if f >= 0.999)
    assert full_at <= fill + 1e-6                                   # เต็มที่ fill ไม่ใช่ที่ 12.6


def test_fill_not_capped_when_next_line_follows_immediately():
    raw = _raw([[(10.0, 10.4), (10.6, 11.0)], [(11.2, 11.6)]])       # ถัดไป 11.2: end ต่อถึง 11.2 ซึ่งไม่เกิน CTC+tail+slack → ไม่ต้องจำกัด
    fills = align._hold_notes(raw)
    assert (0, 1) not in fills
    assert align._word_curve(_tok(4), 0.02, 10.6, 11.2, None) == align._curve(_tok(4), 0.0, 0.02, 10.6, 11.2)


def test_in_line_words_still_continue_to_next_word():
    raw = _raw([[(10.0, 10.2), (10.5, 10.7)]])
    fills = align._hold_notes(raw)
    assert raw[0][0][2] == pytest.approx(10.5) and not fills
