"""ทดสอบ AI แบบครบวงจรจริง: AiClient (เปิด worker process จริง) + LyricsAligner + EventBus — ไม่เปิด UI

ใช้:  .venv\\Scripts\\python scripts\\ai_e2e.py <videoId> [--translate]
พิมพ์เวลาที่ผลแรก/ผลสุดท้ายมาถึง และสรุปเหตุการณ์ LYRICS_RETIMED / TRANSLATION_READY (ตรวจ spawn, queue, thread ฟัง, cache)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--translate", action="store_true")
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args()

    from app.ai.aligner import LyricsAligner
    from app.ai.client import AiClient
    from app.ai.translator import LyricsTranslator
    from app.audio.decoder import find_ffmpeg
    from app.core import events as ev
    from app.core.config import ModelsConfig, Settings, load_model
    from app.core.events import EventBus
    from app.core.paths import get_paths
    from app.lyrics.service import LyricsService
    from app.media.youtube import YouTubeClient

    paths = get_paths()
    paths.ensure()
    settings, _ = load_model(paths, "settings.yaml", Settings)
    models, _ = load_model(paths, "models.yaml", ModelsConfig)
    mdict = models.model_dump()
    ff = find_ffmpeg()
    media = YouTubeClient(paths.cookies_file, ffmpeg_dir=ff.parent if ff else None)
    bus = EventBus()
    t0 = time.time()
    log: list[tuple[float, str, dict]] = []
    for topic in (ev.LYRICS_RETIMED, ev.TRANSLATION_READY, ev.AI_STATUS):
        bus.subscribe(topic, lambda t, p, _t=topic: log.append((time.time() - t0, t, p)))

    ai = AiClient(mdict, paths.stems_cache_dir)
    print("AI start:", ai.start(), ai.last_error)
    aligner = LyricsAligner(ai, bus, paths.db_file, paths, media, mdict)
    translator = LyricsTranslator(ai, bus, paths.db_file, mdict)

    async def run() -> None:
        info = await asyncio.to_thread(media.fetch_info, args.video_id)
        svc = LyricsService(paths.db_file, settings.lyrics_sources)
        res = await svc.find(info.track, info.duration, {"subtitles": info.subtitles}, lambda r: None)
        print(f"[{time.time() - t0:5.1f}s] เนื้อเพลง {res.source_label or 'ไม่พบ'}")
        await aligner.start(args.video_id, res.chosen, res.source_label, info.duration)
        if args.translate and res.chosen is not None:
            await translator.start(args.video_id, res.chosen)
        want = {ev.LYRICS_RETIMED: False, ev.TRANSLATION_READY: not args.translate}
        end = time.time() + args.timeout
        while time.time() < end and not all(want.values()):
            await asyncio.sleep(0.5)
            for _t, topic, p in log:
                if topic == ev.LYRICS_RETIMED and p.get("final"):
                    want[ev.LYRICS_RETIMED] = True
                if topic == ev.TRANSLATION_READY:
                    want[ev.TRANSLATION_READY] = True

    asyncio.run(run())
    print(f"ai.available={ai.available} device={ai.device} degraded={ai.degraded} err={ai.last_error!r}")
    for t, topic, p in log:
        extra = ""
        if topic == ev.LYRICS_RETIMED:
            ly = p["lyrics"]
            extra = f"final={p['final']} lines={len(ly.lines)} label={p['source_label']!r} gaps={len(p.get('gaps') or [])} ai={ly.ai_transcribed}"
        elif topic == ev.TRANSLATION_READY:
            tr = p["translations"]
            extra = f"lines={len(tr)} sample={[x for x in tr if x][:6]}"
        else:
            extra = f"{p.get('state')} {p.get('text')}"
        print(f"  [{t:6.1f}s] {topic} {extra}")
    ai.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
