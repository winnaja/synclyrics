"""สตรีมมาตรฐานของ process"""

from __future__ import annotations

import sys


def ensure_std_streams() -> None:
    """pythonw.exe (เปิดจาก SyncLyrics.exe/ไม่มีคอนโซล) ทำให้ sys.stdout/stderr เป็น None — ไลบรารีที่พิมพ์/แสดง progress (tqdm ใน demucs/huggingface)
    จะพังด้วย "'NoneType' object has no attribute 'write'" จึงต้องมีสตรีมเสมอ"""
    import os

    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if getattr(sys, "stdin", None) is None:
        sys.stdin = open(os.devnull, "r", encoding="utf-8")
