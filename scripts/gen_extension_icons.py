"""สร้างไอคอนส่วนขยาย (วาดเอง: แท่งคลื่นเสียง 3 แท่ง) 3 สถานะ x 4 ขนาด -> extension/icons/

สถานะ: on = สีปกติ (เชื่อมแล้ว), off = สีเทา (โปรแกรมปิดอยู่), error = สีปกติ + จุดแดง
รัน: scripts/gen_extension_icons.py ด้วย python ของ .venv
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter

OUT = Path(__file__).resolve().parents[1] / "extension" / "icons"
SIZES = (16, 32, 48, 128)
PALETTE = {
    "on": (QColor("#8B6CFF"), QColor("#4C7DFF")),
    "off": (QColor("#9A9AA6"), QColor("#6E6E78")),
    "error": (QColor("#8B6CFF"), QColor("#4C7DFF")),
}


def draw(state: str, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    a, b = PALETTE[state]
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, a)
    g.setColorAt(1, b)
    p.setBrush(QBrush(g))
    p.setPen(Qt.PenStyle.NoPen)
    r = size * 0.22
    p.drawRoundedRect(QRectF(0, 0, size, size), r, r)
    p.setBrush(QColor("white"))
    bw = size * 0.14
    gap = size * 0.09
    heights = (0.34, 0.62, 0.44)
    x0 = (size - (3 * bw + 2 * gap)) / 2
    for i, h in enumerate(heights):
        hh = size * h
        p.drawRoundedRect(QRectF(x0 + i * (bw + gap), (size - hh) / 2, bw, hh), bw / 2, bw / 2)
    if state == "error":
        d = size * 0.38
        p.setBrush(QColor("#FF3B30"))
        p.setPen(QColor("white"))
        p.drawEllipse(QRectF(size - d, size - d, d, d))
    p.end()
    return img


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])  # noqa: F841
    OUT.mkdir(parents=True, exist_ok=True)
    for state in PALETTE:
        for s in SIZES:
            draw(state, s).save(str(OUT / f"{state}-{s}.png"))
    print("สร้างไอคอน", len(PALETTE) * len(SIZES), "ไฟล์ที่", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
