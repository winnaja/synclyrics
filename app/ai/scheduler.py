"""คิวงาน AI ตามความสำคัญ + วางแผนช่วงสำหรับประมวลผลแบบทยอย (ข้อ 5.2, 5.3)

อยู่ใน process หลัก (ไม่ใช่ worker) เพื่อให้ worker restart ได้โดยไม่เสียคิว
GPU ทำทีละงาน: scheduler ส่งงานให้ worker ครั้งละ 1 งาน รอผล แล้วค่อยส่งงานถัดไป
(ยกเว้นงานที่ worker ทำบน CPU ได้พร้อมกัน — ตัดสินในเฟส 4)

ความสำคัญ (เลขน้อย = ด่วนกว่า):
  0 PLAYING_SOON     ช่วงที่กำลังจะเล่น (ตัวเล่นตามทันหรือ seek มา)
  1 CURRENT_REST     ส่วนที่เหลือของเพลงปัจจุบัน
  2 CURRENT_ANALYSIS วิเคราะห์ beat/ท่อน/key ทั้งเพลง (ต้องเสร็จก่อนจุดมิกซ์ 30 วิ)
  3 NEXT_TRACK       เตรียมเพลงถัดไป
ภายในระดับเดียวกัน: ช่วงที่เริ่มเร็วกว่าในเพลงทำก่อน
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Priority(IntEnum):
    PLAYING_SOON = 0
    CURRENT_REST = 1
    CURRENT_ANALYSIS = 2
    NEXT_TRACK = 3


@dataclass(slots=True)
class Job:
    job_id: str
    kind: str                      # ชนิดใน app.core.messages.AI_REQUESTS
    video_id: str
    priority: Priority
    start: float = 0.0             # ช่วงในเพลง (วินาที) — ใช้เรียงและ reprioritize ตอน seek
    end: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0


class JobScheduler:
    """priority queue ที่ยกเลิกงานตามเพลงได้ และดันช่วงขึ้นหัวคิวได้ตอน seek (thread เดียวใช้)"""

    def __init__(self) -> None:
        self._heap: list[tuple[int, float, int, str]] = []
        self._jobs: dict[str, Job] = {}
        self._seq = itertools.count()

    def __len__(self) -> int:
        return len(self._jobs)

    def push(self, job: Job) -> None:
        self._jobs[job.job_id] = job
        heapq.heappush(self._heap, (int(job.priority), job.start, next(self._seq), job.job_id))

    def pop(self) -> Job | None:
        """งานถัดไปที่ควรทำ (ข้ามรายการที่ถูกยกเลิก/เปลี่ยนความสำคัญแล้ว)"""
        while self._heap:
            prio, start, _, job_id = heapq.heappop(self._heap)
            job = self._jobs.get(job_id)
            if job is None or int(job.priority) != prio or job.start != start:
                continue  # รายการเก่าที่ค้างใน heap
            del self._jobs[job_id]
            return job
        return None

    def cancel_video(self, video_id: str) -> list[str]:
        """ยกเลิกงานทั้งหมดของเพลงที่ถูกข้าม คืน job_id ที่ยกเลิก (ต้องแจ้ง worker ด้วยถ้ากำลังทำ)"""
        ids = [j.job_id for j in self._jobs.values() if j.video_id == video_id]
        for i in ids:
            del self._jobs[i]
        return ids

    def promote(self, video_id: str, around_s: float, window_s: float) -> int:
        """seek ไปช่วงที่ยังไม่คำนวณ: งานที่ครอบ [around_s, around_s+window_s] ขึ้นเป็น PLAYING_SOON"""
        n = 0
        for job in self._jobs.values():
            if job.video_id == video_id and job.end > around_s and job.start < around_s + window_s:
                if job.priority != Priority.PLAYING_SOON:
                    job.priority = Priority.PLAYING_SOON
                    heapq.heappush(self._heap, (0, job.start, next(self._seq), job.job_id))
                    n += 1
        return n

    def pending(self) -> list[Job]:
        """รายการงานที่ค้าง (สำหรับหน้า debug) เรียงตามลำดับที่จะทำ"""
        return sorted(self._jobs.values(), key=lambda j: (int(j.priority), j.start))


def plan_chunks(
    lines: list[tuple[float, float]],
    duration: float,
    first_chunk_s: float = 25.0,
    chunk_s: float = 20.0,
    overlap_s: float = 2.5,
) -> list[tuple[float, float]]:
    """แบ่งเพลงเป็นช่วงสำหรับ AI โดยไม่ตัดกลางบรรทัดเนื้อเพลง (ข้อ 5.2)

    lines: ช่วงเวลาของแต่ละบรรทัด (เรียงตามเวลา) — ใช้เวลาแบบประมาณได้
    คืนรายการ (start, end) ที่ครอบคลุม 0..duration, ช่วงติดกันซ้อนกันอย่างน้อย ~overlap_s
    และทุกบรรทัดอยู่ครบในอย่างน้อยหนึ่งช่วง
    """
    if duration <= 0:
        return []
    chunks: list[tuple[float, float]] = []
    t = 0.0
    target = first_chunk_s
    while True:
        end = min(duration, t + target)
        for ls, le in lines:  # บรรทัดที่คร่อมขอบ -> ยืดไปจบบรรทัด
            if ls < end < le:
                end = min(duration, le)
                break
        chunks.append((t, end))
        if end >= duration:
            break
        nxt = max(t + 1.0, end - overlap_s)
        for ls, le in lines:  # จุดเริ่มช่วงถัดไปตกกลางบรรทัด -> ถอยไปต้นบรรทัด
            if ls < nxt < le and ls > t:
                nxt = ls
                break
        t = nxt
        target = chunk_s
    return chunks
