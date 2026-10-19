"""QQ Music — API ไม่เป็นทางการ (ข้อ 4.2 ข้อ 5)

มักมีเวลาระดับคำ (QRC — เข้ารหัส ต้องถอดก่อน parse) + คำแปล
API เปลี่ยนได้ทุกเมื่อ: พังแล้วข้ามเงียบๆ และปิดได้ในหน้าตั้งค่า
parser ของ QRC อยู่ที่ app/lyrics/parsers/qrc.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx


class QQMusicSource(LyricsSource):
    name = "qqmusic"
    display_name = "QQ Music"
    unofficial = True
    timeout_s = 6.0

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        raise NotImplementedError("เฟส 1")


SOURCE = QQMusicSource
