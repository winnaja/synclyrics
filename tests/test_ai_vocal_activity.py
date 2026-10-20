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


def test_snap_words_to_voice_moves_start_to_real_onset_and_trims_trailing_silence():
    import numpy as np

    from app.ai.pipeline.vocal_activity import snap_words_to_voice

    sr = 16000
    x = np.zeros(sr * 4, dtype=np.float32)
    t = np.arange(sr) / sr
    x[int(1.5 * sr):int(2.5 * sr)] = 0.3 * np.sin(2 * np.pi * 220 * t)       # ร้องจริง 1.5-2.5 วิ
    out = snap_words_to_voice([[1.0, 3.0, 1.0]], x, sr)                      # Whisper ให้คำนี้ 1.0-3.0 (ทั้งหน้า/หลังเป็นความเงียบ)
    assert 1.45 <= out[0][0] <= 1.6 and 2.45 <= out[0][1] <= 2.7
    same = snap_words_to_voice([[1.6, 2.4, 1.0]], x, sr)                     # เริ่มตอนร้องอยู่แล้ว = ไม่ขยับ
    assert abs(same[0][0] - 1.6) < 1e-6


def test_snap_line_onset_moves_first_word_to_voice_return_after_a_dip():
    import numpy as np

    from app.ai.pipeline.vocal_activity import snap_line_onset

    sr = 16000
    t = np.arange(sr * 2) / sr
    tone = 0.3 * np.sin(2 * np.pi * 220 * t).astype(np.float32)
    x = np.zeros(sr * 4, dtype=np.float32)
    x[int(0.5 * sr):int(1.5 * sr)] = tone[:sr]            # หางเสียงของบรรทัดก่อนหน้า
    x[int(2.0 * sr):int(3.0 * sr)] = tone[:sr]            # เสียงร้องบรรทัดนี้เริ่มจริงที่ 2.0
    out = snap_line_onset([[1.2, 2.6, 1.0], [2.6, 3.0, 1.0]], x, sr)   # Whisper ลากคำแรกย้อนไปที่ 1.2
    assert 1.95 <= out[0][0] <= 2.1
    assert out[1][0] >= out[0][1] - 1e-9                   # คำถัดไปไม่ซ้อน
    quiet = snap_line_onset([[0.6, 1.2, 1.0]], x, sr)      # ร้องต่อเนื่องไม่มี dip = ไม่ขยับ
    assert abs(quiet[0][0] - 0.6) < 1e-9


def test_compact_line_outliers_moves_stray_first_word_next_to_the_rest_of_the_line():
    from app.ai.pipeline.vocal_activity import compact_line_outliers

    line = [[37.3, 37.5, 1.0], [40.2, 40.6, 1.0], [40.7, 41.0, 1.0], [41.1, 41.3, 1.0], [41.4, 42.0, 1.0]]
    out = compact_line_outliers(line)
    assert out[0][1] <= out[1][0] and out[1][0] - out[0][1] < 0.1 and out[0][0] > 39.0
    tight = [[1.0, 1.4, 1.0], [1.5, 1.9, 1.0], [2.0, 2.4, 1.0]]
    assert compact_line_outliers(tight) == tight                      # ไม่มีช่องว่างผิดปกติ = ไม่แตะ


def test_classify_backing_flags_quiet_short_lines_and_echoes():
    import numpy as np

    from app.ai.pipeline.vocal_activity import classify_backing

    sr = 16000
    x = np.zeros(sr * 60, dtype=np.float32)
    t = np.arange(sr * 2) / sr
    lines = []
    for i in range(10):
        a = 3.0 + i * 5.0
        amp = 0.02 if i == 4 else 0.3                  # บรรทัดที่ 4 เบามาก (คอรัส)
        x[int(a * sr):int(a * sr) + sr * 2] = amp * np.sin(2 * np.pi * 220 * t).astype(np.float32)
        lines.append({"start": a, "end": a + 2.0, "words": ["I", "watch", "you"] if i == 4 else ["Lead", "line", "number", str(i)]})
    flags = classify_backing(lines, x, sr)
    assert flags[4] and not any(f for k, f in enumerate(flags) if k != 4)
    assert classify_backing(lines[:5], x, sr) == [False] * 5   # เพลงมีบรรทัดน้อยไม่ตัดสิน


def test_remap_curves_stretches_curve_to_new_word_span():
    from app.ai.pipeline.vocal_activity import remap_curves

    out = remap_curves([[1.0, 0.0, 1.5, 0.5, 2.0, 1.0], None], [[1.0, 2.0, 1.0], [3.0, 4.0, 1.0]], [[1.5, 2.5, 1.0], [3.0, 4.0, 1.0]])
    assert out[0][0] == 1.5 and out[0][-2] == 2.5 and abs(out[0][2] - 2.0) < 1e-6 and out[1] is None


def test_word_curve_is_smooth_monotone_and_spans_the_word():
    from types import SimpleNamespace as NS

    from app.ai.pipeline.align import _curve

    group, f = [], 0
    for d in [3, 3, 15, 3, 3, 3, 3, 3, 3, 3]:
        group.append(NS(start=f, end=f + d))
        f += d + 1
    cv = _curve(group, 10.0, 0.02, 10.0, 10.0 + f * 0.02)
    ts, ps = cv[0::2], cv[1::2]
    assert ts[0] == 10.0 and abs(ts[-1] - (10.0 + f * 0.02)) < 1e-6 and ps[0] == 0.0 and ps[-1] == 1.0
    assert all(b >= a for a, b in zip(ps, ps[1:]))
    slopes = [(ps[i + 1] - ps[i]) / (ts[i + 1] - ts[i]) for i in range(len(ts) - 1)]
    avg = 1.0 / (ts[-1] - ts[0])
    assert max(slopes) < 2.0 * avg                     # ไม่พุ่ง/กระโดดเร็วกว่าเฉลี่ยเกิน 2 เท่า


def test_assign_singers_splits_two_clusters_and_keeps_solo_and_sparse_data():
    import numpy as np

    from app.ai.pipeline.speakers import assign_singers

    rng = np.random.default_rng(0)

    def unit(v):
        return v / np.linalg.norm(v)

    a, b = unit(rng.normal(size=192)), unit(rng.normal(size=192))
    embs = [unit(a + 0.15 * rng.normal(size=192)) if i % 3 else unit(b + 0.15 * rng.normal(size=192)) for i in range(24)]
    who, st = assign_singers(embs, [3.0] * 24)
    assert st["multi"] and set(who) == {0, 1}
    assert who[1] == who[2] and who[0] != who[1]                      # กลุ่มใหญ่ (i%3 != 0) เป็นนักร้องนำ
    solo = [unit(a + 0.15 * rng.normal(size=192)) for _ in range(24)]
    who2, st2 = assign_singers(solo, [3.0] * 24)
    assert not st2["multi"] and set(who2) == {0}
    assert assign_singers(embs[:5], [3.0] * 5)[1]["multi"] is False      # ข้อมูลน้อย = ไม่ตัดสิน
