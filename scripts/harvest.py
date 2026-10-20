"""ดึงเพลงมาสร้างชุดข้อมูลสอน (dataset/songs/) — เนื้อเพลงรายคำจาก NetEase (เฉลยเวลา) + เสียงจาก YouTube → Demucs → เสียงร้อง 16 kHz

ใช้ (ปิดแอปก่อน: ใช้การ์ดจอ):
  .venv\\Scripts\\python scripts\\harvest.py --limit 50                  ดึงจากชาร์ต NetEase ในรายการ SEED_PLAYLISTS
  .venv\\Scripts\\python scripts\\harvest.py --queries my_songs.txt      บรรทัดละ "ศิลปิน - ชื่อเพลง" (เพลงไทย/เพลงที่ชอบ)
  .venv\\Scripts\\python scripts\\harvest.py --from-db copy.sqlite3      เพลงที่เคยเล่นในแอป (อ่านจากสำเนาฐานข้อมูล ห้ามชี้ไฟล์จริง)
ทำต่อจากที่ค้างได้ (ข้ามเพลงที่มีแล้ว) · หน่วงระหว่างเพลง --sleep วินาที (ค่าเริ่มต้น 8) กัน YouTube จำกัดบัญชี · ผลต่อเพลง ~6 MB

ต่อเพลง:
  1) ได้เนื้อเพลงรายคำ (YRC) จาก NetEase — ไม่มีรายคำ/น้อยกว่า 8 บรรทัด = ข้าม
  2) ค้น YouTube หาวิดีโอที่ความยาวต่างไม่เกิน 4 วิ (ไม่เอา live/cover/remix/karaoke) แล้วโหลดเสียง
  3) Demucs แยกเสียงร้อง → dataset/songs/ne<id>/vocals16k.npy (float16)
  4) CTC ทั้งเพลงหาค่าเลื่อนคงที่ระหว่างเฉลยกับเสียงนี้ (YouTube อาจตัดต่างจากแผ่น) เก็บเป็น ref_offset_s · ถ้าบรรทัดส่วนใหญ่ไม่เข้ากัน = ติดธง suspect (ไม่ใช้สอน)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# (id, ชื่อ) ของเพลย์ลิสต์ NetEase ที่ใช้เป็นเมล็ด — หลายภาษา/แนว (ตรวจแล้วว่าเรียกได้ 2026-10-21)
SEED_PLAYLISTS = [
    (2809513713, "欧美热歌"), (60198, "Billboard"), (745956260, "韩语榜"), (5059644681, "日语榜"), (19723756, "飙升榜"),
    (3778678, "热歌榜"), (3779629, "新歌榜"), (2884035, "原创榜"), (991319590, "中文说唱榜"), (71385702, "ACG榜"),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Referer": "https://music.163.com/"}
BAD_WORDS = re.compile(r"\b(live|cover|remix|karaoke|instrumental|sped up|slowed|nightcore|reverb|8d|acoustic|concert|reaction|lyrics video|tutorial)\b", re.I)
MIN_LINES = 8
DUR_TOL_S = 4.0


def http_json(url: str, params: dict) -> dict | None:
    import httpx

    try:
        r = httpx.get(url, params=params, headers=HEADERS, timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def playlist_tracks(pid: int) -> list[dict]:
    d = http_json("https://music.163.com/api/playlist/detail", {"id": pid}) or {}
    return (d.get("result") or {}).get("tracks") or []


def netease_lyrics(song: dict):
    """-> (Lyrics รายคำ | None)"""
    from app.lyrics.sources.netease import build_lyrics

    data = http_json("https://music.163.com/api/song/lyric", {"id": song["id"], "lv": 1, "kv": 1, "tv": -1, "yv": 1})
    if not isinstance(data, dict) or not ((data.get("yrc") or {}).get("lyric") or "").strip():
        return None
    cand = build_lyrics(song, data)
    if cand is None or cand.lyrics.timing.value != "word" or len(cand.lyrics.lines) < MIN_LINES:
        return None
    return cand.lyrics


def search_song(query: str) -> dict | None:
    d = http_json("https://music.163.com/api/search/get", {"s": query, "type": 1, "limit": 3, "offset": 0})
    songs = ((d or {}).get("result") or {}).get("songs") or []
    return songs[0] if songs else None


def pick_youtube(yt, song: dict, query: str):
    """ผลค้นหา YouTube ที่ความยาวใกล้ที่สุดและไม่ใช่ live/cover ฯลฯ"""
    dur = (song.get("duration") or song.get("dt") or 0) / 1000.0
    best = None
    for t in yt.search(query, limit=6):
        title = f"{t.title} {t.channel}"
        if BAD_WORDS.search(title) or not t.duration:
            continue
        diff = abs(float(t.duration) - dur)
        if diff <= DUR_TOL_S and (best is None or diff < best[0]):
            best = (diff, t)
    return best[1] if best else None


def lyrics_ref(lyr) -> list[dict]:
    return [{"start": ln.start, "end": ln.end, "words": [[w.text, w.start, w.end] for w in ln.words]} for ln in lyr.lines]


def process_song(ctx: dict, song: dict, lyr, yt_id: str | None, query: str) -> str:
    import numpy as np

    from app.ai.pipeline import align, audio, stems
    from app.ai.pipeline.match import InLine, ctc_to_result

    out = ctx["out"] / f"ne{song['id']}"
    if (out / "vocals16k.npy").exists():
        return "มีแล้ว"
    yt = ctx["yt"]
    if yt_id is None:
        picked = pick_youtube(yt, song, query)
        if picked is None:
            return "ไม่เจอวิดีโอที่ความยาวตรงกัน"
        yt_id = picked.video_id
    tmp = ctx["tmp"] / yt_id
    try:
        _info, dl = yt.fetch_and_download(yt_id, tmp)
        stereo = audio.decode(str(dl.path), 44100, 2, max_seconds=700)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        return f"โหลดเสียงไม่ได้: {str(e)[:80]}"
    shutil.rmtree(tmp, ignore_errors=True)
    w = ctx["worker"]
    voc = stems.separate_vocals(w.demucs(), stereo, w.device, w.mcfg.get("demucs", {}))
    v16 = stems.to_mono_16k(voc, 44100, w.device)
    # หาค่าเลื่อนคงที่ระหว่างเฉลยกับเสียงนี้
    lines = [InLine(words=[x.text for x in ln.words], start=ln.start, end=ln.end) for ln in lyr.lines]
    g = align.align_global(w.mms(), v16, [ln.words for ln in lines], None)
    res = ctc_to_result(g, lines)
    suspect = res is None
    offset = float(res.offset_s) if res is not None and res.offset_s is not None else None
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "vocals16k.npy", v16.astype(np.float16))
    artists = song.get("artists") or song.get("ar") or []
    meta = {"source": "harvest", "netease_id": song["id"], "youtube_id": yt_id, "title": song.get("name"),
            "artist": ", ".join(a.get("name", "") for a in artists), "duration": len(v16) / 16000.0, "language": lyr.language,
            "ref_offset_s": offset, "suspect": suspect, "ref": lyrics_ref(lyr), "recorded_at": time.time()}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return "ผ่าน" if not suspect else "บันทึกแล้วแต่ติดธง suspect (เฉลยไม่เข้ากับเสียง)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50, help="จำนวนเพลงสูงสุดที่ดึงรอบนี้")
    ap.add_argument("--queries", default="", help="ไฟล์บรรทัดละ 'ศิลปิน - ชื่อเพลง'")
    ap.add_argument("--from-db", default="", help="สำเนา sqlite ของแอป: ใช้เพลงที่เคยเล่น")
    ap.add_argument("--sleep", type=float, default=8.0)
    ap.add_argument("--no-playlists", action="store_true")
    ap.add_argument("--list", action="store_true", help="แค่แสดงรายการเพลงที่จะดึง (ไม่โหลด ไม่ใช้การ์ดจอ)")
    args = ap.parse_args()

    from app.ai.env import setup_ai_environment
    from app.audio.decoder import find_ffmpeg
    from app.core.config import ModelsConfig, load_model
    from app.core.dataset import DATASET_DIR
    from app.core.paths import get_paths
    from app.media.youtube import YouTubeClient

    if args.list:
        done_ids = {p.parent.name for p in (DATASET_DIR / "songs").glob("*/vocals16k.npy")} if (DATASET_DIR / "songs").exists() else set()
        n = 0
        for pid, name in SEED_PLAYLISTS:
            tracks = playlist_tracks(pid)
            print(f"\n== {name} ({pid}) — {len(tracks)} เพลง")
            for t in tracks:
                n += 1
                arts = ", ".join(a.get("name", "") for a in (t.get("artists") or []))
                mark = " [มีแล้ว]" if f"ne{t['id']}" in done_ids else ""
                print(f"  {n:4d}. {arts} - {t.get('name')}{mark}")
        return 0

    paths = get_paths()
    cfg, _ = load_model(paths, "models.yaml", ModelsConfig)
    setup_ai_environment(cfg.model_dump())
    import queue

    import torch  # noqa: F401

    from app.ai.worker import Worker

    worker = Worker(queue.Queue(), None, {"models": cfg.model_dump(), "stems_dir": str(paths.stems_cache_dir)})
    worker.emit = lambda *a, **k: None  # type: ignore[assignment]
    worker.setup()
    ff = find_ffmpeg()
    yt = YouTubeClient(paths.cookies_file, ffmpeg_dir=ff.parent if ff else None)
    ctx = {"out": DATASET_DIR / "songs", "tmp": ROOT / "dataset" / "_tmp", "worker": worker, "yt": yt}
    ctx["out"].mkdir(parents=True, exist_ok=True)

    todo: list[tuple[dict, str | None, str]] = []      # (netease song, youtube id หรือ None, คำค้น)
    if args.from_db:
        import sqlite3

        con = sqlite3.connect(args.from_db)
        for vid, title, channel in con.execute("select video_id, yt_title, channel from tracks where yt_title<>'' order by last_played_at desc"):
            q = f"{(channel or '').replace(' - Topic', '')} {title}".strip()
            song = search_song(q)
            if song:
                todo.append((song, vid, q))
    if args.queries:
        for ln in Path(args.queries).read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                song = search_song(ln.replace(" - ", " "))
                if song:
                    todo.append((song, None, ln))
    if not args.no_playlists:
        for pid, name in SEED_PLAYLISTS:
            for song in playlist_tracks(pid):
                arts = song.get("artists") or []
                todo.append((song, None, f"{arts[0]['name'] if arts else ''} {song.get('name')} audio"))
    seen: set[int] = set()
    done = skipped = 0
    t0 = time.time()
    for song, yt_id, query in todo:
        if done >= args.limit:
            break
        if song["id"] in seen:
            continue
        seen.add(song["id"])
        if (ctx["out"] / f"ne{song['id']}" / "vocals16k.npy").exists():
            continue
        lyr = netease_lyrics(song)
        if lyr is None:
            skipped += 1
            continue
        status = process_song(ctx, song, lyr, yt_id, query)
        print(f"[{done + 1}/{args.limit}] {song.get('name')} — {status}  ({(time.time() - t0) / 60:.1f} นาที)", flush=True)
        if status.startswith(("ผ่าน", "บันทึก")):
            done += 1
        time.sleep(args.sleep)
    print(f"เสร็จ: เพิ่ม {done} เพลง, ข้าม (ไม่มีเนื้อรายคำ) {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
