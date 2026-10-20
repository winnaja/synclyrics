"""จุดเริ่มโปรแกรม: ประกอบทุกส่วนเข้าด้วยกันตามลำดับที่ปลอดภัย (ARCHITECTURE.md §1)

ลำดับการเปิด:
  1. ตรวจ Safe Mode (กด Shift ค้างตอนเปิด หรือ --safe-mode) -> ปิดเอฟเฟกต์และ AI ทั้งหมด
  2. single instance: มีตัวเดิมอยู่ -> ส่ง focus + argv แล้วปิดตัวเอง
  3. paths.ensure(), setup_logging(), โหลด config (พังใช้ค่าเริ่มต้น), เปิด DB (migration)
  4. สร้าง EventBus, AudioEngine (start ก่อนอย่างอื่น — เสียงต้องพร้อมเสมอ)
  5. สร้าง IO thread (asyncio loop) สำหรับ yt-dlp / เนื้อเพลง / ปก
  6. AiClient.start() ใน background (ไม่บล็อก UI; ไม่มี GPU = โหมดไม่มี AI)
  7. BridgeServer.start(), health check ใน background
  8. กู้สถานะล่าสุด (state.json) แล้วเปิด UI (run_ui) — UI พังต้องไม่ทำให้เสียงหยุด

ทุกขั้นห่อด้วย try/except: ขั้นไหนพัง log + ข้อความเข้าใจง่าย + ใช้ fallback แล้วไปต่อ
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LaunchOptions:
    safe_mode: bool = False
    from_host: bool = False       # เปิดโดย native host (ส่วนขยายกด) — ไม่ต้องเปิด Chrome ซ้ำ
    minimized: bool = False       # เปิดพร้อม Windows -> ย่อไป tray
    open_url: str | None = None   # ลิงก์ YouTube ที่ส่งมาทาง argv


def parse_args(argv: list[str]) -> LaunchOptions:
    p = argparse.ArgumentParser(prog="SyncLyrics")
    p.add_argument("--safe-mode", action="store_true", help="ปิดเอฟเฟกต์และ AI ทั้งหมด")
    p.add_argument("--from-host", action="store_true")
    p.add_argument("--minimized", action="store_true")
    p.add_argument("url", nargs="?")
    a = p.parse_args(argv)
    return LaunchOptions(a.safe_mode, a.from_host, a.minimized, a.url)


def shift_held() -> bool:
    """กด Shift ค้างตอนเปิดโปรแกรม = Safe Mode (GetAsyncKeyState ผ่าน ctypes ไม่ต้องมี Qt)"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        VK_SHIFT = 0x10
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
    except Exception:
        return False


def _setup_core(opts: LaunchOptions) -> Any:
    """ขั้นที่ 3-5: path, log, config, DB, EventBus, IO thread — คืนวัตถุรวม (SimpleNamespace)"""
    from types import SimpleNamespace

    from app.core import db as dbmod
    from app.core.config import Settings, load_model
    from app.core.events import EventBus
    from app.core.io_thread import IoThread
    from app.core.log import get_logger, setup_logging
    from app.core.paths import get_paths

    paths = get_paths()
    paths.ensure()
    setup_logging(paths.logs_dir)
    log = get_logger("app")
    settings, warnings = load_model(paths, "settings.yaml", Settings)
    for w in warnings:
        log.warning("config", extra={"data": {"warning": w}})
    if settings.overlay.mode == "full":  # ค่าเก่า: โหมดเต็มตอนนี้เป็นหน้าต่างแยก (fullwindow)
        settings.overlay.mode = "focus"
    conn = dbmod.connect(paths.db_file)  # รัน migration ครั้งเดียวก่อนทุก thread
    try:
        if dbmod.purge_stale_companion_cache(conn):
            log.info("ล้างแคชเนื้อเพลง/ชื่อเพลงที่อาจบันทึกผิดจากบั๊กเดิมของส่วนขยาย (ครั้งเดียว)")
        n_art = dbmod.purge_stale_art_cache(conn, paths.art_cache_dir)
        if n_art:
            log.info("ล้างแคชปกที่อาจบันทึกผิดเพลง (ครั้งเดียว)", extra={"data": {"files": n_art}})
    finally:
        conn.close()
    bus = EventBus()
    io = IoThread().start()
    return SimpleNamespace(paths=paths, settings=settings, warnings=warnings, bus=bus, io=io, log=log)


def _start_engine(core: Any) -> Any:
    """ขั้นที่ 4: เสียงต้องพร้อมก่อนอย่างอื่น — เปิดไม่สำเร็จ: คืนเอนจินที่ยังไม่ทำงาน + ข้อความให้ UI แจ้ง"""
    from app.audio.engine import AudioEngine, EngineConfig

    pb = core.settings.playback
    engine = AudioEngine(EngineConfig(device=pb.output_device, buffer_ms=pb.buffer_ms))
    try:
        # แอปแสดงเนื้อเพลงอย่างเดียว: ไม่เปิดอุปกรณ์เสียงเลย (ไม่แย่งอุปกรณ์/ไม่มีปัญหาเสียงสะดุดของฝั่งแอป)
        engine.start(open_stream=bool(pb.app_audio))
        core.engine_error = None
    except Exception as e:
        core.log.exception("เปิดอุปกรณ์เสียงไม่ได้")
        core.engine_error = f"เปิดอุปกรณ์เสียงไม่ได้: {e}"
    return engine


def main(argv: list[str] | None = None) -> int:
    """ประกอบทุกส่วนตามลำดับที่ปลอดภัย (ดูด้านบน) ส่วนที่พังข้ามอย่างปลอดภัย"""
    args = sys.argv[1:] if argv is None else argv
    opts = parse_args(args)
    opts.safe_mode = opts.safe_mode or shift_held()

    # 2. single instance — ต้องทำก่อนสร้างอะไรหนักๆ
    from app.bridge.pipe_server import BridgeServer, notify_existing_instance

    if notify_existing_instance(args):
        return 0

    core = _setup_core(opts)
    log = core.log
    log.info("เริ่มโปรแกรม", extra={"data": {"safe_mode": opts.safe_mode, "args": args}})

    from app.core.events import ERROR, HEALTH_REPORT
    from app.lyrics import thai
    from app.lyrics.service import LyricsService
    from app.media.youtube import YouTubeClient
    from app.player.controller import PlayerController
    from app.player.state import load_state
    from app.ui.app_window import UiContext, run_ui

    engine = _start_engine(core)
    media_dir = None
    try:
        from app.audio.decoder import find_ffmpeg

        ff = find_ffmpeg()
        media_dir = ff.parent if ff else None
        if ff is None:
            core.engine_error = (core.engine_error or "") + " ไม่พบ ffmpeg — ติดตั้ง ffmpeg แล้วเปิดใหม่"
    except Exception:
        log.exception("ตรวจ ffmpeg ไม่สำเร็จ")
    media = YouTubeClient(core.paths.cookies_file, ffmpeg_dir=media_dir)
    lyrics = LyricsService(core.paths.db_file, core.settings.lyrics_sources)
    controller = PlayerController(engine, core.bus, lyrics, media, None, core.paths.db_file, core.settings,
                                  paths=core.paths, io=core.io)
    controller.start_background_tasks()
    core.io.loop.call_soon_threadsafe(lambda: core.io.loop.run_in_executor(None, thai.warmup))  # เตรียมตัดคำไทย

    # เฟส 4: AI ฟังเสียงเบื้องหลังเพื่อจัดเวลาเนื้อเพลง (Safe Mode = ไม่เปิด) · ไม่มี torch/GPU = ข้ามเงียบๆ ใช้เวลาแบบประมาณ
    ai = None
    if not opts.safe_mode:
        try:
            from app.ai.aligner import LyricsAligner
            from app.ai.client import AiClient
            from app.ai.translator import LyricsTranslator
            from app.core.config import ModelsConfig, load_model

            models_cfg, mwarn = load_model(core.paths, "models.yaml", ModelsConfig)
            for w in mwarn:
                log.warning("config", extra={"data": {"warning": w}})
            mdict = models_cfg.model_dump()
            ai = AiClient(mdict, core.paths.stems_cache_dir)
            controller.ai = ai
            controller.aligner = LyricsAligner(ai, core.bus, core.paths.db_file, core.paths, media, mdict,
                                               position_fn=lambda: controller.remote_clock.position(),
                                               on_mismatch=controller.on_align_mismatch)
            controller.translator = LyricsTranslator(ai, core.bus, core.paths.db_file, mdict)
            from app.core.events import LYRICS_RETIMED

            core.bus.subscribe(LYRICS_RETIMED, controller.on_lyrics_retimed)
            if core.settings.ai.enabled:   # ปิดไว้ในตั้งค่า = ไม่เปิด worker/ไม่กิน VRAM (เปิดทีหลังได้ controller จะเปิดให้เมื่อมีงาน)
                core.io.loop.call_soon_threadsafe(lambda: core.io.loop.run_in_executor(None, ai.start))  # เปิด worker ใน thread ไม่บล็อก UI
        except Exception:
            log.exception("เตรียม AI ไม่สำเร็จ (ใช้เวลาแบบประมาณแทน)")

    bridge = BridgeServer(core.bus)
    window: dict[str, Any] = {}

    from app.bridge.service import BridgeService, load_selectors

    service = BridgeService(
        core.bus, controller, bridge.send,
        selectors_loader=lambda: load_selectors(core.paths.user_config_dir, core.paths.default_config_dir),
        raise_window=lambda: (window.get("raise") or (lambda: None))(), settings=core.settings,
        show_settings=lambda: (window.get("settings") or (lambda: None))())

    def install_extension() -> str:
        """ปุ่มติดตั้งส่วนขยายใน UI (UI thread): คัดลอก + ลงทะเบียน host + clipboard + เปิด chrome://extensions"""
        from PySide6.QtGui import QGuiApplication

        from app.bridge import installer

        res = installer.install(core.paths, set_clipboard=lambda t: QGuiApplication.clipboard().setText(t))
        if res.ok and res.changed:
            bridge.send("reload_extension", {})  # ส่วนขยายที่ติดตั้งอยู่แล้ว ให้โหลดไฟล์ใหม่
        return res.message

    def run_health() -> None:
        """ตรวจสุขภาพใน IO thread (ไม่บล็อก UI) แล้วส่งผลเข้า bus"""
        from app.audio.decoder import find_ffmpeg
        from app.bridge import registry
        from app.core import health

        items = health.run_health_checks(find_ffmpeg=find_ffmpeg, cookies_file=core.paths.cookies_file,
                                         is_ext_registered=registry.is_registered, engine_error=core.engine_error,
                                         app_audio=core.settings.playback.app_audio)
        text = health.format_problems(items)
        if text:
            log.warning("ตรวจสุขภาพ: มีปัญหา", extra={"data": {"problems": [i.id for i in items if not i.ok]}})
        core.bus.publish(HEALTH_REPORT, {"items": items, "text": text})

    def on_started(raise_window: Any, show_settings: Any = None) -> None:
        """เรียกใน UI thread หลัง QML โหลดแล้ว: เปิด named pipe + แจ้ง error ที่ค้าง + กู้สถานะ"""
        window["raise"] = raise_window
        window["settings"] = show_settings
        if not bridge.start():
            log.error("เปิด bridge ไม่สำเร็จ (ส่วนขยายจะต่อไม่ได้ แต่โปรแกรมเล่นเพลงได้ปกติ)")
        if core.engine_error:
            core.bus.publish(ERROR, {"module": "audio", "message": core.engine_error,
                                     "user_message": core.engine_error, "recoverable": False})
        core.io.loop.call_soon_threadsafe(lambda: core.io.loop.run_in_executor(None, run_health))
        if opts.open_url:
            controller.play_url(opts.open_url)
        else:
            state = load_state(core.paths.state_file)
            if state:
                controller.restore(state)

    def shutdown() -> None:
        controller.shutdown()
        if ai is not None:
            try:
                ai.stop()
            except Exception:
                log.exception("ปิด AI worker ไม่สำเร็จ")
        try:
            bridge.stop()
        except Exception:
            log.exception("ปิด bridge ไม่สำเร็จ")
        engine.stop()
        core.io.stop()

    from app.core.config import save_settings

    def quit_app() -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.quit()

    ctx = UiContext(bus=core.bus, get_clock=controller.get_clock, controller=controller,
                    settings=core.settings, shutdown=shutdown, on_started=on_started,
                    actions={"install_extension": install_extension,
                             "reconnect_youtube": lambda: bridge.send("reload_extension", {})},
                    save_settings=lambda: save_settings(core.paths, core.settings), data_dir=str(core.paths.home),
                    quit_app=quit_app, global_hotkeys=not opts.safe_mode)
    try:
        return run_ui(ctx, safe_mode=opts.safe_mode)
    except Exception:
        # UI พังต้องไม่ทำให้เสียงหยุดทันที แต่ไม่มี UI ผู้ใช้ควบคุมไม่ได้ — log แล้วปิดอย่างเรียบร้อย
        log.exception("UI พัง")
        shutdown()
        return 1
