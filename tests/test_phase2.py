"""เฟส 2: คิว/ปุ่มถัดไป-ก่อนหน้า/โหมดคู่หูใน controller, health check, installer, registry, เลือกภาษาคำบรรยาย"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_player_controller import VID, rig, topics, wait_for  # noqa: F401  (rig = fixture)

from app.bridge import installer, registry
from app.core import health
from app.core.models import TrackRef
from app.lyrics.sources.youtube_subs import rank_subtitles

V2, V3 = "vid00000002", "vid00000003"


# ---------------------------------------------------------------------------
# controller: คิว + ถัดไป/ก่อนหน้า (ใช้ rig ของ test_player_controller — ต้องมี ffmpeg)
# ---------------------------------------------------------------------------
def test_play_now_adds_to_queue_and_next_prev_walk_it(rig) -> None:  # noqa: F811
    c = rig.ctl
    c.play_now(TrackRef(video_id=VID))
    assert wait_for(lambda: c.loaded and c.track.video_id == VID)
    assert c.enqueue([TrackRef(video_id=V2), TrackRef(video_id=V3)]) == 2
    c.skip_next()
    assert wait_for(lambda: c.track is not None and c.track.video_id == V2 and c.loaded)
    c.skip_next()
    assert wait_for(lambda: c.track.video_id == V3 and c.loaded)
    c.skip_next()  # หมดคิว: ไม่พัง ไม่เปลี่ยนเพลง
    assert c.track.video_id == V3
    # เพิ่งเริ่มเพลง (<3 วิ) กด prev = ย้อนไปเพลงก่อนหน้า
    c.skip_prev()
    assert wait_for(lambda: c.track.video_id == V2 and c.loaded)
    assert "queue.changed" in topics(rig)


def test_track_end_advances_to_next_in_queue(rig) -> None:  # noqa: F811
    c = rig.ctl
    c.start_background_tasks()
    c.play_now(TrackRef(video_id=VID))
    c.enqueue([TrackRef(video_id=V2)])
    assert wait_for(lambda: c.loaded and c.playing)
    c.seek(2.9)  # เพลงยาว 3 วิ -> จบทันที
    assert wait_for(lambda: c.track.video_id == V2, timeout=10)


def test_snapshot_restore_keeps_queue(rig) -> None:  # noqa: F811
    c = rig.ctl
    c.play_now(TrackRef(video_id=VID))
    c.enqueue([TrackRef(video_id=V2)])
    assert wait_for(lambda: c.loaded)
    snap = json.loads(json.dumps(c.snapshot()))  # ผ่าน JSON เหมือน state.json จริง
    assert [t["video_id"] for t in snap["queue"]["items"]] == [VID, V2] and snap["mode"] == "app"
    c.queue.restore({"items": [], "index": -1})
    assert len(c.queue) == 0
    c.restore(snap)
    assert [t.video_id for t in c.queue.items()] == [VID, V2]


# ---------------------------------------------------------------------------
# controller: โหมดคู่หู
# ---------------------------------------------------------------------------
def test_companion_mode_uses_remote_clock_and_finds_lyrics(rig) -> None:  # noqa: F811
    c = rig.ctl
    c.play_now(TrackRef(video_id=VID))
    assert wait_for(lambda: c.loaded and c.playing)
    c.companion_track(TrackRef(video_id=V2, title="เพลงใน YouTube"))
    assert c.mode == "companion" and not c.playing
    assert wait_for(lambda: c.get_clock() is c.remote_clock)
    # เสียงของแอปต้องหยุด (YouTube เป็นคนเล่น)
    assert wait_for(lambda: c.engine.decks[c.active_deck].state.name != "PLAYING")
    assert wait_for(lambda: any(t == "lyrics.ready" and d["video_id"] == V2 for t, d in rig.events))
    c.companion_state({"video_id": V2, "current_time": 42.0, "rate": 1.0, "paused": False,
                       "sent_at_ms": time.time() * 1000, "duration": 200.0})
    assert abs(c.remote_clock.position() - 42.0) < 1.0 and c.playing and c.duration == 200.0
    c.companion_state({"video_id": V2, "current_time": 50.0, "paused": True, "sent_at_ms": time.time() * 1000})
    assert not c.playing and abs(c.remote_clock.position() - 50.0) < 0.1
    # ปุ่มใน UI ในโหมดคู่หู = สั่งแท็บ YouTube
    sent: list[tuple[str, dict]] = []
    c.tab_control = lambda a, d: sent.append((a, d))
    c.seek(77.0)
    c.skip_next()
    c.toggle_pause()
    assert sent == [("seek", {"time": 77.0}), ("next", {}), ("play", {})]


def test_play_now_leaves_companion_mode(rig) -> None:  # noqa: F811
    c = rig.ctl
    c.set_mode("companion")
    assert c.mode == "companion"
    c.play_now(TrackRef(video_id=VID))
    assert c.mode == "app"
    assert wait_for(lambda: c.loaded and c.playing)
    assert any(t == "mode.changed" for t, _ in rig.events)


# ---------------------------------------------------------------------------
# health check
# ---------------------------------------------------------------------------
def test_health_reports_each_problem_with_a_fix(tmp_path: Path) -> None:
    items = health.run_health_checks(find_ffmpeg=lambda: None, cookies_file=tmp_path / "nope.txt",
                                     is_ext_registered=lambda: False, engine_error="เปิดอุปกรณ์เสียงไม่ได้",
                                     which=lambda n: None)
    bad = {i.id: i for i in items if not i.ok}
    assert set(bad) == {"audio", "ffmpeg", "node", "cookies", "extension_registered"}
    assert all(i.message for i in bad.values()) and bad["ffmpeg"].severity == "error"
    assert "winget install" in bad["node"].fix and str(tmp_path / "nope.txt") in bad["cookies"].fix
    text = health.format_problems(items)
    assert "วิธีแก้" in text and "cookies" in text


def test_health_all_ok_and_cookie_contents_never_leak(tmp_path: Path) -> None:
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tSECRET_VALUE_123\n"
                 "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PSID\tSECRET_2\n", encoding="utf-8")
    items = health.run_health_checks(find_ffmpeg=lambda: Path("ffmpeg"), cookies_file=f,
                                     is_ext_registered=lambda: True, engine_error=None, which=lambda n: "node")
    assert all(i.ok for i in items) and health.format_problems(items) == ""
    f.write_text("# ว่าง\n.example.com\tTRUE\t/\tTRUE\t0\tX\tSECRET_VALUE_123\n", encoding="utf-8")
    items = health.run_health_checks(find_ffmpeg=lambda: Path("ffmpeg"), cookies_file=f,
                                     is_ext_registered=lambda: True, engine_error=None, which=lambda n: "node")
    assert "SECRET" not in repr(items) and not next(i for i in items if i.id == "cookies").ok


def test_health_check_that_crashes_becomes_a_warning() -> None:
    def boom() -> Path:
        raise RuntimeError("พัง")

    items = health.run_health_checks(find_ffmpeg=boom, cookies_file=Path("x"), is_ext_registered=lambda: True,
                                     engine_error=None, which=lambda n: "node")
    ff = next(i for i in items if i.id == "ffmpeg")
    assert not ff.ok and ff.severity == "warn"


# ---------------------------------------------------------------------------
# installer / registry
# ---------------------------------------------------------------------------
def make_ext(root: Path) -> Path:
    src = root / "extension"
    (src / "icons").mkdir(parents=True)
    (src / "manifest.json").write_text(
        (Path(__file__).resolve().parents[1] / "extension" / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (src / "background.js").write_text("// bg", encoding="utf-8")
    (src / "icons" / "on-16.png").write_bytes(b"png")
    (src / "key.pem").write_text("PRIVATE", encoding="utf-8")
    (src / "README.md").write_text("doc", encoding="utf-8")
    return src


def test_sync_extension_copies_only_changed_and_never_the_private_key(tmp_path: Path) -> None:
    src, dst = make_ext(tmp_path), tmp_path / "installed"
    assert installer.sync_extension(src, dst) is True
    assert (dst / "background.js").exists() and (dst / "icons" / "on-16.png").exists()
    assert not (dst / "key.pem").exists() and not (dst / "README.md").exists()
    assert installer.sync_extension(src, dst) is False  # ไม่มีอะไรเปลี่ยน
    (src / "background.js").write_text("// bg v2", encoding="utf-8")
    assert installer.sync_extension(src, dst) is True
    assert (dst / "background.js").read_text(encoding="utf-8") == "// bg v2"


@pytest.mark.skipif(os.name != "nt", reason="winreg เฉพาะ Windows")
def test_install_registers_host_in_registry(tmp_path: Path, monkeypatch) -> None:
    # ใช้ key ทดสอบ ไม่แตะ registry จริงของโปรแกรม
    test_key = r"Software\SyncLyricsTest\NativeMessagingHosts\com.synclyrics.host"
    monkeypatch.setattr(registry, "REG_KEY", test_key)
    src = make_ext(tmp_path)
    paths = SimpleNamespace(extension_src_dir=src, installed_extension_dir=tmp_path / "installed", home=tmp_path)
    clip: list[str] = []
    opened: list[str] = []
    try:
        res = installer.install(paths, set_clipboard=clip.append, open_url=opened.append)
        assert res.ok and res.changed and clip == [str(tmp_path / "installed")] and opened == ["chrome://extensions"]
        mp = registry.registered_manifest()
        assert mp is not None and mp.exists()
        d = json.loads(mp.read_text(encoding="utf-8"))
        assert d["allowed_origins"] == [f"chrome-extension://{registry.extension_id_from_manifest(src / 'manifest.json')}/"]
    finally:
        registry.unregister()
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\SyncLyricsTest\NativeMessagingHosts")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\SyncLyricsTest")
        except OSError:
            pass


def test_install_fails_gracefully_without_extension_folder(tmp_path: Path) -> None:
    paths = SimpleNamespace(extension_src_dir=tmp_path / "none", installed_extension_dir=tmp_path / "i", home=tmp_path)
    res = installer.install(paths, set_clipboard=lambda t: None, open_url=lambda u: None)
    assert not res.ok and "ไม่พบ" in res.message


# ---------------------------------------------------------------------------
# youtube_subs: ไม่ส่ง "คำแปล" แทนเนื้อร้อง
# ---------------------------------------------------------------------------
def test_subtitles_drop_translations_for_non_latin_titles() -> None:
    en_only = {"en": [{"ext": "vtt", "url": "u-en"}]}
    assert rank_subtitles(en_only, "สลักจิต - ป๊อบ ปองกูล [Official MV]") == []
    both = {"en": [{"ext": "vtt", "url": "u-en"}], "th": [{"ext": "vtt", "url": "u-th"}]}
    assert rank_subtitles(both, "สลักจิต - ป๊อบ ปองกูล") == [("th", "u-th")]
    # ชื่ออังกฤษ: ยังได้ทุกภาษา เรียงอังกฤษก่อน
    assert [lang for lang, _ in rank_subtitles(both, "Midnight Drive - Nova Waves")] == ["en", "th"]
    assert [lang for lang, _ in rank_subtitles({"ja": both["th"], "en": both["en"]}, "夜に駆ける - YOASOBI")] == ["ja"]


# ---------------------------------------------------------------------------
# ปก: ตัดขอบดำของ thumbnail
# ---------------------------------------------------------------------------
def _img(h: int, w: int, bars=(0, 0, 0, 0), dark_level: int = 0):
    import numpy as np

    g = np.full((h, w), 140, dtype=np.uint8)
    g[:, ::7] = 200  # ลายในเนื้อรูป
    top, bottom, left, right = bars
    for sl in (g[:top], g[h - bottom:] if bottom else g[:0], g[:, :left], g[:, w - right:] if right else g[:, :0]):
        sl[...] = dark_level
    return g


def test_content_box_detects_pillarbox_and_letterbox() -> None:
    from app.media.artwork import find_content_box

    assert find_content_box(_img(360, 480, bars=(45, 45, 0, 0))) == (0, 45, 480, 315)  # hqdefault: ขอบบนล่าง
    assert find_content_box(_img(300, 500, bars=(0, 0, 150, 150))) == (150, 0, 350, 300)  # ขอบซ้ายขวา (ภาพที่ผู้ใช้เจอ)
    assert find_content_box(_img(300, 300)) is None  # ไม่มีขอบ


def test_content_box_does_not_crop_dark_art_or_tiny_noise() -> None:
    import numpy as np

    from app.media.artwork import find_content_box

    assert find_content_box(np.zeros((100, 100), np.uint8)) is None  # ดำล้วน
    dim = np.full((200, 200), 10, np.uint8)
    dim[90:110, 90:110] = 60  # ปกมืดที่มีวัตถุเล็กๆ ตรงกลาง: เหลือเนื้อ <40% = ไม่ตัด
    assert find_content_box(dim) is None
    assert find_content_box(_img(300, 300, bars=(3, 0, 0, 0))) is None  # ขอบบาง <3% ไม่คุ้มตัด
    assert find_content_box(_img(300, 300, bars=(60, 0, 0, 0), dark_level=40)) is None  # ขอบ "เทาเข้ม" ไม่ใช่ดำ = เนื้อรูป


def test_autocrop_black_bars_end_to_end(tmp_path: Path) -> None:
    """ไฟล์ JPEG จริง: ขอบดำซ้ายขวา (ภาพที่ผู้ใช้เจอ) ถูกตัด ภาพไม่มีขอบไม่ถูกแตะ ไฟล์เสียไม่ crash"""
    import numpy as np
    from PIL import Image

    from app.media.artwork import autocrop_black_bars

    rgb = np.zeros((300, 500, 3), np.uint8)
    rgb[:, 150:350] = (200, 120, 90)
    rgb[:, 150:350:5] = (90, 140, 220)
    p = tmp_path / "t.jpg"
    Image.fromarray(rgb).save(p, quality=95)
    assert autocrop_black_bars(p) is True
    assert Image.open(p).size == (200, 300)
    assert autocrop_black_bars(p) is False  # ตัดซ้ำ = ไม่เปลี่ยน
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert autocrop_black_bars(bad) is False


# ---------------------------------------------------------------------------
# แอปแสดงเนื้อเพลงอย่างเดียว (companion เป็นโหมดเดียว) + ไม่เชื่อชื่อเพลงจากหน้าเว็บ
# ---------------------------------------------------------------------------
@pytest.fixture()
def fake_oembed(monkeypatch):
    """oEmbed ปลอม: videoId -> (ชื่อ, ช่อง) ไม่ใช้เครือข่าย"""
    table = {V2: ("Nobody Knows (Nobody Knows)", "KISS OF LIFE"), V3: ("OMG", "NewJeans")}

    async def fake(video_id, client=None, timeout_s=4.0):
        return table.get(video_id)

    monkeypatch.setattr("app.media.youtube.fetch_oembed", fake)
    return table


def test_companion_never_trusts_page_title_for_new_track(rig, fake_oembed) -> None:  # noqa: F811
    """บั๊กที่ผู้ใช้เจอ: YouTube เปลี่ยน URL (videoId ใหม่) ก่อนชื่อบนหน้า -> ส่วนขยายส่ง id ใหม่ + ชื่อเพลงเก่า"""
    c = rig.ctl
    rig.media.info_fail = True  # ให้เหลือแค่ oEmbed
    c.companion_track(TrackRef(video_id=V2, title="OMG", channel="NewJeans"))  # คำใบ้ผิด (ชื่อเพลงก่อนหน้า)
    assert wait_for(lambda: c.track is not None and c.track.title == "Nobody Knows (Nobody Knows)")
    assert c.track.channel == "KISS OF LIFE" and c.track.video_id == V2
    # หน้าจอถูกเคลียร์ก่อนเสมอ: เหตุการณ์แรกของเพลงใหม่ไม่มีชื่อเก่า และไม่มีเหตุการณ์ไหนที่พาชื่อ "OMG" ไปให้ UI
    changed = [d for t, d in rig.events if t == "track.changed" and d["video_id"] == V2]
    assert changed and changed[0]["track_ref"].title == ""
    assert not any(getattr(d.get("track_ref"), "title", "") == "OMG" for t, d in rig.events if t == "track.changed")
    assert wait_for(lambda: any(t == "lyrics.ready" and d["video_id"] == V2 for t, d in rig.events))


def test_companion_music_section_used_only_when_page_title_matches(rig, fake_oembed) -> None:  # noqa: F811
    c = rig.ctl
    rig.media.info_fail = True
    ms = {"song": "Nobody Knows", "artist": "KISS OF LIFE"}
    c.companion_track(TrackRef(video_id=V2, title="Nobody Knows (Nobody Knows)", music_section=ms))
    assert wait_for(lambda: c.track is not None and c.track.title.startswith("Nobody"))
    assert c.track.music_section == ms  # หน้าเว็บอัปเดตแล้ว (ชื่อตรง) -> ใช้ได้
    c.companion_track(TrackRef(video_id=V3, title="Nobody Knows (Nobody Knows)", music_section=ms))  # ชื่อเก่า + id ใหม่
    assert wait_for(lambda: c.track is not None and c.track.video_id == V3 and c.track.title == "OMG")
    assert c.track.music_section == {}  # ไม่ตรง -> ทิ้ง ไม่เอาของเพลงอื่นมาปน


def test_companion_state_alone_switches_track_when_track_message_is_lost(rig, fake_oembed) -> None:  # noqa: F811
    c = rig.ctl
    rig.media.info_fail = True
    c.companion_track(TrackRef(video_id=V2))
    assert wait_for(lambda: c.track is not None and c.track.video_id == V2 and c.track.title)
    # ข้อความ companion_track ของเพลงถัดไปหาย แต่ companion_state มาถึง -> ต้องจับเพลงใหม่เอง
    c.companion_state({"video_id": V3, "current_time": 5.0, "rate": 1.0, "paused": False,
                       "sent_at_ms": time.time() * 1000})
    assert wait_for(lambda: c.track is not None and c.track.video_id == V3 and c.track.title == "OMG")
    assert abs(c.remote_clock.position() - 5.0) < 1.0 and c.playing


def test_app_without_audio_ignores_play_and_never_opens_audio(app_paths) -> None:
    """ค่าเริ่มต้น: แอปแสดงเนื้อเพลงอย่างเดียว"""
    from app.core.config import Settings
    from app.core.events import EventBus
    from app.core.io_thread import IoThread
    from app.player.controller import PlayerController

    assert Settings().playback.app_audio is False
    io = IoThread().start()
    try:
        bus = EventBus()
        events: list[str] = []
        bus.subscribe("*", lambda t, d: events.append(t))
        ctl = PlayerController(SimpleNamespace(clocks=[None], decks=[]), bus, None, None, None, app_paths.db_file,
                               Settings(), paths=app_paths, io=io)
        assert ctl.mode == "companion"
        ctl.play_now(TrackRef(video_id=VID))
        ctl.play_url("https://youtu.be/dQw4w9WgXcQ")
        assert ctl.enqueue([TrackRef(video_id=VID)]) == 0
        ctl.set_mode("app")
        assert ctl.mode == "companion" and ctl.track is None and "track.changed" not in events
    finally:
        io.stop()


def test_health_skips_audio_and_ffmpeg_when_app_has_no_audio(tmp_path: Path) -> None:
    items = health.run_health_checks(find_ffmpeg=lambda: None, cookies_file=tmp_path / "x", is_ext_registered=lambda: True,
                                     engine_error="เสียงพัง", which=lambda n: "node", app_audio=False)
    assert {i.id for i in items} == {"node", "cookies", "extension_registered"}


def test_purge_stale_cache_runs_once_and_keeps_user_offset(app_paths) -> None:
    from app.core import db as dbmod

    conn = dbmod.connect(app_paths.db_file)
    conn.execute("INSERT INTO tracks(video_id, yt_title, title, artist, first_seen_at, lyrics_offset_s) "
                 "VALUES('aaaaaaaaaaa','OMG','OMG','NewJeans',1,0.4)")
    conn.execute("INSERT INTO lyrics(video_id, source, source_id, timing, score, payload, fetched_at) "
                 "VALUES('aaaaaaaaaaa','x','1','line',90,'{}',1)")
    assert dbmod.purge_stale_companion_cache(conn) is True
    row = conn.execute("SELECT title, artist, lyrics_offset_s FROM tracks WHERE video_id='aaaaaaaaaaa'").fetchone()
    assert row["title"] is None and row["artist"] is None and row["lyrics_offset_s"] == 0.4
    assert conn.execute("SELECT COUNT(*) c FROM lyrics").fetchone()["c"] == 0
    conn.execute("INSERT INTO lyrics(video_id, source, source_id, timing, score, payload, fetched_at) "
                 "VALUES('aaaaaaaaaaa','x','2','line',90,'{}',1)")
    assert dbmod.purge_stale_companion_cache(conn) is False  # ครั้งเดียว: ข้อมูลใหม่ไม่ถูกล้างซ้ำ
    assert conn.execute("SELECT COUNT(*) c FROM lyrics").fetchone()["c"] == 1
    conn.close()


def _topic_thumb(w: int = 1280, h: int = 720, art: int = 720):
    """จำลอง thumbnail แบบ Topic: ปกจัตุรัสที่มีรายละเอียดคม วางกลางพื้นหลังเบลอเรียบ"""
    import numpy as np

    rng = np.random.default_rng(1)
    g = np.tile(np.linspace(40, 90, w), (h, 1))  # พื้นหลังเรียบ (ไล่เฉด)
    x0 = (w - art) // 2
    g[:, x0:x0 + art] = rng.integers(20, 235, size=(h, art))  # ปก: รายละเอียดเยอะ
    return g, x0


def test_find_art_square_detects_topic_thumbnail() -> None:
    from app.media.artwork import find_art_square

    g, x0 = _topic_thumb()
    box = find_art_square(g)
    assert box is not None and abs(box[0] - x0) <= 2 and box[1] == 0 and abs((box[2] - box[0]) - 720) <= 2 and box[3] == 720


def test_find_art_square_ignores_normal_images() -> None:
    import numpy as np

    from app.media.artwork import find_art_square

    rng = np.random.default_rng(2)
    assert find_art_square(rng.integers(0, 255, size=(720, 1280))) is None   # รูปถ่ายทั่วไป (ทั้งภาพมีรายละเอียด)
    assert find_art_square(np.tile(np.linspace(0, 255, 1280), (720, 1))) is None  # ไล่เฉดเรียบล้วน ไม่มีขอบ
    g, _ = _topic_thumb(w=720, h=720, art=700)
    assert find_art_square(g) is None  # รูปจัตุรัสอยู่แล้ว (aspect < 1.4) ไม่ตัด
    g, _ = _topic_thumb(art=500)  # กว้างปกไม่เท่าความสูง = ไม่ใช่รูปแบบนี้
    assert find_art_square(g) is None


def test_autocrop_cuts_topic_thumbnail_to_square_art(tmp_path: Path) -> None:
    import numpy as np
    from PIL import Image

    from app.media.artwork import autocrop_black_bars

    g, _ = _topic_thumb()
    p = tmp_path / "t.jpg"
    Image.fromarray(g.astype("uint8")).convert("RGB").save(p, quality=95)
    assert autocrop_black_bars(p) is True
    assert Image.open(p).size[0] == Image.open(p).size[1] == 720


def test_dominant_colors_keeps_grayscale_covers_neutral_and_colored_ones_vivid(tmp_path: Path) -> None:
    import colorsys

    import numpy as np
    from PIL import Image

    from app.media.artwork import dominant_colors

    def hsv(c: str) -> tuple[float, float, float]:
        return colorsys.rgb_to_hsv(*(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)))

    rng = np.random.default_rng(3)
    gray = rng.integers(0, 255, size=(200, 200)).astype("uint8")
    Image.fromarray(gray).convert("RGB").save(tmp_path / "bw.png")
    bw = dominant_colors(tmp_path / "bw.png")
    assert len(bw) == 4 and all(hsv(c)[1] < 0.2 and hsv(c)[2] <= 0.62 for c in bw)  # เทาเป็นกลาง ไม่เติมสี
    red_blue = np.zeros((200, 200, 3), "uint8")
    red_blue[:, :100] = (200, 30, 40)
    red_blue[:, 100:] = (30, 60, 200)
    Image.fromarray(red_blue).save(tmp_path / "rb.png")
    cols = dominant_colors(tmp_path / "rb.png")
    assert len(cols) == 4 and all(c.startswith("#") and len(c) == 7 for c in cols)
    assert all(hsv(c)[1] >= 0.3 and 0.25 <= hsv(c)[2] <= 0.85 for c in cols[:2])  # คงโทนปก อยู่ในช่วงสว่างที่อ่านตัวอักษรขาวได้
    assert dominant_colors(tmp_path / "missing.png") == ["#2a2f3d", "#343947", "#232733", "#2e3340"]  # ไม่มีไฟล์ = ค่าเริ่มต้น (เทากลางๆ)
    # ปกสีเดียวหลายเฉด (ทะเลสีน้ำเงิน): ทุกสีต้องยังเป็นน้ำเงิน ห้ามมีเฉดอื่น (เคยมีม่วงโผล่จากการหมุนเฉดสี)
    ocean = np.zeros((200, 200, 3), "uint8")
    ocean[:, :70] = (4, 30, 85)
    ocean[:, 70:140] = (20, 75, 120)
    ocean[:, 140:] = (48, 97, 136)
    Image.fromarray(ocean).save(tmp_path / "ocean.png")
    assert all(190 <= hsv(c)[0] * 360 <= 235 for c in dominant_colors(tmp_path / "ocean.png"))


def test_volume_is_read_from_youtube_and_controlled_through_the_tab(rig, fake_oembed) -> None:  # noqa: F811
    c = rig.ctl
    rig.media.info_fail = True
    c.companion_track(TrackRef(video_id=V2))
    assert wait_for(lambda: c.track is not None and c.track.video_id == V2)
    sent: list[tuple[str, dict]] = []
    c.tab_control = lambda a, d: sent.append((a, d))
    # วอลลุ่มจาก YouTube เข้ามากับ companion_state -> เหตุการณ์ volume.changed (เฉพาะเมื่อเปลี่ยนจริง)
    st = {"video_id": V2, "current_time": 3.0, "paused": False, "sent_at_ms": time.time() * 1000, "volume": 0.4, "muted": False}
    c.companion_state(st)
    c.companion_state(st)
    changes = [d for t, d in rig.events if t == "volume.changed"]
    assert changes == [{"volume": 0.4, "muted": False}]
    c.companion_state({**st, "volume": 7})  # ค่านอกช่วง = ทิ้ง
    assert c.volume == 0.4
    # ปรับวอลลุ่มจากแอป -> สั่งแท็บ (ไม่แตะ engine) + อัปเดตทันที (ไม่รอรอบรายงานถัดไป)
    c.set_volume(0.8)
    assert sent[-1] == ("volume", {"value": 0.8}) and c.volume == 0.8
    c.set_volume(5)  # clamp
    assert sent[-1] == ("volume", {"value": 1.0})
    c.toggle_mute()
    assert sent[-1] == ("mute", {"value": True}) and c.muted is True
    c.toggle_mute()
    assert sent[-1] == ("mute", {"value": False}) and c.muted is False


def test_group_range_links_continuous_lines_only():
    from app.ui.lyrics_model import group_range, group_rows

    def row(start, end, text, voice="main"):
        return {"start": start, "end": end, "text": text, "voice": voice}

    rows = [
        row(0, 3, "She just want the fame, I know what"),   # 0 ─┐ ต่อเนื่อง ขึ้นบรรทัดใหม่ด้วยตัวพิมพ์เล็ก
        row(3.0, 5, "she fiends (oh-oh)"),                  # 1 ─┘
        row(5.0, 8, "Give her a little taste"),             # 2  ประโยคใหม่ (เวลาติดกันพอดีแต่ขึ้นต้นตัวใหญ่) ต้องไม่ถูกรวม
        row(7.0, 9, "(ooh)", voice="background"),           # 3  เสียงประสานทับกัน รวมกับบรรทัด 2
        row(20, 22, "Next verse"),                          # 4  ห่างมาก
    ]
    assert group_range(rows, 0, 0.6) == (0, 1)
    assert group_range(rows, 1, 0.6) == (0, 1)
    assert group_range(rows, 2, 0.6) == (2, 3)
    assert group_range(rows, 3, 0.6) == (2, 3)
    assert group_range(rows, 4, 0.6) == (4, 4)
    assert group_range(rows, 9, 0.6) == (9, 9)

    # เพลงที่ทุกบรรทัดขึ้นต้นตัวใหญ่และเวลาติดกันหมด (LRC ทั่วไป) ห้ามถูกรวมเป็นก้อนเดียวทั้งเพลง
    lrc = [row(i * 3.0, i * 3.0 + 3.0, f"Line number {i}") for i in range(40)]
    assert all(lo == hi for lo, hi in group_rows(lrc, 0.6))
    # ต่อให้ต่อกันตลอด (ตัวพิมพ์เล็กทุกบรรทัด) ก็จำกัดท่อนละไม่เกิน 3 บรรทัด
    chain = [row(i * 3.0, i * 3.0 + 3.0, f"and line {i}") for i in range(10)]
    assert max(hi - lo + 1 for lo, hi in group_rows(chain, 0.6)) == 3


def test_volume_is_read_from_youtube_and_controlled_through_the_tab(rig, fake_oembed) -> None:  # noqa: F811
    c = rig.ctl
    rig.media.info_fail = True
    c.companion_track(TrackRef(video_id=V2))
    assert wait_for(lambda: c.track is not None and c.track.video_id == V2)
    sent: list[tuple[str, dict]] = []
    c.tab_control = lambda a, d: sent.append((a, d))
    # วอลลุ่มจาก YouTube เข้ามากับ companion_state -> เหตุการณ์ volume.changed (เฉพาะเมื่อเปลี่ยนจริง)
    st = {"video_id": V2, "current_time": 3.0, "paused": False, "sent_at_ms": time.time() * 1000, "volume": 0.4, "muted": False}
    c.companion_state(st)
    c.companion_state(st)
    changes = [d for t, d in rig.events if t == "volume.changed"]
    assert changes == [{"volume": 0.4, "muted": False}]
    c.companion_state({**st, "volume": 7})  # ค่านอกช่วง = ทิ้ง
    assert c.volume == 0.4
    # ปรับวอลลุ่มจากแอป -> สั่งแท็บ (ไม่แตะ engine) + อัปเดตทันที (ไม่รอรอบรายงานถัดไป)
    c.set_volume(0.8)
    assert sent[-1] == ("volume", {"value": 0.8}) and c.volume == 0.8
    c.set_volume(5)  # clamp
    assert sent[-1] == ("volume", {"value": 1.0})
    c.toggle_mute()
    assert sent[-1] == ("mute", {"value": True}) and c.muted is True
    c.toggle_mute()
    assert sent[-1] == ("mute", {"value": False}) and c.muted is False


def test_group_range_links_continuous_lines_only():
    from app.ui.lyrics_model import group_range

    def row(start, end, text, voice="main"):
        return {"start": start, "end": end, "text": text, "voice": voice}

    rows = [
        row(0, 3, "She just want the fame, I know what"),   # 0 ─┐ ต่อเนื่อง ขึ้นบรรทัดใหม่ด้วยตัวพิมพ์เล็ก
        row(3.1, 5, "she fiends (oh-oh)"),                  # 1 ─┘
        row(5.2, 8, "Give her a little taste"),             # 2  ประโยคใหม่ (ขึ้นต้นตัวใหญ่ ไม่มีจุลภาค) ไม่ถูกรวม
        row(7.5, 9, "(ooh)", voice="background"),           # 3  เสียงประสานทับกัน รวมกับบรรทัด 2
        row(20, 22, "Next verse"),                          # 4  ห่างมาก
    ]
    assert group_range(rows, 0, 0.6) == (0, 1)
    assert group_range(rows, 1, 0.6) == (0, 1)
    assert group_range(rows, 2, 0.6) == (2, 3)
    assert group_range(rows, 3, 0.6) == (2, 3)
    assert group_range(rows, 4, 0.6) == (4, 4)
    assert group_range(rows, 1, 0.05) == (1, 1)  # ช่องว่าง 0.1 > 0.05 -> แยก
    assert group_range(rows, 9, 0.6) == (9, 9)


def test_purge_stale_art_cache_runs_once(tmp_path: Path) -> None:
    from app.core import db as dbmod

    art = tmp_path / "art"
    art.mkdir()
    (art / "abc.itunes.jpg").write_bytes(b"x" * 10)
    (art / "def.youtube.jpg").write_bytes(b"y" * 10)
    conn = dbmod.connect(tmp_path / "t.sqlite3")
    try:
        assert dbmod.purge_stale_art_cache(conn, art) == 2 and not list(art.iterdir())
        (art / "new.jpg").write_bytes(b"z" * 10)           # ปกใหม่หลังล้าง ต้องไม่ถูกลบซ้ำ
        assert dbmod.purge_stale_art_cache(conn, art) == 0 and (art / "new.jpg").exists()
    finally:
        conn.close()
