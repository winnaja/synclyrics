"""เตรียมสภาพแวดล้อมของ AI worker: ต่อ site-packages ของ AI เข้า sys.path และกำหนดที่เก็บน้ำหนักโมเดล

ใช้ใน worker process เท่านั้น (process หลักห้าม import torch) — เรียกก่อน import torch/faster_whisper/demucs
เหตุผลที่แยก site-packages: torch+CUDA กินหลาย GB ติดตั้งไว้ไดรฟ์อื่นได้ (ตั้ง models.yaml: site_dir) ไม่ต้องอยู่ใน .venv หลัก
ต่อท้าย sys.path (ไม่ใช่นำหน้า) เพื่อให้ numpy/pydantic ฯลฯ ใช้ตัวของ .venv หลักเสมอ ไม่ชนเวอร์ชันกัน
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def setup_ai_environment(config: dict[str, Any]) -> dict[str, str]:
    """คืนสรุปสิ่งที่ตั้ง (ใส่ log/หน้า debug ได้) · ไม่มีโฟลเดอร์ที่ตั้งไว้ = ข้ามเงียบๆ"""
    info: dict[str, str] = {}
    site = str(config.get("site_dir") or "")
    if site and Path(site).is_dir() and site not in sys.path:
        sys.path.append(site)
        info["site_dir"] = site
    model_dir = str(config.get("model_dir") or "")
    if model_dir:
        Path(model_dir).mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", model_dir)
        os.environ.setdefault("TORCH_HOME", str(Path(model_dir) / "torch"))
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        info["model_dir"] = model_dir
    # หน้าต่างโหลดโมเดลครั้งแรกต้องออกเน็ต แต่หลังจากนั้นไม่ควรเช็กอัปเดตโมเดลทุกครั้ง
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    return info
