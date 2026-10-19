"""ทดสอบ AudioEngine / Limiter โดยไม่ใช้อุปกรณ์เสียง: เรียก _callback เองด้วย array ที่จองไว้"""

from __future__ import annotations

import sys
import time
import tracemalloc
import types

import numpy as np
import pytest

from app.audio.automation import AutomationLane, Param
from app.audio.deck import DeckState, PcmBuffer, Segment, full_program
from app.audio.dsp import Limiter
from app.audio.engine import AudioEngine, EngineConfig, list_output_devices

SR = 48000
BLOCK = 512


def make_pcm(frames: int, scale: float = 1.0) -> np.ndarray:
    """สัญญาณที่ทุก frame ไม่ซ้ำกัน (เช็คตำแหน่งได้แม่น) ค่าไม่เกิน ~0.6"""
    n = np.arange(frames, dtype=np.float32)
    data = np.empty((frames, 2), dtype=np.float32)
    data[:, 0] = (0.1 + 0.5 * (n / frames)) * scale
    data[:, 1] = -(0.1 + 0.4 * (n / frames)) * scale
    return data


def make_engine(**cfg) -> AudioEngine:
    eng = AudioEngine(EngineConfig(**cfg))
    eng.start(open_stream=False, sample_rate=SR)
    return eng


def run(eng: AudioEngine, blocks: int, frames: int = BLOCK) -> np.ndarray:
    """เรียก callback ซ้ำ ๆ แล้วต่อผลเป็น array เดียว"""
    out = np.zeros((frames, 2), dtype=np.float32)
    parts = []
    for _ in range(blocks):
        eng._callback(out, frames, None, None)
        parts.append(out.copy())
    return np.concatenate(parts)


def loaded(frames: int = SR * 10, deck: int = 0, scale: float = 1.0, **cfg):
    eng = make_engine(**cfg)
    data = make_pcm(frames, scale)
    buf = PcmBuffer.from_array(data, SR)
    eng.load(deck, "vid", full_program(buf))
    return eng, data, buf


# ---------------------------------------------------------------------------
# Limiter
# ---------------------------------------------------------------------------
class TestLimiter:
    def test_loud_sine_stays_below_ceiling(self) -> None:
        lim = Limiter(SR, ceiling_db=-1.0)
        t = np.arange(SR, dtype=np.float32) / SR
        sig = (3.0 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        sig = np.stack([sig, sig], axis=1).copy()
        for i in range(0, SR, BLOCK):
            blk = sig[i:i + BLOCK]
            lim.process(blk)
            assert np.max(np.abs(blk)) <= lim.ceiling + 1e-6
        assert lim.gain_reduction_db > 0
        assert np.isfinite(sig).all()

    def test_quiet_signal_untouched(self) -> None:
        lim = Limiter(SR)
        data = make_pcm(BLOCK, 0.5)
        ref = data.copy()
        lim.process(data)
        assert lim.gain == 1.0 and lim.gain_reduction_db == 0.0
        assert np.array_equal(data, ref)

    def test_releases_back_to_unity(self) -> None:
        lim = Limiter(SR)
        loud = np.full((BLOCK, 2), 2.0, dtype=np.float32)
        lim.process(loud)
        assert lim.gain < 1.0
        quiet = np.full((BLOCK, 2), 0.1, dtype=np.float32)
        for _ in range(100):  # ~1 วินาที >> release 100ms
            lim.process(quiet)
        assert lim.gain == pytest.approx(1.0, abs=1e-3)

    def test_nan_input_sanitized(self) -> None:
        lim = Limiter(SR)
        blk = np.zeros((BLOCK, 2), dtype=np.float32)
        blk[10, 0] = np.nan
        blk[20, 1] = np.inf
        lim.process(blk)
        assert np.isfinite(blk).all()
        assert np.max(np.abs(blk)) <= lim.ceiling + 1e-6

    def test_block_larger_than_max_block(self) -> None:
        lim = Limiter(SR, max_block=256)
        blk = np.full((1000, 2), 4.0, dtype=np.float32)
        lim.process(blk)
        assert np.max(np.abs(blk)) <= lim.ceiling + 1e-6


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def test_start_without_stream_sets_rate() -> None:
    eng = AudioEngine(EngineConfig())
    eng.start(open_stream=False, sample_rate=44100)
    assert eng.sample_rate == 44100
    eng.set_device(None)  # ไม่มี stream: ต้องไม่เปิดอุปกรณ์
    eng.stop()


def test_play_output_equals_source() -> None:
    eng, data, _ = loaded()
    eng.play(0)
    out = run(eng, 4)
    assert np.array_equal(out, data[:4 * BLOCK])
    assert eng.decks[0].state is DeckState.PLAYING
    assert eng.frames_rendered == 4 * BLOCK


def test_silence_when_nothing_loaded() -> None:
    eng = make_engine()
    out = run(eng, 2)
    assert not out.any()
    assert not eng.clocks[0].playing


def test_master_volume_ramp_then_exact() -> None:
    eng, data, _ = loaded()
    eng.play(0)
    eng.set_master_volume(0.5)
    out = run(eng, 6)
    ramp = int(SR * 0.02)
    # หลัง ramp 20ms: ค่า = source * 0.5 ตรงๆ
    s = ramp + 8
    np.testing.assert_allclose(out[s:], data[s:6 * BLOCK] * 0.5, atol=1e-6)
    # ช่วง ramp: เริ่มจาก ~1.0 และลดลงทีละน้อย ไม่กระโดด
    assert abs(out[0, 0] - data[0, 0]) < 1e-3
    ratio = out[:ramp, 0] / data[:ramp, 0]
    assert np.all(np.diff(ratio) <= 1e-6)
    assert ratio[-1] == pytest.approx(0.5, abs=0.01)


def test_clock_advances_exactly() -> None:
    eng, _, _ = loaded()
    eng.play(0)
    for k in range(5):
        run(eng, 1)
        pos, _host, rate, playing, gen = eng.clocks[0]._snapshot()
        assert pos == pytest.approx(k * BLOCK / SR, abs=1e-9)
        assert playing and rate == 1.0
        assert gen == eng.decks[0].generation


def test_clock_host_time_includes_latency() -> None:
    eng, _, _ = loaded()
    eng._latency_s = 0.05
    eng.play(0)
    t = time.perf_counter()
    run(eng, 1)
    host = eng.clocks[0]._snapshot()[1]
    assert t + 0.05 <= host <= time.perf_counter() + 0.05


def test_seek_jumps_with_fade_and_generation() -> None:
    eng, data, _ = loaded()
    eng.play(0)
    run(eng, 1)
    gen0 = eng.decks[0].generation
    eng.seek(0, 5.0)
    out = run(eng, 1)
    d = eng.decks[0]
    assert d.generation == gen0 + 1
    fade = int(SR * 0.005)
    target = int(5.0 * SR)
    # ต้น block: ยังเล่นของเดิมแล้ว fade-out ไปถึง 0 ตรงจุดกระโดด
    assert out[0, 0] == pytest.approx(data[BLOCK, 0], abs=1e-6)
    assert abs(out[fade, 0]) < 1e-6
    # fade-in จาก 0 ที่ตำแหน่งใหม่ แล้วเต็มเสียงเป๊ะหลัง fade
    s = 2 * fade
    np.testing.assert_array_equal(out[s:], data[target + fade:target + fade + BLOCK - s])
    assert eng.clocks[0].generation == gen0 + 1
    pos = eng.clocks[0]._snapshot()[0]
    assert pos == pytest.approx(5.0 - fade / SR, abs=1e-6)  # ย้อนไป sample แรกของ block ตามเส้นเวลาใหม่
    assert d.state is DeckState.PLAYING


def test_seek_while_idle_is_immediate() -> None:
    eng, data, _ = loaded()
    eng.seek(0, 2.0)
    run(eng, 1)
    assert eng.clocks[0].generation == 2
    eng.play(0)
    out = run(eng, 1)
    np.testing.assert_array_equal(out, data[2 * SR:2 * SR + BLOCK])


def test_pause_fades_and_resume_continues() -> None:
    eng, data, _ = loaded()
    eng.play(0)
    run(eng, 2)
    eng.pause(0)
    out = run(eng, 1)
    fade = int(SR * 0.005)
    assert abs(out[fade, 0]) < 1e-6 and not out[fade:].any()
    assert eng.decks[0].state is DeckState.PAUSED
    assert not eng.clocks[0].playing
    run(eng, 1)  # block แรกหลังหยุด: ตำแหน่งต้น block คือจุดที่ fade-out จบ
    pos_paused = eng.clocks[0]._snapshot()[0]
    out2 = run(eng, 2)
    assert not out2.any()
    assert eng.clocks[0]._snapshot()[0] == pos_paused  # ตำแหน่งนิ่ง
    eng.play(0)
    out3 = run(eng, 1)
    # ต่อจากจุดที่หยุด (fade-in 5ms แล้วเท่าต้นฉบับ)
    resume_at = eng.decks[0].seg_pos - BLOCK
    s = 2 * fade
    np.testing.assert_array_equal(out3[s:], data[resume_at + s:resume_at + BLOCK])
    assert out3[0, 0] == 0.0


def test_play_at_frame_is_sample_accurate() -> None:
    eng, data, _ = loaded()
    eng.play(0, at_frame=700)
    out = run(eng, 3)
    assert not out[:700].any()
    np.testing.assert_array_equal(out[700:700 + 500], data[:500])
    pos, _h, _r, playing, _g = eng.clocks[0]._snapshot()
    assert playing  # block ที่ 3: กำลังเล่น


def test_play_at_clock_extrapolates_to_start_sample() -> None:
    eng, _, _ = loaded()
    eng.play(0, at_frame=700)
    run(eng, 2)  # block 2 เริ่มเล่นที่ offset 188
    pos, _h, _r, playing, _g = eng.clocks[0]._snapshot()
    assert playing
    assert pos == pytest.approx(-188 / SR, abs=1e-9)


def test_starvation_silence_and_no_advance() -> None:
    eng = make_engine()
    data = make_pcm(4000)
    buf = PcmBuffer(data, SR)
    buf.frames_ready = 1000
    eng.load(0, "v", full_program(buf))
    eng.play(0)
    out1 = run(eng, 1)
    assert np.array_equal(out1, data[:BLOCK])
    out2 = run(eng, 1)
    assert np.array_equal(out2[:488], data[512:1000]) and not out2[488:].any()
    assert eng.stats.starvations == 1
    out3 = run(eng, 1)
    assert not out3.any() and eng.stats.starvations == 2
    assert eng.decks[0].seg_pos == 1000          # ไม่เดินเลย frames_ready
    assert not eng.clocks[0].playing
    buf.frames_ready = 4000                       # decoder ตามมา -> เล่นต่อจากที่ค้าง
    out4 = run(eng, 1)
    assert np.array_equal(out4, data[1000:1000 + BLOCK])


def test_end_of_program_sets_ended() -> None:
    eng = make_engine()
    data = make_pcm(700)
    eng.load(0, "v", full_program(PcmBuffer.from_array(data, SR)))
    eng.play(0)
    out = run(eng, 2)
    assert np.array_equal(out[:700], data) and not out[700:].any()
    assert eng.decks[0].state is DeckState.ENDED
    assert not eng.clocks[0].playing
    assert eng.clocks[0]._snapshot()[0] == pytest.approx(BLOCK / SR, abs=1e-9)  # ตำแหน่ง ณ ต้น block สุดท้าย


def test_end_exactly_on_block_boundary() -> None:
    eng = make_engine()
    eng.load(0, "v", full_program(PcmBuffer.from_array(make_pcm(2 * BLOCK), SR)))
    eng.play(0)
    run(eng, 2)
    assert eng.decks[0].state is DeckState.ENDED
    assert not eng.clocks[0].playing


def test_incomplete_buffer_total_frames_trimmed_when_complete() -> None:
    """memmap ใหญ่กว่าเสียงจริง: complete + total_frames น้อยกว่า src_end -> จบที่ total_frames"""
    eng = make_engine()
    buf = PcmBuffer(make_pcm(2000), SR)
    prog = full_program(buf)  # src_end = 2000
    buf.frames_ready = 900
    buf.total_frames = 900
    buf.complete = True
    eng.load(0, "v", prog)
    eng.play(0)
    run(eng, 2)
    assert eng.decks[0].state is DeckState.ENDED
    assert eng.stats.starvations == 0


def test_ended_play_restarts() -> None:
    eng = make_engine()
    data = make_pcm(300)
    eng.load(0, "v", full_program(PcmBuffer.from_array(data, SR)))
    eng.play(0)
    run(eng, 1)
    assert eng.decks[0].state is DeckState.ENDED
    gen = eng.decks[0].generation
    eng.play(0)
    out = run(eng, 1)
    assert np.array_equal(out[:300], data)
    assert eng.decks[0].generation == gen + 1


def test_exception_in_callback_gives_silence() -> None:
    eng, _, buf = loaded()
    eng.play(0)
    run(eng, 1)
    buf.data = None  # type: ignore[assignment]  # ทำให้ก็อป PCM พัง
    out = np.ones((BLOCK, 2), dtype=np.float32)
    eng._callback(out, BLOCK, None, None)
    assert not out.any()
    assert eng.stats.callback_errors == 1
    assert eng.stats.last_error
    assert eng.frames_rendered == 2 * BLOCK  # เวลา engine เดินต่อ


def test_underflow_status_counted() -> None:
    eng = make_engine()
    out = np.zeros((BLOCK, 2), dtype=np.float32)
    status = types.SimpleNamespace(output_underflow=True)
    eng._callback(out, BLOCK, None, status)
    assert eng.stats.underruns == 1
    eng._callback(out, BLOCK, None, types.SimpleNamespace(output_underflow=False))
    assert eng.stats.underruns == 1


def test_two_decks_summed_and_independent_clocks() -> None:
    eng = make_engine()
    a, b = make_pcm(SR, 0.5), make_pcm(SR, 0.3)
    eng.load(0, "a", full_program(PcmBuffer.from_array(a, SR)))
    eng.load(1, "b", full_program(PcmBuffer.from_array(b, SR)))
    eng.play(0)
    eng.play(1)
    out = run(eng, 2)
    np.testing.assert_allclose(out, (a + b)[:2 * BLOCK], atol=1e-6)
    assert eng.clocks[0].playing and eng.clocks[1].playing
    eng.clear_deck(1)
    run(eng, 1)
    assert eng.decks[1].state is DeckState.EMPTY and not eng.clocks[1].playing


def test_segments_boundary_and_media_rate() -> None:
    eng = make_engine()
    a = PcmBuffer.from_array(make_pcm(1000, 0.5), SR)
    b = PcmBuffer.from_array(make_pcm(3000, 0.4), SR)
    prog = [
        Segment(a, 0, 1000, 0.0, 0.5),        # intro ที่ยืด: เวลาเพลงเดินครึ่งความเร็ว
        Segment(b, 200, 3000, 1000 / SR * 0.5, 1.0),
    ]
    eng.load(0, "v", prog)
    eng.play(0)
    out = run(eng, 4)
    np.testing.assert_array_equal(out[:1000], a.data)
    np.testing.assert_array_equal(out[1000:1000 + 1000], b.data[200:1200])
    # ระหว่าง segment แรก rate = 0.5
    eng2 = make_engine()
    eng2.load(0, "v", prog)
    eng2.play(0)
    run(eng2, 1)
    assert eng2.clocks[0]._snapshot()[2] == 0.5
    run(eng2, 2)  # ผ่านไปที่ segment 2 แล้ว
    assert eng2.clocks[0]._snapshot()[2] == 1.0


def test_seek_maps_media_time_across_segments() -> None:
    eng = make_engine()
    a = PcmBuffer.from_array(make_pcm(SR, 0.5), SR)
    b = PcmBuffer.from_array(make_pcm(SR * 2, 0.4), SR)
    prog = [Segment(a, 0, SR, 0.0, 0.5), Segment(b, 0, 2 * SR, 0.5, 1.0)]
    eng.load(0, "v", prog)
    eng.seek(0, 1.0)  # เลย 0.5 วินาทีแรก -> อยู่ใน segment 2 ที่ 0.5 วินาที
    run(eng, 1)
    d = eng.decks[0]
    assert d.seg_index == 1 and d.seg_pos == SR // 2


def test_gain_lane_ramps() -> None:
    eng, data, _ = loaded()
    lane = AutomationLane.ramp(Param.GAIN, 0, SR, 1.0, 0.0)
    eng.set_lanes(0, [lane])
    eng.play(0)
    out = run(eng, 4)
    assert abs(out[0, 0] - data[0, 0]) < 1e-6
    assert np.max(np.abs(out[-1])) < np.max(np.abs(data[BLOCK * 4 - 1]))
    eng.clear_deck(0)
    run(eng, 1)
    assert not eng.decks[0].lanes


def test_limiter_in_engine_caps_output() -> None:
    eng = make_engine(master_volume=1.0)
    loud = np.full((SR // 2, 2), 3.0, dtype=np.float32)
    eng.load(0, "v", full_program(PcmBuffer.from_array(loud, SR)))
    eng.play(0)
    out = run(eng, 8)
    assert np.max(np.abs(out)) <= eng._limiter.ceiling + 1e-6
    assert eng.stats.limiter_gain_reduction_db > 0


def test_large_callback_is_chunked() -> None:
    eng, data, _ = loaded(frames=40000)
    eng.play(0)
    out = np.zeros((20000, 2), dtype=np.float32)
    eng._callback(out, 20000, None, None)  # > MAX_BLOCK
    assert np.array_equal(out, data[:20000])
    assert eng.stats.callback_errors == 0


def test_render_helper() -> None:
    eng, data, _ = loaded()
    eng.play(0)
    assert np.array_equal(eng.render(256), data[:256])


def test_no_memory_growth_in_callback() -> None:
    eng, _, _ = loaded(frames=SR * 120)
    eng.play(0)
    eng.set_lanes(0, [AutomationLane.ramp(Param.GAIN, 0, SR * 60, 1.0, 0.9)])
    out = np.zeros((BLOCK, 2), dtype=np.float32)
    for _ in range(200):  # วอร์มอัพ
        eng._callback(out, BLOCK, None, None)
    tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        for _ in range(2000):
            eng._callback(out, BLOCK, None, None)
        after, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert after - before < 20_000, f"หน่วยความจำโตใน callback: {after - before} bytes"
    assert eng.stats.callback_errors == 0


def test_callback_time_benchmark() -> None:
    eng, _, _ = loaded(frames=SR * 120)
    eng.play(0)
    out = np.zeros((BLOCK, 2), dtype=np.float32)
    for _ in range(50):
        eng._callback(out, BLOCK, None, None)
    best = 1e9
    for _ in range(3):
        t = time.perf_counter()
        for _ in range(300):
            eng._callback(out, BLOCK, None, None)
        best = min(best, (time.perf_counter() - t) / 300 * 1000)
    assert best < 2.0, f"callback เฉลี่ย {best:.3f} ms ต่อ 512 frame"
    assert eng.stats.max_callback_ms > 0


def test_list_output_devices_tolerates_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        def __getattr__(self, name: str):
            raise RuntimeError("no portaudio")

    monkeypatch.setitem(sys.modules, "sounddevice", Boom())
    assert list_output_devices() == []


def test_list_output_devices_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace(
        query_hostapis=lambda: [{"name": "MME", "default_output_device": 0},
                                {"name": "Windows WASAPI", "default_output_device": 2}],
        query_devices=lambda: [
            {"name": "Mic", "hostapi": 0, "max_output_channels": 0, "default_samplerate": 44100.0},
            {"name": "Spk MME", "hostapi": 0, "max_output_channels": 2, "default_samplerate": 44100.0},
            {"name": "Spk WASAPI", "hostapi": 1, "max_output_channels": 2, "default_samplerate": 48000.0},
        ],
        default=types.SimpleNamespace(device=[0, 1]),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    devs = list_output_devices()
    assert [d.name for d in devs] == ["Spk MME", "Spk WASAPI"]
    assert [d.is_default for d in devs] == [False, True]
    assert devs[1].hostapi == "Windows WASAPI" and devs[1].default_samplerate == 48000.0


def test_watchdog_reopens_stalled_stream(monkeypatch) -> None:
    """callback หยุดเรียก (อุปกรณ์เสียงถูกถอด/แย่ง) -> control thread ต้องเปิด stream ใหม่เอง"""
    import threading
    import time
    from types import SimpleNamespace

    import app.audio.engine as eng_mod

    eng = eng_mod.AudioEngine(eng_mod.EngineConfig())
    eng.start(open_stream=False)
    monkeypatch.setattr(eng_mod, "STALL_TIMEOUT_S", 0.3)
    reopened: list[int] = []
    eng._stream = SimpleNamespace(stop=lambda: None, close=lambda: None)
    monkeypatch.setattr(eng, "_open_stream", lambda ms: reopened.append(ms))
    t = threading.Thread(target=eng._control_loop, daemon=True)
    t.start()
    deadline = time.time() + 3.0
    while not reopened and time.time() < deadline:
        time.sleep(0.05)
    eng._stop_evt.set()
    t.join(1.0)
    assert reopened, "watchdog ไม่เปิด stream ใหม่"
