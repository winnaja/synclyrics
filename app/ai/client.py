"""AiClient — ฝั่ง process หลักที่เปิด/คุย/เฝ้า AI worker (ข้อ 5, 11.2)

- เปิด worker ด้วย multiprocessing (spawn) ตั้ง priority ต่ำกว่า UI/เสียง (psutil BELOW_NORMAL)
- ส่งงานจาก JobScheduler ทีละงาน ผ่าน request queue, รับผลผ่าน event queue (thread ฟังแยก)
- watchdog: ไม่มี heartbeat เกิน models.watchdog_timeout_s หรือ process ตาย -> kill แล้วเปิดใหม่
  งานที่ค้างอยู่ใส่กลับคิว (attempts+1, เกิน 2 ครั้ง = ยอมแพ้ ใช้เวลาแบบประมาณ) เพลงไม่หยุด
- ผลลัพธ์: เขียน DB (alignment_chunks / analysis) แล้วส่ง EventBus
- ไม่มี GPU / ติดตั้ง requirements-ai.txt ไม่ครบ: ทำงานแบบ "ไม่มี AI" (เวลาแบบประมาณล้วน)
"""

from __future__ import annotations

from typing import Any

from app.ai.scheduler import Job, JobScheduler


class AiClient:
    """เฟส 4"""

    def __init__(self, models_config: dict[str, Any]) -> None:
        self.models_config = models_config
        self.scheduler = JobScheduler()
        self.available = False  # True เมื่อ worker ส่ง "ready"

    def start(self) -> None:
        raise NotImplementedError("เฟส 4")

    def stop(self) -> None:
        raise NotImplementedError("เฟส 4")

    def submit(self, job: Job) -> None:
        raise NotImplementedError("เฟส 4")

    def cancel_video(self, video_id: str) -> None:
        raise NotImplementedError("เฟส 4")

    def on_seek(self, video_id: str, position_s: float) -> None:
        """ดันช่วงที่ seek ไปขึ้นหัวคิว"""
        raise NotImplementedError("เฟส 4")
