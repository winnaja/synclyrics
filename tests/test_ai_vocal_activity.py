"""ช่วงเสียงร้อง/ช่วงดนตรีล้วน จากสัญญาณสังเคราะห์ (ไม่ใช้ torch)"""

from __future__ import annotations

import numpy as np

from app.ai.pipeline.vocal_activity import instrumental_gaps, vocal_segments

SR = 16000


def tone(seconds: float, amp: float = 0.2) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype=np.float32) + 1e-5


def test_segments_found_with_intro_solo_and_outro():
    x = np.concatenate([silence(6), tone(5), silence(0.2), tone(3), silence(8), tone(4), silence(7)])
    segs = vocal_segments(x, SR)
    assert len(segs) == 2                               # ช่องว่าง 0.2 วิรวมเข้าด้วยกัน
    assert abs(segs[0][0] - 6.0) < 0.15 and abs(segs[0][1] - 14.2) < 0.2
    assert abs(segs[1][0] - 22.2) < 0.2 and abs(segs[1][1] - 26.2) < 0.2
    total = len(x) / SR
    gaps = instrumental_gaps(segs, total)
    assert len(gaps) == 3
    assert gaps[0][0] == 0.0 and abs(gaps[0][1] - 6.0) < 0.15       # อินโทร
    assert abs((gaps[1][1] - gaps[1][0]) - 8.0) < 0.4               # โซโล่
    assert abs(gaps[2][1] - total) < 1e-6                           # เอาท์โทร


def test_short_pauses_between_words_are_not_gaps():
    x = np.concatenate([tone(2), silence(1.0), tone(2), silence(1.5), tone(2)])
    segs = vocal_segments(x, SR)
    assert instrumental_gaps(segs, len(x) / SR, 4.0) == []


def test_silence_only_is_no_vocals_and_whole_song_is_a_gap():
    x = silence(20)
    assert vocal_segments(x, SR) == []
    assert instrumental_gaps([], 20.0) == [(0.0, 20.0)]


def test_quiet_backing_vocals_far_below_main_are_ignored_but_main_found():
    x = np.concatenate([tone(3, 0.3), silence(2), tone(3, 0.0004), silence(2), tone(3, 0.3)])
    segs = vocal_segments(x, SR)
    assert len(segs) == 2


def test_query_gpu_never_raises():
    from app.ai.gpu import GpuInfo, query_gpu

    info = query_gpu()
    assert info is None or (isinstance(info, GpuInfo) and info.vram_total_mb > 0)
