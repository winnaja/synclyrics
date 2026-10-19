"""จุดเริ่มของ AI worker process (ข้อ 5.3)

worker_main(requests, events, config) รันใน process แยก:
  1. ตั้ง priority ต่ำ, เลือก device (cuda/cpu), torch.inference_mode, cudnn.benchmark
  2. โหลดโมเดลค้างใน VRAM (Demucs fp16, MMS_FA fp16; whisper ตาม keep_loaded) + warm-up เสียงเงียบ
  3. ส่ง "ready" แล้ววนรับงาน: ทำทีละงาน ส่ง "progress"/"result"/"failed"
  4. heartbeat ทุก 1 วิ จาก thread แยก (watchdog ฝั่ง client ใช้)
  5. VRAM ใกล้งบ: ลดขนาดโมเดล (เช่น whisper -> int8_float16) แล้วส่ง "degraded"
  6. จบแต่ละเพลง: torch.cuda.empty_cache()

กฎ: worker ไม่แตะ SQLite, ไม่ถือ state สำคัญ (ฆ่าทิ้งได้ทุกเมื่อ)
อ่านเสียงจากไฟล์ .f32 ใน cache (np.memmap) เขียน stems ลง cache/stems/<videoId>/
ห้าม import ไฟล์นี้จาก process หลัก (ยกเว้นส่งชื่อฟังก์ชันให้ multiprocessing)
"""

from __future__ import annotations

from typing import Any


def worker_main(requests: Any, events: Any, config: dict[str, Any]) -> None:
    """เฟส 4"""
    raise NotImplementedError("เฟส 4")
