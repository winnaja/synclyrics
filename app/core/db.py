"""ฐานข้อมูล SQLite ไฟล์เดียวของทั้งโปรแกรม + ระบบ migration

กฎการใช้ (ARCHITECTURE.md §8):
- โปรแกรมหลักเท่านั้นที่เปิดฐานข้อมูล AI worker ห้ามแตะ (ส่งผลกลับทาง queue แทน)
  เพื่อให้ watchdog ฆ่า/เปิด worker ใหม่ได้ทุกเมื่อโดยไม่ทำให้ DB ล็อกค้าง
- หนึ่ง thread หนึ่ง connection (sqlite3 ไม่ให้ใช้ข้าม thread)
- audio callback ห้ามแตะ DB เด็ดขาด, UI thread อ่านได้เฉพาะ query เล็กๆ
- เปลี่ยน schema = เพิ่ม migration ใหม่ท้าย MIGRATIONS ห้ามแก้ของเก่าที่ปล่อยไปแล้ว
- เก็บ list/dict เป็น JSON ใน TEXT, เวลาเป็น unix epoch (REAL วินาที)
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

# แต่ละรายการ = migration หนึ่งขั้น index+1 = user_version หลังรัน
MIGRATIONS: list[str | Callable[[sqlite3.Connection], None]] = [
    # ---------------- v1: schema เริ่มต้น (เฟส 0) ----------------
    """
    -- เพลงที่เคยรู้จัก (หนึ่งแถวต่อ videoId)
    CREATE TABLE tracks (
        video_id        TEXT PRIMARY KEY,
        yt_title        TEXT NOT NULL DEFAULT '',
        channel         TEXT NOT NULL DEFAULT '',
        duration_s      REAL,
        title           TEXT,               -- ชื่อเพลงที่แยกแล้ว (ข้อ 4.1)
        artist          TEXT,
        album           TEXT,
        version_tags    TEXT NOT NULL DEFAULT '[]',  -- JSON: ["live","remix",...]
        music_section   TEXT NOT NULL DEFAULT '{}',  -- JSON จากส่วน "Music" ใต้วิดีโอ
        cover_url       TEXT,
        palette         TEXT,               -- JSON: สี 4-5 สีจากปก (OKLCH)
        language        TEXT,
        no_mix          INTEGER NOT NULL DEFAULT 0,  -- "ห้ามมิกซ์เพลงนี้" (ข้อ 7.1)
        theme_id        TEXT,               -- ธีมแยกต่อเพลง (ข้อ 9.2)
        lyrics_offset_s REAL NOT NULL DEFAULT 0,     -- offset ที่ผู้ใช้ปรับด้วย [ / ]
        first_seen_at   REAL NOT NULL,
        last_played_at  REAL,
        play_count      INTEGER NOT NULL DEFAULT 0
    );

    -- ไฟล์เสียง PCM ใน cache (ลบตาม LRU เมื่อเกินขนาดที่ตั้ง)
    CREATE TABLE audio_cache (
        video_id        TEXT PRIMARY KEY REFERENCES tracks(video_id) ON DELETE CASCADE,
        path            TEXT NOT NULL,      -- relative ต่อ cache/audio
        sample_rate     INTEGER NOT NULL,
        channels        INTEGER NOT NULL,
        frames          INTEGER NOT NULL,
        bytes           INTEGER NOT NULL,
        source_format   TEXT,               -- เช่น "opus 251 ~160k"
        complete        INTEGER NOT NULL DEFAULT 0,
        created_at      REAL NOT NULL,
        last_access_at  REAL NOT NULL
    );
    CREATE INDEX idx_audio_cache_lru ON audio_cache(last_access_at);

    -- ผลเนื้อเพลงจากทุกแหล่ง (เก็บหลายผลต่อเพลง เพื่อกด "ผลถัดไป" ได้)
    CREATE TABLE lyrics (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id        TEXT NOT NULL REFERENCES tracks(video_id) ON DELETE CASCADE,
        source          TEXT NOT NULL,      -- ชื่อ plugin
        source_id       TEXT NOT NULL DEFAULT '',
        timing          TEXT NOT NULL,      -- word / line / none
        language        TEXT,
        score           REAL NOT NULL,      -- คะแนนความตรง (ข้อ 4.3)
        payload         TEXT NOT NULL,      -- JSON ของ Lyrics.to_dict()
        fetched_at      REAL NOT NULL,
        UNIQUE(video_id, source, source_id)
    );
    CREATE INDEX idx_lyrics_video ON lyrics(video_id, score DESC);

    -- ตัวเลือกเนื้อเพลงที่ผู้ใช้เลือกเอง (ระบบจำตาม videoId)
    CREATE TABLE lyrics_choice (
        video_id        TEXT PRIMARY KEY REFERENCES tracks(video_id) ON DELETE CASCADE,
        lyrics_id       INTEGER NOT NULL REFERENCES lyrics(id) ON DELETE CASCADE,
        chosen_at       REAL NOT NULL
    );

    -- เวลาที่ผู้ใช้แก้ด้วย Tap Sync (Enhanced LRC)
    CREATE TABLE user_timing (
        video_id        TEXT PRIMARY KEY REFERENCES tracks(video_id) ON DELETE CASCADE,
        lyrics_id       INTEGER REFERENCES lyrics(id) ON DELETE SET NULL,
        elrc            TEXT NOT NULL,
        updated_at      REAL NOT NULL
    );

    -- ผลวิเคราะห์ดนตรีทั้งเพลง (Analysis.to_dict())
    CREATE TABLE analysis (
        video_id        TEXT PRIMARY KEY REFERENCES tracks(video_id) ON DELETE CASCADE,
        version         INTEGER NOT NULL,
        bpm             REAL,
        beat_confidence REAL,
        camelot         TEXT,
        lufs            REAL,
        payload         TEXT NOT NULL,      -- JSON เต็ม (beats, downbeats, sections, vocal_segments)
        created_at      REAL NOT NULL
    );

    -- ผล alignment ทีละช่วง (ประมวลผลแบบทยอย ข้อ 5.2)
    CREATE TABLE alignment_chunks (
        video_id        TEXT NOT NULL REFERENCES tracks(video_id) ON DELETE CASCADE,
        lyrics_id       INTEGER NOT NULL REFERENCES lyrics(id) ON DELETE CASCADE,
        start_s         REAL NOT NULL,
        end_s           REAL NOT NULL,
        words           TEXT NOT NULL,      -- JSON: [{line_idx, word_idx, start, end, confidence}]
        confidence      REAL NOT NULL,
        offset_s        REAL NOT NULL DEFAULT 0,  -- offset อัตโนมัติที่ตรวจเจอ (ข้อ 5.1 ขั้น 7)
        model           TEXT NOT NULL,
        created_at      REAL NOT NULL,
        PRIMARY KEY (video_id, lyrics_id, start_s)
    );

    -- คิวปัจจุบัน + สถานะการเล่น (บันทึกทุก 5 วิ)
    CREATE TABLE queue_items (
        position        INTEGER PRIMARY KEY,
        video_id        TEXT NOT NULL,
        added_from      TEXT NOT NULL DEFAULT 'unknown',
        track_ref       TEXT NOT NULL       -- JSON TrackRef
    );
    CREATE TABLE playback_state (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        video_id        TEXT,
        queue_index     INTEGER,
        position_s      REAL,
        mode            TEXT NOT NULL DEFAULT 'app',
        saved_at        REAL NOT NULL
    );

    CREATE TABLE playlists (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL,
        created_at      REAL NOT NULL
    );
    CREATE TABLE playlist_items (
        playlist_id     INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
        position        INTEGER NOT NULL,
        video_id        TEXT NOT NULL,
        track_ref       TEXT NOT NULL,
        PRIMARY KEY (playlist_id, position)
    );

    -- ทุกการมิกซ์ (ข้อ 7.5 "ความจำ") — แหล่งข้อมูลของระบบเรียนรู้ ประวัติ และสถิติ
    CREATE TABLE mixes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at      REAL NOT NULL,
        video_a         TEXT NOT NULL,
        video_b         TEXT NOT NULL,
        compat_score    REAL NOT NULL,      -- 0-100
        style           TEXT NOT NULL,      -- รูปแบบมิกซ์ที่ใช้จริง
        context         TEXT NOT NULL,      -- JSON feature vector + ชื่อ feature
        action          TEXT NOT NULL,      -- JSON action ที่เลือก
        decision_log    TEXT NOT NULL,      -- JSON เหตุผลทั้งหมด (ข้อ 7.9)
        explored        INTEGER NOT NULL DEFAULT 0,  -- 1 = เป็นการทดลอง
        policy_version  INTEGER NOT NULL,
        auto_reward     REAL,               -- รางวัลจากสัญญาณอัตโนมัติ
        stars           INTEGER CHECK (stars BETWEEN 1 AND 5),
        stars_at        REAL,
        reward          REAL                -- รางวัลสุดท้าย (ดาวทับสัญญาณอัตโนมัติ)
    );
    CREATE INDEX idx_mixes_time ON mixes(created_at);
    CREATE INDEX idx_mixes_pair ON mixes(video_a, video_b);

    -- สัญญาณอัตโนมัติระหว่าง/หลังมิกซ์ (ข้ามการมิกซ์, ลดเสียง, seek ย้อน ...)
    CREATE TABLE mix_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        mix_id          INTEGER NOT NULL REFERENCES mixes(id) ON DELETE CASCADE,
        kind            TEXT NOT NULL,
        value           REAL NOT NULL,
        at              REAL NOT NULL
    );

    -- สถานะของ bandit (เมทริกซ์ posterior) เก็บเป็น blob ต่อ action
    CREATE TABLE bandit_state (
        name            TEXT PRIMARY KEY,   -- เช่น "style:beatmatch"
        version         INTEGER NOT NULL,
        blob            BLOB NOT NULL,      -- numpy .npz
        updated_at      REAL NOT NULL
    );

    -- ค่าที่ผู้ใช้กำหนดเองต่อคู่เพลงใน Mix Lab
    CREATE TABLE pair_overrides (
        video_a         TEXT NOT NULL,
        video_b         TEXT NOT NULL,
        action          TEXT NOT NULL,      -- JSON
        updated_at      REAL NOT NULL,
        PRIMARY KEY (video_a, video_b)
    );

    -- สถานะการตั้งค่าครั้งแรก / health check / งานรายวัน
    CREATE TABLE kv (
        key             TEXT PRIMARY KEY,
        value           TEXT NOT NULL,
        updated_at      REAL NOT NULL
    );
    """,
    # เฟส 4: ผลของ AI ต่อเพลง (จัดเวลาเนื้อเพลงจากเสียง, คำแปล, ช่วงเสียงร้อง) — เล่นซ้ำแล้วได้ทันทีโดยไม่เรียก AI
    """
    CREATE TABLE ai_results (
        video_id        TEXT NOT NULL,
        kind            TEXT NOT NULL,      -- 'align' | 'translation:<ภาษา>' | 'vocal'
        lyrics_key      TEXT NOT NULL DEFAULT '',  -- ระบุชุดเนื้อเพลง (แหล่ง+id+hash) ผลใช้ได้กับชุดนี้เท่านั้น
        version         INTEGER NOT NULL,   -- เวอร์ชันวิธีคำนวณ (AnalysisCfg.algo_version) ไม่ตรง = ถือว่าหมดอายุ
        payload         TEXT NOT NULL,      -- JSON
        created_at      REAL NOT NULL,
        PRIMARY KEY (video_id, kind, lyrics_key)
    );
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)


def connect(path: Path | str) -> sqlite3.Connection:
    """เปิด connection พร้อมค่าที่ถูกต้อง (WAL, foreign keys, busy timeout) และรัน migration"""
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """รัน migration ที่ยังไม่ได้รัน คืน user_version หลังรัน"""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"ฐานข้อมูลเป็นเวอร์ชัน {current} ใหม่กว่าโปรแกรม ({SCHEMA_VERSION}) — อัปเดตโปรแกรมก่อน"
        )
    for i in range(current, SCHEMA_VERSION):
        step = MIGRATIONS[i]
        conn.execute("BEGIN")
        try:
            if callable(step):
                step(conn)
            else:
                for stmt in _split_sql(step):
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {i + 1}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return SCHEMA_VERSION


def _split_sql(script: str) -> list[str]:
    """แยก SQL หลายคำสั่ง (executescript จะ COMMIT เองซึ่งทำให้ rollback ไม่ได้)"""
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(ln.split("--", 1)[0] for ln in lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


PURGE_KEY = "purge_stale_companion_meta_v1"


def purge_stale_companion_cache(conn: sqlite3.Connection) -> bool:
    """ล้างเนื้อเพลง/ชื่อที่แคชไว้ครั้งเดียว (v1): บั๊กเดิมของส่วนขยายส่ง "videoId ใหม่ + ชื่อเพลงก่อนหน้า" เข้ามา

    แคชตาม videoId จึงอาจจำเนื้อเพลง/ชื่อ/ปกของเพลงผิดไว้ถาวร · ล้าง lyrics, lyrics_choice, ชื่อที่ยืนยันไว้ใน tracks
    (ค้นใหม่ครั้งต่อไปจากชื่อที่ยืนยันกับ YouTube แล้ว) · offset ที่ผู้ใช้ปรับไว้ (lyrics_offset_s) เก็บไว้
    คืน True ถ้ามีการล้าง (ครั้งแรกเท่านั้น)
    """
    import time

    if conn.execute("SELECT 1 FROM kv WHERE key=?", (PURGE_KEY,)).fetchone():
        return False
    conn.execute("DELETE FROM lyrics_choice")
    conn.execute("DELETE FROM lyrics")
    conn.execute("UPDATE tracks SET title=NULL, artist=NULL, album=NULL, music_section='{}'")
    conn.execute("INSERT INTO kv(key, value, updated_at) VALUES(?,?,?)", (PURGE_KEY, "1", time.time()))
    return True


PURGE_ART_KEY = "purge_stale_art_v1"


def purge_stale_art_cache(conn: sqlite3.Connection, art_dir: Any) -> int:
    """ล้างปกที่แคชไว้ครั้งเดียว: บั๊กเดิม (ชื่อเพลงจากหน้าเว็บผิดเพลง) ทำให้ปกถูกค้นด้วยชื่อผิดแล้วจำตาม videoId ถาวร
    (เช่น เพลง LE SSERAFIM แสดงปก NewJeans) · ลบไฟล์ใน cache/art ทั้งหมด ครั้งต่อไปจะค้นใหม่จากชื่อที่ยืนยันกับ YouTube แล้ว
    คืนจำนวนไฟล์ที่ลบ (0 = เคยล้างแล้ว/ไม่มีไฟล์)
    """
    import time
    from pathlib import Path

    if conn.execute("SELECT 1 FROM kv WHERE key=?", (PURGE_ART_KEY,)).fetchone():
        return 0
    n = 0
    d = Path(art_dir)
    if d.is_dir():
        for f in d.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    n += 1
                except OSError:
                    pass
    conn.execute("INSERT INTO kv(key, value, updated_at) VALUES(?,?,?)", (PURGE_ART_KEY, "1", time.time()))
    return n
