"""PlayerController — ขั้นตอนตั้งแต่กดเล่นจนเสียงออกและเนื้อเพลงขึ้น (ARCHITECTURE.md §2)

play(track) (โหมดแอป):
  t=0     ยกเลิกงานของเพลงเก่า (ถ้าข้าม), เปิดดู cache ใน DB
  ขนาน:   [IO] yt-dlp info -> download bestaudio -> decoder (PCM ทยอยลง memmap)
          [IO] LyricsService.find -> เวลาแบบประมาณ -> LYRICS_READY  (เป้า < 1 วิ ถ้ามี cache/แหล่งตอบเร็ว)
          [IO] artwork + palette
  ~2 วิ   PCM พอ ~2 วิ -> engine.load + play (เป้า: เริ่มภายใน 3 วิ)
  ต่อไป   AI: ช่วงแรก 20-30 วิ (PLAYING_SOON) แล้วทยอยต่อ นำหน้าตัวเล่น >= 30 วิ
          AI: analyze_full (CURRENT_ANALYSIS)
  50%     (และ AI เพลงปัจจุบันเสร็จ) -> Preloader เตรียมเพลงถัดไปครบ (ข้อ 6)

ตัวเล่นห้ามรอ AI เด็ดขาด — ช่วงที่ AI ยังไม่เสร็จใช้เวลาแบบประมาณ
"""

from __future__ import annotations

from typing import Any

from app.core.models import TrackRef


class PlayerController:
    """เฟส 1 (deck เดียว) -> เฟส 5 (2 deck + preload) -> เฟส 6 (AutoMix)"""

    def __init__(self, engine: Any, bus: Any, lyrics: Any, media: Any, ai: Any, db: Any, settings: Any) -> None:
        self.engine = engine
        self.bus = bus
        self.lyrics = lyrics
        self.media = media
        self.ai = ai
        self.db = db
        self.settings = settings
        self.active_deck = 0

    def play(self, track: TrackRef, start_at: float = 0.0) -> None:
        raise NotImplementedError("เฟส 1")

    def toggle_pause(self) -> None:
        raise NotImplementedError("เฟส 1")

    def seek(self, position_s: float) -> None:
        raise NotImplementedError("เฟส 1")

    def skip_next(self) -> None:
        raise NotImplementedError("เฟส 5")

    def skip_mix(self) -> None:
        """ปุ่ม "ข้ามการมิกซ์": ตัดไปเพลง B ทันทีแบบสั้น (รางวัล -0.8)"""
        raise NotImplementedError("เฟส 6")
