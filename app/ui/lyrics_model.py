"""LyricsModel — QAbstractListModel ของบรรทัดเนื้อเพลงสำหรับ QML (ส่วนที่ 3.3)

role ต่อบรรทัด: start, end, voice, words (list ของ {text, start, end, estimated, trailingSpace}),
translation, romanization, text, gapAfter (ช่องว่างถึงบรรทัดถัดไป เฉพาะที่ยาวเกิน GAP_MIN_S)
อัปเกรดเวลาจาก AI ทีละช่วง (LYRICS_TIMING_UPDATED): emit dataChanged เฉพาะบรรทัดที่เปลี่ยน
QML ทำ morph เวลาเก่า -> ใหม่แบบ smooth (ห้ามกระโดด)

ส่วน logic ล้วน (lyrics_to_rows, find_line_index) ไม่พึ่ง Qt เพื่อ test ได้ตรงๆ
คลาส Qt สร้างแบบ lazy ใน make_lyrics_model_class() — ห้าม import PySide6 ตอน import module
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Any

from app.core.models import Line, Lyrics, Word, WordTimingSource

# ช่องว่างระหว่างบรรทัดที่ยาวกว่านี้ถือเป็นช่วงดนตรี (ข้อ 3.3)
GAP_MIN_S = 4.0


def word_to_dict(w: Word) -> dict[str, Any]:
    """คำ -> dict สำหรับ QML (เวลา estimated ใช้การเติมสีแบบเดียวกัน)"""
    return {
        "text": w.text,
        "start": float(w.start),
        "end": float(w.end),
        "estimated": w.timing == WordTimingSource.ESTIMATED,
        "trailingSpace": bool(w.trailing_space),
    }


def line_to_row(line: Line, gap_after: float = 0.0) -> dict[str, Any]:
    """บรรทัด -> แถวของ model"""
    return {
        "start": float(line.start),
        "end": float(line.end),
        "voice": line.voice.value,
        "words": [word_to_dict(w) for w in line.words],
        "translation": line.translation or "",
        "romanization": line.romanization or "",
        "text": line.text,
        "gapAfter": gap_after,
    }


def lyrics_to_rows(lyrics: Lyrics) -> list[dict[str, Any]]:
    """แปลงเนื้อเพลงทั้งชุดเป็นแถว (เรียงตามเวลาเริ่มอยู่แล้ว) พร้อมคำนวณช่วงดนตรีหลังแต่ละบรรทัด"""
    rows: list[dict[str, Any]] = []
    lines = lyrics.lines
    for i, ln in enumerate(lines):
        gap = 0.0
        if i + 1 < len(lines):
            g = lines[i + 1].start - ln.end
            gap = g if g > GAP_MIN_S else 0.0
        rows.append(line_to_row(ln, gap))
    return rows


def find_line_index(starts: list[float], position: float) -> int:
    """บรรทัดปัจจุบัน = บรรทัดสุดท้ายที่ start <= position (bisect) คืน -1 ถ้ายังไม่ถึงบรรทัดแรก"""
    return bisect_right(starts, position) - 1


_MODEL_CLASS: type | None = None


def make_lyrics_model_class() -> type:
    """สร้างคลาส LyricsModel (สืบทอด QAbstractListModel) ครั้งเดียวแล้วจำไว้"""
    global _MODEL_CLASS
    if _MODEL_CLASS is not None:
        return _MODEL_CLASS

    from PySide6.QtCore import (
        QAbstractListModel,
        QByteArray,
        QModelIndex,
        Qt,
        Signal,
    )

    names = ("start", "end", "voice", "words", "translation", "romanization", "text", "gapAfter")
    role_ids = {n: int(Qt.ItemDataRole.UserRole) + 1 + i for i, n in enumerate(names)}

    class LyricsModel(QAbstractListModel):
        """model ของบรรทัดเนื้อเพลง อยู่ใน UI thread เท่านั้น"""

        countChanged = Signal()

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._rows: list[dict[str, Any]] = []
            self._starts: list[float] = []

        # ---------- QAbstractListModel ----------
        def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
            return 0 if parent.isValid() else len(self._rows)

        def roleNames(self) -> dict[int, QByteArray]:
            return {rid: QByteArray(n.encode()) for n, rid in role_ids.items()}

        def data(self, index: QModelIndex, role: int = 0) -> Any:
            if not index.isValid() or not (0 <= index.row() < len(self._rows)):
                return None
            row = self._rows[index.row()]
            for n, rid in role_ids.items():
                if rid == role:
                    return row[n]
            return None

        # ---------- การแก้ข้อมูล ----------
        def set_lyrics(self, lyrics: Lyrics) -> None:
            """แทนที่เนื้อเพลงทั้งชุด"""
            rows = lyrics_to_rows(lyrics)
            self.beginResetModel()
            self._rows = rows
            self._starts = [r["start"] for r in rows]
            self.endResetModel()
            self.countChanged.emit()

        def clear(self) -> None:
            if not self._rows:
                return
            self.beginResetModel()
            self._rows = []
            self._starts = []
            self.endResetModel()
            self.countChanged.emit()

        def update_words(self, start: float, end: float, words: list[Word]) -> None:
            """เฟส 4 (ตัวยึดที่ใช้งานได้): แทนคำของบรรทัดที่เวลาเริ่มอยู่ในช่วง [start, end]
            emit dataChanged เฉพาะบรรทัดที่คำเปลี่ยนจริง"""
            if not self._rows or not words:
                return
            lo = max(0, bisect_right(self._starts, start - 1e-3) - 1)
            for i in range(lo, len(self._rows)):
                row = self._rows[i]
                if row["start"] > end + 1e-3:
                    break
                if row["start"] < start - 1e-3:
                    continue
                inside = [w for w in words if row["start"] - 1e-3 <= w.start <= row["end"] + 1e-3]
                if not inside:
                    continue
                new_words = [word_to_dict(w) for w in inside]
                if new_words == row["words"]:
                    continue
                row["words"] = new_words
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [role_ids["words"]])

        # ---------- ค้นหา ----------
        def line_index_at(self, position: float) -> int:
            return find_line_index(self._starts, position)

        def line_count(self) -> int:
            return len(self._rows)

    _MODEL_CLASS = LyricsModel
    return LyricsModel
