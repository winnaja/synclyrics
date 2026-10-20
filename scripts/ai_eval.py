"""ทดสอบ pipeline "AI ฟังเสียงจัดเวลาเนื้อเพลง" กับคลิปจริงแบบไม่ต้องเปิดโปรแกรม (เฟส 4)

ใช้:  .venv\\Scripts\\python scripts\\ai_eval.py <videoId> [--no-demucs] [--no-mms] [--out ไฟล์.json]
ทำ: ดึงข้อมูล+เนื้อเพลงเหมือนในโปรแกรม -> โหลดเสียงมาวิเคราะห์ -> รัน worker ในโปรเซสนี้ -> พิมพ์สรุป
สรุปที่พิมพ์: coverage (จับคู่เนื้อเพลงกับเสียงได้กี่ %), offset/scale, เวลาต้นฉบับเทียบเวลาที่ AI จัด ของบรรทัดแรกๆ/กลาง/ท้าย,
ช่วงเสียงร้อง ใช้ดูว่า "เวลาตรงเสียงไหม" โดยไม่ต้องฟังทุกเพลง (ผู้ใช้ยังต้องฟังยืนยันตอนปิดเฟส)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import queue
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


async def get_lyrics(video_id: str, paths, settings, media):
    from app.lyrics.service import LyricsService
    from app.core.models import TrackRef

    info = await asyncio.to_thread(media.fetch_info, video_id)
    track = info.track if info is not None else TrackRef(video_id=video_id)
    svc = LyricsService(paths.db_file, settings.lyrics_sources)
    res = await svc.find(track, info.duration if info else None, {"subtitles": info.subtitles} if info else {}, lambda r: None)
    return info, res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--no-demucs", action="store_true")
    ap.add_argument("--no-mms", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--keep-audio", action="store_true")
    args = ap.parse_args()

    from app.ai.aligner import lyrics_to_input
    from app.ai.worker import Worker
    from app.core.config import ModelsConfig, Settings, load_model
    from app.core.paths import get_paths
    from app.media.youtube import YouTubeClient

    paths = get_paths()
    paths.ensure()
    settings, _ = load_model(paths, "settings.yaml", Settings)
    models, _ = load_model(paths, "models.yaml", ModelsConfig)
    mcfg = models.model_dump()
    if args.no_demucs:
        mcfg["demucs"]["enabled"] = False
    if args.no_mms:
        mcfg["align"]["enabled"] = False
    from app.audio.decoder import find_ffmpeg

    ff = find_ffmpeg()
    media = YouTubeClient(paths.cookies_file, ffmpeg_dir=ff.parent if ff else None)

    t0 = time.time()
    info, res = asyncio.run(get_lyrics(args.video_id, paths, settings, media))
    lyrics = res.chosen
    print(f"[{time.time() - t0:5.1f}s] วิดีโอ: {info.track.title if info else '?'} · ยาว {fmt(info.duration) if info else '?'}")
    print(f"         เนื้อเพลง: {res.source_label or 'ไม่พบ'}" + (f" · {len(lyrics.lines)} บรรทัด · ภาษา {lyrics.language}" if lyrics else ""))

    tmp = paths.cache_dir / "analysis" / args.video_id
    t1 = time.time()
    _info, dl = media.fetch_and_download(args.video_id, tmp)
    print(f"[{time.time() - t0:5.1f}s] โหลดเสียงเสร็จ ({dl.path.stat().st_size / 1e6:.1f} MB, โหลด {time.time() - t1:.1f}s)")

    rq: queue.Queue = queue.Queue()
    eq: queue.Queue = queue.Queue()
    w = Worker(rq, eq, {"models": mcfg, "stems_dir": str(paths.stems_cache_dir)})
    w.setup()
    print(f"[{time.time() - t0:5.1f}s] AI พร้อม device={w.device} vram_ว่าง={w.vram_mb()}")
    payload = {"job_id": "eval", "video_id": args.video_id, "audio_path": str(dl.path), "start_hint": 0.0,
               "lines": lyrics_to_input(lyrics) if lyrics else [], "language": lyrics.language if lyrics else None}
    w.job_align_song(payload)
    print(f"[{time.time() - t0:5.1f}s] เสร็จ")
    final = None
    partials = 0
    while not eq.empty():
        m = eq.get()
        if m["type"] == "result" and m["payload"]["kind"] == "align_final":
            final = m["payload"]["data"]
        elif m["type"] == "result":
            partials += 1
        elif m["type"] in ("failed", "degraded"):
            print("!!", m["type"], m["payload"].get("error") or m["payload"])
    if final is None:
        print("ไม่ได้ผลสุดท้าย")
        return 1
    print(f"ผลทยอย {partials} ครั้ง · coverage={final['coverage']:.0%} · offset={final.get('offset_s')} · scale={final.get('scale')} "
          f"· mismatch={final.get('version_mismatch')} · คำที่ AI ฟังได้ {final['transcript_words']} · ภาษา {final.get('language')}")
    vs = final["vocal_segments"]
    print(f"ช่วงเสียงร้อง {len(vs)} ช่วง: ร้องแรก {fmt(vs[0][0]) if vs else '-'} · ร้องสุดท้ายจบ {fmt(vs[-1][1]) if vs else '-'}")
    print(f"โหมดผล: {final['mode']}" + (f" (จับคู่เรียงลำดับได้ {final.get('mono_coverage', 0):.0%} -> สร้างตามลำดับที่ร้องจริง จับคู่ข้อความ {final['coverage']:.0%})" if final["mode"] == "reconstruct" else ""))
    if final["mode"] in ("reconstruct", "transcribe"):
        for ln in final["lines"][:40]:
            print(f"  {fmt(ln['start'])}-{fmt(ln['end'])} {'L' if ln.get('src') else 't'} {' '.join(ln['text_words'])[:70]}")
    if lyrics and vs and final["mode"] == "match":
        def voiced(a: float, b: float) -> float:
            tot = max(1e-6, b - a)
            return sum(max(0.0, min(b, e) - max(a, st)) for st, e in vs) / tot
        res_lines = [x for x in final["lines"] if x["resolved"]]
        src_ov = [voiced(src.start, src.end) for src in lyrics.lines]
        ai_ov = [voiced(x["start"], x["end"]) for x in res_lines]
        print(f"ความตรงกับเสียงร้องจริง (สัดส่วนเวลาบรรทัดที่อยู่ในช่วงมีเสียงร้อง): เวลาต้นฉบับ {sum(src_ov) / len(src_ov):.0%} -> เวลาที่ AI จัด "
              f"{sum(ai_ov) / max(1, len(ai_ov)):.0%} (เฉพาะ {len(res_lines)} บรรทัดที่จับคู่ได้)")
    if lyrics and vs and final["mode"] == "match":
        allv = [voiced(x["start"], x["end"]) for x in final["lines"] if x["end"] > x["start"]]
        print(f"ทุกบรรทัด (รวมที่ประมาณ): อยู่ในช่วงมีเสียงร้อง {sum(allv) / max(1, len(allv)):.0%}")
    if lyrics and final["mode"] == "match":
        lines = final["lines"]
        resolved = sum(1 for x in lines if x["resolved"])
        print(f"บรรทัดที่จับคู่กับเสียงได้ {resolved}/{len(lines)}")
        pick = list(range(min(6, len(lines)))) + list(range(len(lines) // 2, min(len(lines), len(lines) // 2 + 4))) + list(range(max(0, len(lines) - 4), len(lines)))
        print("  #   ต้นฉบับ -> AI    resolved  ข้อความ")
        for i in sorted(set(pick)):
            ln, src = lines[i], lyrics.lines[i]
            conf = sum(c for _a, _b, c in ln["words"]) / max(1, len(ln["words"]))
            print(f"{i:4d}  {fmt(src.start)} -> {fmt(ln['start'])}  {'✓' if ln['resolved'] else '~'} conf={conf:.2f}  {src.text[:48]}")
    if args.out:
        Path(args.out).write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
        print("บันทึก", args.out)
    if not args.keep_audio:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
