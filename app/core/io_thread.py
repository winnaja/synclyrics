"""IO thread: asyncio loop ใน thread แยก (ARCHITECTURE.md §1) — ไม่ใช้ qasync

ทำไมแยก: UI thread ต้องว่างไว้ให้ QML อย่างเดียว งานเครือข่าย (เนื้อเพลง ปก) และงานบล็อก (yt-dlp)
ไม่ควรไปแย่งเวลา UI/เสียง  งานบล็อกให้ใช้ loop.run_in_executor / asyncio.to_thread
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class IoThread:
    """เปิด event loop ใน daemon thread แล้วรับ coroutine จาก thread ใดก็ได้"""

    def __init__(self, name: str = "synclyrics-io", workers: int = 6) -> None:
        self._loop = asyncio.new_event_loop()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="io-work")
        self._loop.set_default_executor(self._executor)
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def start(self) -> "IoThread":
        if not self._thread.is_alive():
            self._thread.start()
            self._ready.wait(5.0)
        return self

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def submit(self, coro: Coroutine[Any, Any, T]) -> "concurrent.futures.Future[T]":
        """ส่ง coroutine ไปรันใน loop คืน Future (ยกเลิกได้ด้วย .cancel())"""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def call_soon(self, fn: Any, *args: Any) -> None:
        self._loop.call_soon_threadsafe(fn, *args)

    def stop(self, timeout: float = 3.0) -> None:
        """หยุด loop (ยกเลิกงานที่ค้าง) — เรียกตอนปิดโปรแกรม"""
        if not self._loop.is_running():
            return

        async def _cancel_all() -> None:
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        try:
            asyncio.run_coroutine_threadsafe(_cancel_all(), self._loop).result(timeout)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        self._executor.shutdown(wait=False, cancel_futures=True)
