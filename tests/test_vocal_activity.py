

def test_last_word_is_not_dragged_to_next_lines_onset():
    """คำท้ายบรรทัดที่ end ถูกต่อไปเกือบถึงบรรทัดถัดไป ห้ามถูกลากไปเริ่มที่จุดเริ่มเสียงของบรรทัดถัดไป (คำสุดท้ายขึ้นสีช้าเกือบทุกเพลง)"""
    import numpy as np

    from app.ai.pipeline.vocal_activity import snap_line_onset

    sr = 16000
    rng = np.random.default_rng(0)
    x = np.zeros(sr * 17, dtype=np.float32)
    x[sr * 10:sr * 13] = rng.normal(0, 0.3, sr * 3)        # ร้องอยู่ 10-13 วิ (รวมคำท้าย)
    x[int(sr * 14.5):sr * 16] = rng.normal(0, 0.3, int(sr * 1.5))   # บรรทัดถัดไปเริ่ม 14.5 วิ หลังเว้น
    words = [[10.0, 11.0, 0.9], [11.0, 12.0, 0.9], [12.0, 14.4, 0.9]]   # คำท้ายถูกต่อ end ไป 14.4
    out = snap_line_onset(words, x)
    assert out[-1][0] < 13.0, f"คำท้ายถูกลากไปเริ่มที่ {out[-1][0]} (บรรทัดถัดไป)"
