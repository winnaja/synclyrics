"""ลำดับงานของ AI worker (job_align_song) ด้วยโมดูลโมเดลจำลอง — ไม่ใช้ torch/GPU/ffmpeg/เครือข่าย

ตรวจ: เริ่มจากช่วงที่กำลังฟัง · ส่งผลทยอยทุกช่วง · ผลสุดท้ายถูก · cache ทำให้ครั้งที่สองไม่เรียกโมเดล · ยกเลิกกลางงานหยุดจริง · ไม่มีเนื้อเพลง = ถอดเสียง
"""

from __future__ import annotations

import queue
from pathlib import Path

import numpy as np
import pytest

from app.ai import worker as wk
from app.ai.pipeline import audio, stems, transcribe
from app.ai.pipeline.match import TWord

SR = 8000
LYRICS = ["walking down the empty street", "city lights are fading slow", "i can hear your voice again",
          "echoing through the night", "hold me close and never let go", "we are dancing in the rain"]
# เสียงจริง: บรรทัดที่ k เริ่มที่ 12 + k*10 วิ (ต้นฉบับเลื่อนไป -7 วิ) คำละ 1 วิ
TRUE = [12.0 + k * 10.0 for k in range(len(LYRICS))]
DURATION = 80.0


class Harness:
    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch, with_lyrics: bool = True) -> None:
        self.rq: queue.Queue = queue.Queue()
        self.eq: queue.Queue = queue.Queue()
        cfg = {"models": {"analysis": {"window_s": 30.0, "context_s": 3.0, "sample_rate": SR, "max_song_s": 900, "min_coverage": 0.25,
                                       "algo_version": 1, "batched_whisper": False, "ctc_first": False},
                          "demucs": {"enabled": True}, "whisper": {"model": "fake", "keep_loaded": True}, "align": {"enabled": False}},
               "stems_dir": str(tmp / "stems")}
        self.w = wk.Worker(self.rq, self.eq, cfg)
        self.w.device = "cpu"
        self.w._demucs = object()
        self.w._whisper = object()
        self.w._mms_failed = True
        self.calls: list[tuple[str, float]] = []
        self.cancel_after: int | None = None
        outer = self

        monkeypatch.setattr(audio, "decode", lambda *a, **k: np.zeros((int(DURATION * SR), 2), dtype=np.float32))
        monkeypatch.setattr(stems, "separate_vocals", lambda model, seg, dev, cfg: seg)
        monkeypatch.setattr(stems, "to_mono_16k", lambda x, sr, device="cpu": np.zeros(int(len(x) / sr * 16000), dtype=np.float32))

        def fake_transcribe(model, a, language, cfg, t_offset=0.0, prompt=None):
            outer.calls.append(("transcribe", t_offset))
            if outer.cancel_after is not None and len(outer.calls) >= outer.cancel_after:
                outer.rq.put({"type": "cancel", "payload": {"job_ids": ["j1"]}})
            end = t_offset + len(a) / 16000
            words = []
            for k, line in enumerate(LYRICS):
                for wi, word in enumerate(line.split()):
                    s = TRUE[k] + wi
                    if t_offset - 0.5 <= s and s + 0.9 <= end + 0.5:
                        words.append(TWord(word, s, s + 0.9, 0.9))
            return words, "en"

        monkeypatch.setattr(transcribe, "transcribe_window", fake_transcribe)
        self.lines = [{"words": ln.split(), "start": TRUE[k] - 7.0, "end": TRUE[k] - 7.0 + 5.0} for k, ln in enumerate(LYRICS)] if with_lyrics else []

    def payload(self, hint: float = 0.0) -> dict:
        return {"job_id": "j1", "video_id": "vid00000001", "audio_path": "x.webm", "lines": self.lines, "language": "en" if self.lines else None,
                "start_hint": hint}

    def events(self) -> list[dict]:
        out = []
        while not self.eq.empty():
            out.append(self.eq.get())
        return out


def results(evs: list[dict], kind: str) -> list[dict]:
    return [e["payload"]["data"] for e in evs if e["type"] == "result" and e["payload"]["kind"] == kind]


def test_progressive_partials_then_final_with_correct_times(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.w.job_align_song(h.payload())
    evs = h.events()
    parts, final = results(evs, "align_partial"), results(evs, "align_final")
    assert len(parts) == 3 and len(final) == 1                       # 80 วิ / 30 = 3 ช่วง
    assert [p["windows_done"] for p in parts] == [1, 2, 3]
    f = final[0]
    assert f["mode"] == "match" and f["coverage"] > 0.9 and not f["version_mismatch"]
    for ln, t in zip(f["lines"], TRUE):
        assert ln["resolved"] and abs(ln["start"] - t) < 0.3
    assert abs(f["offset_s"] - 7.0) < 0.3
    assert (tmp_path / "stems" / "vid00000001" / "transcript.json").exists()


def test_starts_from_the_window_being_listened_to(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.w.job_align_song(h.payload(hint=65.0))
    assert [round(off) for _n, off in h.calls[:3]] == [57, 0, 27]    # ช่วง 60-80 (+บริบท) ก่อน แล้ววนกลับไปเริ่มจากต้นเพลงไล่ไปข้างหน้า


def test_second_run_uses_cached_transcript_without_models(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.w.job_align_song(h.payload())
    h.events()
    first_calls = len(h.calls)
    h2 = Harness(tmp_path, monkeypatch)                              # worker ใหม่ ไฟล์ cache เดิม
    h2.w.job_align_song(h2.payload())
    assert h2.calls == [] and first_calls == 3
    f = results(h2.events(), "align_final")[0]
    assert abs(f["lines"][0]["start"] - TRUE[0]) < 0.3 and f["duration"] == pytest.approx(DURATION)


def test_cancel_stops_between_windows(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.cancel_after = 1
    with pytest.raises(wk._Cancelled):
        h.w.job_align_song(h.payload())
    assert len(h.calls) == 1 and results(h.events(), "align_final") == []


def test_no_lyrics_transcribes_into_lines(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, with_lyrics=False)
    h.w.job_align_song(h.payload())
    f = results(h.events(), "align_final")[0]
    assert f["mode"] == "transcribe" and len(f["lines"]) >= 4
    assert f["lines"][0]["text_words"][:2] == ["walking", "down"] and abs(f["lines"][0]["start"] - TRUE[0]) < 0.01


def test_wrong_lyrics_flag_version_mismatch(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.lines = [{"words": "totally unrelated song text here".split(), "start": 1.0 + 8 * k, "end": 5.0 + 8 * k} for k in range(6)]
    h.w.job_align_song(h.payload())
    f = results(h.events(), "align_final")[0]
    assert f["version_mismatch"] is True and f["coverage"] < 0.25


def test_too_long_audio_fails_without_crashing(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.w.mcfg["analysis"]["max_song_s"] = 30
    h.w.job_align_song(h.payload())
    evs = h.events()
    assert any(e["type"] == "failed" and e["payload"]["recoverable"] is False for e in evs)


def test_run_loop_handles_failures_and_shutdown(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    monkeypatch.setattr(h.w, "setup", lambda: None)
    h.w.vram_mb = lambda: (0, 0)                                     # type: ignore[method-assign]
    monkeypatch.setattr(audio, "decode", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ffmpeg พัง")))
    h.rq.put({"type": "align_song", "payload": h.payload()})
    h.rq.put({"type": "shutdown", "payload": {}})
    h.w.run()
    types = [e["type"] for e in h.events()]
    assert "ready" in types and "failed" in types                    # งานพังไม่ทำให้ worker ตาย และรับ shutdown ต่อได้


def test_reordered_song_is_reconstructed_in_the_order_it_is_sung(tmp_path, monkeypatch):
    """รีมิกซ์: เสียงร้องเรียงกลับด้านจากเนื้อเพลง -> จับคู่เรียงลำดับไม่ได้ -> สร้างบรรทัดตามเสียงจริง ใช้ข้อความเนื้อเพลงที่ตรง"""
    import app.ai.pipeline.match as M

    saved = list(TRUE)
    TRUE[:] = [62.0, 52.0, 42.0, 32.0, 22.0, 12.0]
    real = M.transcript_reliable
    monkeypatch.setattr(M, "transcript_reliable", lambda w, min_words=10, min_prob=0.55: real(w, min_words, min_prob))
    try:
        h = Harness(tmp_path, monkeypatch)
        h.w.job_align_song(h.payload())
        f = results(h.events(), "align_final")[0]
    finally:
        TRUE[:] = saved
    assert f["mode"] == "reconstruct" and f["coverage"] > 0.9 and f["version_mismatch"] is False
    starts = [ln["start"] for ln in f["lines"]]
    assert starts == sorted(starts) and len(f["lines"]) == 6
    assert [ln["src"] for ln in f["lines"]] == [[5], [4], [3], [2], [1], [0]]       # ลำดับที่ร้องจริง = กลับด้านจากเนื้อเพลง
    assert abs(starts[0] - 12.0) < 0.3
