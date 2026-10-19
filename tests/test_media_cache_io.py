"""cache เสียง (LRU/ล้าง) และ IoThread"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app.core import db as dbmod
from app.core.io_thread import IoThread
from app.media import cache


def _make(conn, audio_dir: Path, vid: str, size: int, age: float) -> None:
    conn.execute("INSERT INTO tracks(video_id, first_seen_at) VALUES(?,?)", (vid, time.time()))
    f = audio_dir / f"{vid}.f32"
    f.write_bytes(b"\0" * size)
    (audio_dir / f"{vid}.f32.meta.json").write_text("{}")
    cache.register(conn, vid, f, audio_dir, 48000, size // 8, "251 opus 130k", True)
    conn.execute("UPDATE audio_cache SET last_access_at=? WHERE video_id=?", (time.time() - age, vid))


def test_enforce_limit_removes_oldest_first_and_protects(app_paths) -> None:
    conn = dbmod.connect(app_paths.db_file)
    d = app_paths.audio_cache_dir
    _make(conn, d, "old00000001", 400, age=300)
    _make(conn, d, "mid00000001", 400, age=200)
    _make(conn, d, "new00000001", 400, age=100)
    # จำกัด ~ 0.0000008 GB = ~858 ไบต์ -> ต้องลบ 1 รายการ (เก่าสุด)
    removed = cache.enforce_limit(conn, d, 858 / cache.GB)
    assert removed == ["old00000001"]
    assert not (d / "old00000001.f32").exists() and (d / "mid00000001.f32").exists()
    # protect: เพลงที่กำลังเล่นห้ามถูกลบแม้เก่าสุด
    removed = cache.enforce_limit(conn, d, 1 / cache.GB, protect=["mid00000001"])
    assert "mid00000001" not in removed and (d / "mid00000001.f32").exists()


def test_clear_all_keeps_protected_and_removes_orphans(app_paths) -> None:
    conn = dbmod.connect(app_paths.db_file)
    d = app_paths.audio_cache_dir
    _make(conn, d, "aaa00000001", 100, age=10)
    _make(conn, d, "bbb00000001", 100, age=10)
    (d / "orphan0001.f32").write_bytes(b"\0" * 50)
    freed = cache.clear_all(conn, d, protect=["bbb00000001"])
    assert freed >= 150
    assert not (d / "aaa00000001.f32").exists() and not (d / "orphan0001.f32").exists()
    assert (d / "bbb00000001.f32").exists()
    assert cache.total_bytes(conn) == 100


def test_touch_updates_lru(app_paths) -> None:
    conn = dbmod.connect(app_paths.db_file)
    _make(conn, app_paths.audio_cache_dir, "ccc00000001", 10, age=500)
    before = conn.execute("SELECT last_access_at FROM audio_cache").fetchone()[0]
    cache.touch(conn, "ccc00000001")
    assert conn.execute("SELECT last_access_at FROM audio_cache").fetchone()[0] > before


def test_io_thread_runs_and_cancels() -> None:
    io = IoThread().start()
    try:
        async def add(a: int, b: int) -> int:
            await asyncio.sleep(0.01)
            return a + b

        assert io.submit(add(2, 3)).result(2) == 5

        async def forever() -> None:
            await asyncio.sleep(60)

        fut = io.submit(forever())
        time.sleep(0.05)
        fut.cancel()
        time.sleep(0.05)
        assert fut.cancelled()
    finally:
        io.stop()
    assert not io.loop.is_running()


async def test_artwork_policy_remix_uses_youtube_thumbnail(app_paths) -> None:
    from app.core.models import TrackMeta, TrackRef
    from app.media import artwork

    calls: list[str] = []

    class Resp:
        def __init__(self, content: bytes = b"x" * 5000, js: dict | None = None) -> None:
            self.status_code, self.content, self._js = 200, content, js or {}

        def json(self) -> dict:
            return self._js

    class Client:
        async def get(self, url: str, **kw):
            calls.append(url)
            if "itunes" in url:
                return Resp(js={"results": [{"artworkUrl100": "http://x/100x100bb.jpg", "trackName": "Midnight Drive",
                                             "artistName": "Nova Waves", "trackTimeMillis": 200000}]})
            return Resp()

    track = TrackRef(video_id="vid00000009", title="x", duration=200.0)
    remix = TrackMeta(title="Midnight Drive", artist="Nova Waves", duration=200.0, version_tags=frozenset({"remix"}))
    art = await artwork.fetch_artwork(track, remix, app_paths.art_cache_dir, client=Client())
    assert art is not None and art.source == "youtube" and not any("itunes" in c for c in calls)

    calls.clear()
    track2 = TrackRef(video_id="vid00000010", title="x", duration=200.0)
    original = TrackMeta(title="Midnight Drive", artist="Nova Waves", duration=200.0)
    art2 = await artwork.fetch_artwork(track2, original, app_paths.art_cache_dir, client=Client())
    assert art2 is not None and art2.source == "itunes"
