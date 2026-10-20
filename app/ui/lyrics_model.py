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


def _norm_key(text: str) -> str:
    """ข้อความ -> คีย์เทียบ (ไม่สนตัวพิมพ์/เครื่องหมาย/ช่องว่าง)"""
    return "".join(c for c in text.casefold() if c.isalnum())


def word_to_dict(w: Word) -> dict[str, Any]:
    """คำ -> dict สำหรับ QML (เวลา estimated ใช้การเติมสีแบบเดียวกัน)"""
    return {
        "text": w.text,
        "start": float(w.start),
        "end": float(w.end),
        "estimated": w.timing == WordTimingSource.ESTIMATED,
        "trailingSpace": bool(w.trailing_space),
        "emphasis": bool(w.emphasis),
        "curve": list(w.curve) if w.curve else [],
        "background": False,
        "spacer": False,
    }


_OPEN = "(（"
_CLOSE = ")）"


def split_background(words: list[Word]) -> list[dict[str, Any]]:
    """คำในวงเล็บ = เสียงประสาน/เสียงสะท้อน: แยกเป็นแถวเล็กใต้บรรทัดหลัก (แบบ Apple Music) — ใช้เวลารายคำเดิม ไม่เพิ่มจำนวนบรรทัดของ model
    คืนรายการ dict ของ QML: คำหลักก่อน แล้วคำเว้น {"spacer": True} (ดันขึ้นบรรทัดใหม่ใน Flow) แล้วคำเสียงประสาน (background=True) ·
    ตัดเครื่องหมายวงเล็บออกจากข้อความที่แสดง · บรรทัดที่เป็นวงเล็บทั้งบรรทัดถือเป็นบรรทัดปกติ (ไม่เหลือบรรทัดหลักให้แสดง)"""
    main: list[dict[str, Any]] = []
    bg: list[dict[str, Any]] = []
    depth = 0
    for w in words:
        opens = sum(w.text.count(c) for c in _OPEN)
        closes = sum(w.text.count(c) for c in _CLOSE)
        is_bg = depth > 0 or opens > 0
        depth = max(0, depth + opens - closes)
        shown = "".join(ch for ch in w.text if ch not in _OPEN + _CLOSE)
        if not shown.strip():
            continue
        d = word_to_dict(w)
        d["text"] = shown
        d["background"] = is_bg
        (bg if is_bg else main).append(d)
    if not main:   # ทั้งบรรทัดอยู่ในวงเล็บ: แสดงเป็นบรรทัดปกติ
        for d in bg:
            d["background"] = False
        return bg
    if not bg:
        return main
    if main:
        main[-1]["trailingSpace"] = False
    return main + [{"spacer": True, "text": "", "start": 0.0, "end": 0.0, "estimated": False, "trailingSpace": False, "emphasis": False,
                    "background": False}] + bg


def line_to_row(line: Line, gap_after: float = 0.0, gap_start: float | None = None) -> dict[str, Any]:
    """บรรทัด -> แถวของ model (gap_start = เวลาที่ช่วงดนตรีหลังบรรทัดนี้เริ่ม ไม่ระบุ = ท้ายบรรทัด)"""
    return {
        "start": float(line.start),
        "end": float(line.end),
        "voice": line.voice.value,
        "words": split_background(line.words),
        "translation": line.translation or "",
        "romanization": line.romanization or "",
        "text": line.text,
        "gapAfter": gap_after,
        "gapStart": float(line.end if gap_start is None else gap_start),
    }


def lyrics_to_rows(lyrics: Lyrics, vocal_gaps: list[tuple[float, float]] | None = None) -> list[dict[str, Any]]:
    """แปลงเนื้อเพลงทั้งชุดเป็นแถว (เรียงตามเวลาเริ่มอยู่แล้ว) พร้อมคำนวณช่วงดนตรีหลังแต่ละบรรทัด

    vocal_gaps = ช่วงที่ AI ฟังแล้วไม่มีเสียงร้อง (เฟส 4) — ถ้ามี ใช้ตัดสินแทนช่องว่างของเวลาเนื้อเพลง:
    ช่องว่างระหว่างบรรทัดที่ AI ได้ยินเสียงร้องอยู่ (เนื้อเพลงไม่ครบ) ไม่แสดงจุด · ไม่มี = ใช้ช่องว่างจากเวลาเนื้อเพลง (GAP_MIN_S)
    """
    rows: list[dict[str, Any]] = []
    lines = lyrics.lines
    for i, ln in enumerate(lines):
        gap, start = 0.0, None
        if i + 1 < len(lines):
            nxt = lines[i + 1].start
            if vocal_gaps is None:
                g = nxt - ln.end
                gap = g if g > GAP_MIN_S else 0.0
            else:
                best = 0.0
                for gs, ge in vocal_gaps:
                    lo, hi = max(gs, ln.end), min(ge, nxt)
                    if hi - lo > best:
                        best, start = hi - lo, lo
                gap = best if best >= GAP_MIN_S else 0.0
                if gap <= 0.0:
                    start = None
        rows.append(line_to_row(ln, gap, start))
    from app.lyrics.sections import detect_sections

    for row, sec in zip(rows, detect_sections([r["text"] for r in rows], [r["start"] for r in rows], [r["end"] for r in rows])):
        row["section"] = sec      # ท่อนของบรรทัด (ไม่ใช่ role ของ QML ใช้ในการจัดกลุ่มความสว่างเท่านั้น)
    return rows


def edge_gaps(lyrics: Lyrics, vocal_gaps: list[tuple[float, float]] | None, duration: float = 0.0) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """ช่วงดนตรีก่อนบรรทัดแรก (อินโทร) และหลังบรรทัดสุดท้าย (เอาท์โทร) เมื่อ AI บอกว่าไม่มีเสียงร้อง ≥ GAP_MIN_S"""
    if not lyrics.lines or not vocal_gaps:
        return None, None
    first, last = lyrics.lines[0].start, lyrics.lines[-1].end
    intro = outro = None
    for gs, ge in vocal_gaps:
        lo, hi = gs, min(ge, first)
        if lo < first and hi - lo >= GAP_MIN_S and (intro is None or hi - lo > intro[1] - intro[0]):
            intro = (lo, hi)
        lo2, hi2 = max(gs, last), ge if duration <= 0 else min(ge, duration)
        if hi2 - lo2 >= GAP_MIN_S and (outro is None or hi2 - lo2 > outro[1] - outro[0]):
            outro = (lo2, hi2)
    return intro, outro


def _continues(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """บรรทัด b ดูเป็นการร้องต่อจาก a ไหม (ขึ้นต้นด้วยตัวพิมพ์เล็ก/วงเล็บ หรือ a จบด้วยจุลภาค)"""
    bt = str(b.get("text", "")).lstrip()
    if not bt:
        return False
    first = next((c for c in bt if c.isalpha() or c == "("), "")
    if first == "(" or first.islower():
        return True
    return str(a.get("text", "")).rstrip().endswith((",", "、", "，"))


MAX_GROUP_LINES = 3  # ท่อนเดียวกันรวมได้ไม่เกินกี่บรรทัด (กันลูกโซ่ลามทั้งเพลง)


def _linked(rows: list[dict[str, Any]], a: int, gap_s: float) -> bool:
    """บรรทัด a กับ a+1 เป็นท่อนเดียวกันไหม"""
    ra, rb = rows[a], rows[a + 1]
    gap = float(rb["start"]) - float(ra["end"])
    if gap > gap_s:
        return False
    if ra.get("section") is not None and rb.get("section") is not None and ra["section"] != rb["section"]:
        return False                         # คนละท่อน (ขอบท่อนจากโครงสร้างเนื้อเพลง) ไม่รวมกลุ่มความสว่างข้ามกัน
    if gap < -0.1:
        return True                          # เวลาทับกันจริง (เช่นเสียงประสานร้องพร้อมกัน)
    # เวลาของบรรทัดจาก LRC มักติดกันพอดี (จบ = เริ่มบรรทัดถัดไป) จึงใช้ "เวลาติดกัน" อย่างเดียวไม่ได้ ต้องดูเหมือนประโยคต่อกันด้วย
    return rb.get("voice") == "background" or _continues(ra, rb)


def group_rows(rows: list[dict[str, Any]], gap_s: float) -> list[tuple[int, int]]:
    """แบ่งบรรทัดเป็นท่อน [(first, last), ...] จากซ้ายไปขวา — รวมบรรทัดที่ร้องต่อเนื่องกัน ท่อนละไม่เกิน MAX_GROUP_LINES"""
    groups: list[tuple[int, int]] = []
    n = len(rows)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and j - i + 1 < MAX_GROUP_LINES and _linked(rows, j, gap_s):
            j += 1
        groups.append((i, j))
        i = j + 1
    return groups


def group_range(rows: list[dict[str, Any]], i: int, gap_s: float) -> tuple[int, int]:
    """ช่วงบรรทัด [first, last] ที่เป็น "ท่อนเดียวกัน" กับบรรทัด i (ใช้ให้บรรทัดก่อนหน้าในท่อนค้างความสว่าง แล้วจางพร้อมกันเมื่อจบท่อน)"""
    if not (0 <= i < len(rows)):
        return (i, i)
    for lo, hi in group_rows(rows, gap_s):
        if lo <= i <= hi:
            return (lo, hi)
    return (i, i)


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

    names = ("start", "end", "voice", "words", "translation", "romanization", "text", "gapAfter", "gapStart")
    role_ids = {n: int(Qt.ItemDataRole.UserRole) + 1 + i for i, n in enumerate(names)}

    class LyricsModel(QAbstractListModel):
        """model ของบรรทัดเนื้อเพลง อยู่ใน UI thread เท่านั้น"""

        countChanged = Signal()

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self._rows: list[dict[str, Any]] = []
            self._starts: list[float] = []
            self._emph: dict[str, str] = {}      # ข้อความบรรทัด(normalize) -> คำเน้น (จาก AI) ใส่ซ้ำทุกครั้งที่สร้างแถวใหม่

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
            self._mark_emphasis(rows)
            self.beginResetModel()
            self._rows = rows
            self._starts = [r["start"] for r in rows]
            self.endResetModel()
            self.countChanged.emit()

        def retime(self, lyrics: Lyrics, vocal_gaps: list[tuple[float, float]] | None = None) -> None:
            """AI จัดเวลาใหม่ (จำนวนบรรทัดเท่าเดิม): แก้เวลา/คำ/ช่วงดนตรีของแต่ละบรรทัดแทนที่ ไม่รีเซ็ต model (คำแปล/ตำแหน่งเลื่อนคงเดิม)"""
            rows = lyrics_to_rows(lyrics, vocal_gaps)
            self._mark_emphasis(rows)
            if len(rows) != len(self._rows):
                self.set_lyrics(lyrics)
                return
            changed = False
            for i, new in enumerate(rows):
                old = self._rows[i]
                keep_tr, keep_ro = old["translation"], old["romanization"]
                if all(old[k] == new[k] for k in ("start", "end", "words", "gapAfter", "gapStart", "voice")):
                    continue
                new["translation"], new["romanization"] = new["translation"] or keep_tr, new["romanization"] or keep_ro
                self._rows[i] = new
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [role_ids[n] for n in ("start", "end", "voice", "words", "gapAfter", "gapStart", "translation", "romanization")])
                changed = True
            if changed:
                self._starts = [r["start"] for r in self._rows]

        def _mark_emphasis(self, rows: list[dict[str, Any]]) -> bool:
            """ใส่ธง emphasis ให้คำที่ AI เลือกในบรรทัดที่ข้อความตรงกัน (บรรทัดซ้ำ/ฮุกได้ทุกบรรทัด) · คืน True ถ้ามีแถวใดเปลี่ยน"""
            if not self._emph:
                return False
            changed = False
            for row in rows:
                target = self._emph.get(_norm_key(str(row.get("text", ""))))
                if not target:
                    continue
                for w in row["words"]:
                    if not w.get("emphasis") and _norm_key(str(w.get("text", ""))) == target and not w.get("background") and not w.get("spacer"):
                        w["emphasis"] = True
                        changed = True
                        break
            return changed

        def apply_emphasis(self, mapping: dict[str, str]) -> bool:
            """AI เลือกคำเน้นเสร็จ: ใส่ในแถวปัจจุบัน (คำที่ผ่านการจัดเวลา/ตัดบรรทัดแล้วก็ยังตรงด้วยข้อความ)"""
            self._emph = {k: _norm_key(v) for k, v in mapping.items() if k and v}
            changed = False
            for i, row in enumerate(self._rows):
                before = [bool(w.get("emphasis")) for w in row["words"]]
                if self._mark_emphasis([row]) and before != [bool(w.get("emphasis")) for w in row["words"]]:
                    idx = self.index(i, 0)
                    self.dataChanged.emit(idx, idx, [role_ids["words"]])
                    changed = True
            return changed

        def set_translations(self, translations: list[str]) -> bool:
            """ใส่คำแปลทีละบรรทัด (ลำดับตรงกับบรรทัด) คืน True เมื่อจำนวนตรงและมีผล"""
            if len(translations) != len(self._rows):
                return False
            for i, tr in enumerate(translations):
                tr = tr or ""
                if self._rows[i]["translation"] != tr:
                    self._rows[i]["translation"] = tr
                    idx = self.index(i, 0)
                    self.dataChanged.emit(idx, idx, [role_ids["translation"]])
            return True

        def set_gaps(self, lyrics: Lyrics, vocal_gaps: list[tuple[float, float]] | None) -> None:
            """ใส่ช่วงเสียงร้องจาก AI โดยไม่แตะเวลาเดิม (เช่น ตอนเนื้อเพลงไม่ตรงเวอร์ชันและคงเวลาเดิมไว้)"""
            self.retime(lyrics, vocal_gaps)

        def clear(self) -> None:
            self._emph = {}
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
        def line_index_at(self, position: float, lead: float = 0.0) -> int:
            """บรรทัดปัจจุบัน · lead > 0: ถ้าบรรทัดก่อนหน้าจบแล้ว (อยู่ในช่องว่าง) ให้ขึ้นบรรทัดถัดไปล่วงหน้า lead วินาที (เลื่อนจอให้ทันตอนเริ่มร้อง)"""
            i = find_line_index(self._starts, position)
            if lead > 0.0:
                j = find_line_index(self._starts, position + lead)
                if j > i and (i < 0 or position >= float(self._rows[i]["end"]) - 0.05):
                    return j
            return i

        def group_range(self, i: int, gap_s: float) -> tuple[int, int]:
            return group_range(self._rows, i, gap_s)

        def line_count(self) -> int:
            return len(self._rows)

    _MODEL_CLASS = LyricsModel
    return LyricsModel
