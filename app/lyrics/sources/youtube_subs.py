"""คำบรรยายของวิดีโอผ่าน yt-dlp — เฉพาะที่คนทำ (ไม่ใช่ auto-generated) (ข้อ 4.2 ข้อ 2)

คำบรรยายของ MV มักตรงเวลากับวิดีโอนี้พอดี (รวมช่วงเปิดเรื่องของ MV) จึงได้คะแนนเรื่องเวลาดี
แต่ต้องกรองที่ไม่ใช่เนื้อเพลงออก เช่น [Music], ♪ อย่างเดียว, คำแปลอย่างเดียว
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.lyrics.sources.base import LyricsCandidate, LyricsQuery, LyricsSource

if TYPE_CHECKING:
    import httpx


class YouTubeSubtitlesSource(LyricsSource):
    name = "youtube_subs"
    display_name = "คำบรรยาย YouTube"
    timeout_s = 8.0

    async def search(self, query: LyricsQuery, client: "httpx.AsyncClient") -> list[LyricsCandidate]:
        # query.extras["subtitles"] มาจาก VideoInfo.subtitles (โหลดมาพร้อมข้อมูลวิดีโอแล้ว)
        raise NotImplementedError("เฟส 1")


SOURCE = YouTubeSubtitlesSource
