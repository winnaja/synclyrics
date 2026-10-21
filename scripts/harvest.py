"""ดึงเพลงมาสร้างชุดข้อมูลสอน (dataset/songs/) — เนื้อเพลงจาก NetEase (เฉลยเวลา) + เสียงจาก YouTube → Demucs → เสียงร้อง 16 kHz

ใช้ (ปิดแอปก่อน: ใช้การ์ดจอ):
  .venv\\Scripts\\python scripts\\harvest.py --plan 2000                 ดึงตามแผนหมวด ~2000 เพลง (ไทย/สากล/เกาหลี/ญี่ปุ่น/จีน/รีมิกซ์ + ช้า/เร็ว) สลับหมวดให้สมดุลทุกช่วง
  .venv\\Scripts\\python scripts\\harvest.py --plan 2000 --list          แค่แสดงรายการที่จะดึง (ไม่โหลด ไม่ใช้การ์ดจอ) → dataset/harvest_queue.txt
  .venv\\Scripts\\python scripts\\harvest.py --limit 50                  ชาร์ตเริ่มต้น (SEED_PLAYLISTS) แบบเดิม
  .venv\\Scripts\\python scripts\\harvest.py --queries my_songs.txt      บรรทัดละ "ศิลปิน - ชื่อเพลง"
  .venv\\Scripts\\python scripts\\harvest.py --from-db copy.sqlite3      เพลงที่เคยเล่นในแอป (อ่านจากสำเนาฐานข้อมูล ห้ามชี้ไฟล์จริง)
ทำต่อจากที่ค้างได้ (ข้ามเพลงที่มีแล้ว) · หน่วงระหว่างเพลง --sleep วินาที (ค่าเริ่มต้น 8) กัน YouTube จำกัดบัญชี · ผลต่อเพลง ~6 MB · ~35 วิ/เพลง

ต่อเพลง:
  1) เนื้อเพลงรายคำ (YRC) จาก NetEase — ไม่มีรายคำ = ใช้ระดับบรรทัด (LRC) แทน (ติด ref_timing="line": ใช้เทรน CTC ได้ แต่ไม่ใช้วัดเวลารายคำ) · น้อยกว่า 8 บรรทัด = ข้าม
  2) ค้น YouTube หาวิดีโอที่ความยาวต่างไม่เกิน 4 วิ (ไม่เอา live/cover/karaoke ฯลฯ; หมวดรีมิกซ์อนุญาตคำว่า remix/DJ) แล้วโหลดเสียง
  3) Demucs แยกเสียงร้อง → dataset/songs/ne<id>/vocals16k.npy (float16)
  4) CTC ทั้งเพลงหาค่าเลื่อนคงที่ระหว่างเฉลยกับเสียงนี้ (ref_offset_s) · เฉลยไม่เข้ากับเสียง = ติดธง suspect (ไม่ใช้สอน)
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

# (id, ชื่อ) ของเพลย์ลิสต์ NetEase แบบเดิม (ใช้กับ --limit)
SEED_PLAYLISTS = [
    (2809513713, "欧美热歌"), (60198, "Billboard"), (745956260, "韩语榜"), (5059644681, "日语榜"), (19723756, "飙升榜"),
    (3778678, "热歌榜"), (3779629, "新歌榜"), (2884035, "原创榜"), (991319590, "中文说唱榜"), (71385702, "ACG榜"),
]

# แผนหมวด: สัดส่วนของจำนวนเพลงรวม · playlists = id ที่ตรวจแล้ว · keywords = ค้นเพลย์ลิสต์ NetEase แล้วเอาอันที่คนฟังมากสุดไม่เกิน top
# ช้า/เร็ว: หมวดต่างๆ ผสมเพลย์ลิสต์เพลงช้า (慢歌) และเพลงเร็ว (快歌/DJ) · remix = Douyin DJ remix
PLAN: dict[str, dict] = {
    "thai": {"share": 0.175, "playlists": [7095271308, 2193969739, 13016675, 2906886473, 89345375], "keywords": ["泰语", "泰国歌曲", "泰语流行"], "top": 2},
    "western": {"share": 0.24, "playlists": [2809513713, 60198, 7026393081, 903909932, 8637589200],
                "keywords": ["欧美慢歌", "欧美流行"], "top": 2},
    "korean": {"share": 0.19, "playlists": [745956260, 380465612, 2576219155, 386400687, 8216958348], "keywords": ["韩国独立音乐", "K-Indie", "韩语"], "top": 2},
    "japanese": {"share": 0.13, "playlists": [5059644681, 164238075, 7562848371, 2210309970], "keywords": ["日语"], "top": 2},
    "chinese": {"share": 0.165, "playlists": [3778678, 12740998746, 8596628206, 2219061646, 4983135357], "keywords": ["华语流行", "华语快歌", "慢歌"], "top": 2},
    "remix": {"share": 0.01, "playlists": [9778099003, 2833353252, 7375318202], "keywords": ["抖音DJ", "抖音remix"], "top": 2, "allow_remix": True},
    "slow_fast": {"share": 0.09, "playlists": [888011144, 4922619465, 802073292, 7605235874, 13883512679], "keywords": ["慢歌", "快歌"], "top": 2},
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Referer": "https://music.163.com/", "Cookie": "os=pc; appver=2.9.7"}
BAD_WORDS = re.compile(r"\b(live|cover|remix|karaoke|instrumental|sped up|slowed|nightcore|reverb|8d|acoustic|concert|reaction|lyrics video|tutorial)\b", re.I)
BAD_WORDS_NO_REMIX = re.compile(r"\b(live|cover|karaoke|instrumental|sped up|slowed|nightcore|reverb|8d|acoustic|concert|reaction|lyrics video|tutorial)\b", re.I)
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
    """เพลงในเพลย์ลิสต์ (สูงสุด 1000) · v3 คืนครบ ส่วน API เดิมคืนแค่ 10 เพลงแรกของเพลย์ลิสต์ผู้ใช้"""
    d = http_json("https://music.163.com/api/v3/playlist/detail", {"id": pid, "n": 100000, "s": 0}) or {}
    tr = (d.get("playlist") or {}).get("tracks") or []
    if tr:
        return tr
    d = http_json("https://music.163.com/api/playlist/detail", {"id": pid}) or {}
    return (d.get("result") or {}).get("tracks") or []


def artists_of(song: dict) -> list[dict]:
    return song.get("artists") or song.get("ar") or []


def search_playlists(keyword: str, top: int) -> list[int]:
    d = http_json("https://music.163.com/api/search/get", {"s": keyword, "type": 1000, "limit": 12}) or {}
    pls = (d.get("result") or {}).get("playlists") or []
    pls = [p for p in pls if (p.get("trackCount") or 0) >= 20]
    pls.sort(key=lambda p: p.get("playCount") or 0, reverse=True)
    return [int(p["id"]) for p in pls[:top]]


def netease_lyrics(song: dict):
    """-> (Lyrics, ระดับเวลา "word"|"line") หรือ (None, None) · รายคำ (YRC) ก่อน ไม่มีใช้ LRC ระดับบรรทัด"""
    from app.lyrics.sources.netease import build_lyrics

    data = http_json("https://music.163.com/api/song/lyric", {"id": song["id"], "lv": 1, "kv": 1, "tv": -1, "yv": 1})
    if not isinstance(data, dict):
        return None, None
    cand = build_lyrics(song, data)
    if cand is None or len(cand.lyrics.lines) < MIN_LINES:
        return None, None
    return cand.lyrics, ("word" if cand.lyrics.timing.value == "word" else "line")


def search_song(query: str) -> dict | None:
    d = http_json("https://music.163.com/api/search/get", {"s": query, "type": 1, "limit": 3, "offset": 0})
    songs = ((d or {}).get("result") or {}).get("songs") or []
    return songs[0] if songs else None


def pick_youtube(yt, song: dict, query: str, allow_remix: bool = False):
    """ผลค้นหา YouTube ที่ความยาวใกล้ที่สุดและไม่ใช่ live/cover ฯลฯ"""
    dur = (song.get("duration") or song.get("dt") or 0) / 1000.0
    bad = BAD_WORDS_NO_REMIX if allow_remix else BAD_WORDS
    best = None
    for t in yt.search(query, limit=6):
        title = f"{t.title} {t.channel}"
        if bad.search(title) or not t.duration:
            continue
        diff = abs(float(t.duration) - dur)
        if diff <= DUR_TOL_S and (best is None or diff < best[0]):
            best = (diff, t)
    return best[1] if best else None


def lyrics_ref(lyr) -> list[dict]:
    """เฉลย: ระดับบรรทัดไม่มีเวลารายคำจริง → ประมาณรายคำเพื่อให้โครงสร้างข้อมูลเหมือนกัน (ref_timing บอกว่าไม่ควรใช้วัดรายคำ)"""
    if lyr.timing.value != "word":
        from app.lyrics.timing_estimate import estimate_lyrics

        lyr = estimate_lyrics(lyr, lyr.duration or 240.0)
    return [{"start": ln.start, "end": ln.end, "words": [[w.text, w.start, w.end] for w in ln.words]} for ln in lyr.lines]


def process_song(ctx: dict, song: dict, lyr, level: str, yt_id: str | None, query: str, category: str = "", allow_remix: bool = False) -> str:
    import numpy as np

    from app.ai.pipeline import align, audio, stems
    from app.ai.pipeline.match import InLine, ctc_to_result

    out = ctx["out"] / f"ne{song['id']}"
    if (out / "vocals16k.npy").exists():
        return "มีแล้ว"
    yt = ctx["yt"]
    if yt_id is None:
        picked = pick_youtube(yt, song, query, allow_remix)
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
            "category": category, "allow_remix": allow_remix, "ref_timing": level,
            "ref_offset_s": offset, "suspect": suspect, "ref": lyrics_ref(lyr), "recorded_at": time.time()}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return "ผ่าน" if not suspect else "บันทึกแล้วแต่ติดธง suspect (เฉลยไม่เข้ากับเสียง)"


def build_plan(total: int) -> list[tuple[str, dict, bool]]:
    """-> [(หมวด, เพลง NetEase, allow_remix)] สลับหมวดตามสัดส่วนทุกช่วง (หยุดตรงไหนก็สมดุล) · เพลงซ้ำข้ามหมวดไม่นับซ้ำ"""
    import itertools

    cats: dict[str, list[dict]] = {}
    for name, cfg in PLAN.items():
        pids = list(cfg["playlists"])
        for kw in cfg.get("keywords", []):
            pids += search_playlists(kw, cfg.get("top", 2))
        seen_pl: set[int] = set()
        lists = []
        for pid in pids:
            if pid in seen_pl:
                continue
            seen_pl.add(pid)
            lists.append(playlist_tracks(pid))
        # สลับเพลย์ลิสต์ในหมวดให้เพลงช้า/เร็ว/แนวต่างๆ ปนกัน
        mixed = [t for grp in itertools.zip_longest(*lists) for t in grp if t]
        cats[name] = mixed
        print(f"  หมวด {name}: {len(mixed)} เพลงที่เป็นตัวเลือก (จาก {len(lists)} เพลย์ลิสต์)", flush=True)
    quota = {n: max(1, int(round(total * c["share"]))) for n, c in PLAN.items()}
    # ตัวเลือกต่อหมวดมากกว่าโควตา ~2.5 เท่า (บางเพลงไม่มีเนื้อ/วิดีโอ)
    cursors = {n: 0 for n in cats}
    out: list[tuple[str, dict, bool]] = []
    taken = {n: 0 for n in cats}
    used: set[int] = set()
    cap = {n: int(quota[n] * 2.6) for n in cats}
    while any(cursors[n] < len(cats[n]) and taken[n] < cap[n] for n in cats):
        for n in cats:
            for _ in range(max(1, int(quota[n] / 20))):      # สัดส่วนต่อรอบ ~ โควตา/20
                while cursors[n] < len(cats[n]) and cats[n][cursors[n]]["id"] in used:
                    cursors[n] += 1
                if cursors[n] >= len(cats[n]) or taken[n] >= cap[n]:
                    break
                song = cats[n][cursors[n]]
                cursors[n] += 1
                used.add(song["id"])
                taken[n] += 1
                out.append((n, song, bool(PLAN[n].get("allow_remix"))))
    print("โควตาเป้าหมาย:", quota, flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=int, default=0, help="ดึงตามแผนหมวด จำนวนเพลงรวมเป้าหมาย (เช่น 2000)")
    ap.add_argument("--limit", type=int, default=50, help="จำนวนเพลงสูงสุดที่ดึงรอบนี้ (โหมดไม่ใช้ --plan)")
    ap.add_argument("--queries", default="", help="ไฟล์บรรทัดละ 'ศิลปิน - ชื่อเพลง'")
    ap.add_argument("--from-db", default="", help="สำเนา sqlite ของแอป: ใช้เพลงที่เคยเล่น")
    ap.add_argument("--sleep", type=float, default=8.0)
    ap.add_argument("--no-playlists", action="store_true")
    ap.add_argument("--list", action="store_true", help="แค่แสดงรายการเพลงที่จะดึง (ไม่โหลด ไม่ใช้การ์ดจอ)")
    args = ap.parse_args()

    from app.core.dataset import DATASET_DIR

    done_dir = DATASET_DIR / "songs"

    def exists(song) -> bool:
        return (done_dir / f"ne{song['id']}" / "vocals16k.npy").exists()

    plan_items: list[tuple[str, dict, bool]] = []
    if args.plan:
        plan_items = build_plan(args.plan)
    if args.list:
        if plan_items:
            lines = []
            for i, (cat, t, rm) in enumerate(plan_items, 1):
                arts = ", ".join(a.get("name", "") for a in artists_of(t))
                lines.append(f"{i:5d}. [{cat}] {arts} - {t.get('name')}{' [มีแล้ว]' if exists(t) else ''}")
            DATASET_DIR.mkdir(parents=True, exist_ok=True)
            (DATASET_DIR / "harvest_queue.txt").write_text("\n".join(lines), encoding="utf-8")
            from collections import Counter

            print(f"รายการที่จะลอง {len(lines)} เพลง (บันทึกที่ dataset/harvest_queue.txt)")
            print("แยกตามหมวด:", dict(Counter(c for c, _t, _r in plan_items)))
            return 0
        n = 0
        for pid, name in SEED_PLAYLISTS:
            tracks = playlist_tracks(pid)
            print(f"\n== {name} ({pid}) — {len(tracks)} เพลง")
            for t in tracks:
                n += 1
                arts = ", ".join(a.get("name", "") for a in artists_of(t))
                print(f"  {n:4d}. {arts} - {t.get('name')}{' [มีแล้ว]' if exists(t) else ''}")
        return 0

    from app.ai.env import setup_ai_environment
    from app.audio.decoder import find_ffmpeg
    from app.core.config import ModelsConfig, load_model
    from app.core.paths import get_paths
    from app.media.youtube import YouTubeClient

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
    ctx = {"out": done_dir, "tmp": ROOT / "dataset" / "_tmp", "worker": worker, "yt": yt}
    ctx["out"].mkdir(parents=True, exist_ok=True)

    todo: list[tuple[str, dict, str | None, str, bool]] = []      # (หมวด, เพลง NetEase, youtube id หรือ None, คำค้น, อนุญาตรีมิกซ์)
    if args.from_db:
        import sqlite3

        con = sqlite3.connect(args.from_db)
        for vid, title, channel in con.execute("select video_id, yt_title, channel from tracks where yt_title<>'' order by last_played_at desc"):
            q = f"{(channel or '').replace(' - Topic', '')} {title}".strip()
            song = search_song(q)
            if song:
                todo.append(("history", song, vid, q, False))
    if args.queries:
        for ln in Path(args.queries).read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                song = search_song(ln.replace(" - ", " "))
                if song:
                    todo.append(("queries", song, None, ln, False))
    for cat, song, rm in plan_items:
        arts = artists_of(song)
        todo.append((cat, song, None, f"{arts[0]['name'] if arts else ''} {song.get('name')} audio", rm))
    if not args.no_playlists and not args.plan:
        for pid, name in SEED_PLAYLISTS:
            for song in playlist_tracks(pid):
                arts = artists_of(song)
                todo.append((name, song, None, f"{arts[0]['name'] if arts else ''} {song.get('name')} audio", False))

    target = args.plan or args.limit
    quota = {n: max(1, int(round(args.plan * c["share"]))) for n, c in PLAN.items()} if args.plan else {}
    got: dict[str, int] = {}
    seen: set[int] = set()
    done = skipped = 0
    t0 = time.time()
    for cat, song, yt_id, query, rm in todo:
        if done >= target:
            break
        if song["id"] in seen or exists(song):
            continue
        if quota and got.get(cat, 0) >= quota.get(cat, 10**9):
            continue
        seen.add(song["id"])
        lyr, level = netease_lyrics(song)
        if lyr is None:
            skipped += 1
            continue
        status = process_song(ctx, song, lyr, level or "line", yt_id, query, cat, rm)
        print(f"[{done + 1}/{target}] ({cat}) {song.get('name')} — {status}  ({(time.time() - t0) / 60:.1f} นาที)", flush=True)
        if status.startswith(("ผ่าน", "บันทึก")):
            done += 1
            got[cat] = got.get(cat, 0) + 1
        time.sleep(args.sleep)
    print(f"เสร็จ: เพิ่ม {done} เพลง, ข้าม (ไม่มีเนื้อ) {skipped} · ตามหมวด: {got}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
