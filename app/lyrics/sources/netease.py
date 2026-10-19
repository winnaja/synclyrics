"""NetEase Cloud Music — API ไม่เป็นทางการ (ข้อ 4.2 ข้อ 4)

มักมีเวลาระดับคำ (YRC) + คำแปล (tlyric) + romanization (romalrc)
API เปลี่ยนได้ทุกเมื่อ: พังแล้วข้ามเงียบๆ (unofficial = True) และปิดได้ในหน้าตั้งค่า
parser ของ YRC อยู่ที่ app/lyrics/parsers/yrc.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx


class NeteaseSource(LyricsSource):
    name = "netease"
    display_name = "NetEase"
    unofficial = True
    timeout_s = 6.0

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        raise NotImplementedError("เฟส 1")


SOURCE = NeteaseSource
