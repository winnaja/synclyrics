"""ถอดรหัสไฟล์เสียงที่โหลดมา (opus/m4a ...) เป็น PCM ใน numpy ด้วย ffmpeg — ใช้เฉพาะใน AI worker

แอปไม่เล่นเสียงเอง: ไฟล์ที่โหลดจาก YouTube ใช้เพื่อวิเคราะห์อย่างเดียว (Demucs/Whisper)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW — ไม่ให้หน้าต่าง console โผล่


class AudioError(RuntimeError):
    """ถอดรหัสไม่ได้"""


def ffmpeg_exe() -> str:
    from app.audio.decoder import find_ffmpeg

    p = find_ffmpeg()
    if p is None:
        raise AudioError("ไม่พบ ffmpeg")
    return str(p)


def decode(src: Path | str, sample_rate: int, channels: int, max_seconds: float | None = None) -> np.ndarray:
    """คืน float32 รูปร่าง (n, channels) · max_seconds = ตัดทิ้งหลังเท่านี้ (กันไฟล์ยาวผิดปกติกินแรม)"""
    cmd = [ffmpeg_exe(), "-v", "error", "-nostdin", "-i", str(src), "-vn", "-ac", str(channels), "-ar", str(sample_rate)]
    if max_seconds:
        cmd += ["-t", f"{max_seconds:.1f}"]
    cmd += ["-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    if proc.returncode != 0 or not proc.stdout:
        raise AudioError(f"ffmpeg ถอดรหัสไม่สำเร็จ: {proc.stderr.decode('utf-8', 'replace')[-300:]}")
    usable = len(proc.stdout) // (4 * channels) * (4 * channels)
    return np.frombuffer(proc.stdout[:usable], dtype=np.float32).reshape(-1, channels).copy()
