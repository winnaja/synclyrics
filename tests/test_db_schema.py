"""schema ของ SQLite สร้างได้ migration รันซ้ำได้ และ constraint ทำงาน"""

from __future__ import annotations

import sqlite3
import time

import pytest

from app.core import db

EXPECTED_TABLES = {
    "tracks", "audio_cache", "lyrics", "lyrics_choice", "user_timing", "analysis",
    "alignment_chunks", "queue_items", "playback_state", "playlists", "playlist_items",
    "mixes", "mix_events", "bandit_state", "pair_overrides", "kv",
}


def test_create_and_reopen(tmp_path) -> None:
    path = tmp_path / "t.sqlite3"
    conn = db.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
    # เปิดซ้ำต้องไม่รัน migration ซ้ำ/ไม่ error
    db.connect(path).close()


def test_foreign_keys_and_cascade(tmp_path) -> None:
    conn = db.connect(tmp_path / "t.sqlite3")
    now = time.time()
    conn.execute("INSERT INTO tracks(video_id, first_seen_at) VALUES ('abcdefghijk', ?)", (now,))
    conn.execute(
        "INSERT INTO lyrics(video_id, source, timing, score, payload, fetched_at) VALUES ('abcdefghijk','lrclib','line',80,'{}',?)",
        (now,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO lyrics(video_id, source, timing, score, payload, fetched_at) VALUES ('nope_nope_x','x','line',1,'{}',?)",
            (now,),
        )
    conn.execute("DELETE FROM tracks WHERE video_id='abcdefghijk'")
    assert conn.execute("SELECT COUNT(*) FROM lyrics").fetchone()[0] == 0


def test_stars_constraint(tmp_path) -> None:
    conn = db.connect(tmp_path / "t.sqlite3")
    row = ("a" * 11, "b" * 11, 75.0, "clean_cut", "{}", "{}", "{}", 1)
    conn.execute(
        "INSERT INTO mixes(created_at, video_a, video_b, compat_score, style, context, action, decision_log, policy_version)"
        " VALUES (0,?,?,?,?,?,?,?,?)",
        row,
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE mixes SET stars = 6")


def test_newer_db_refused(tmp_path) -> None:
    path = tmp_path / "t.sqlite3"
    c = sqlite3.connect(path)
    c.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    c.close()
    with pytest.raises(RuntimeError):
        db.connect(path)
