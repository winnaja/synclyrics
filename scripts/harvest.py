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
import itertools
import json
import random
import re
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# (id, ชื่อ) ของเพลย์ลิสต์ NetEase แบบเดิม (ใช้กับ --limit)
SEED_PLAYLISTS = [
    (2809513713, "欧美热歌"), (60198, "Billboard"), (745956260, "韩语榜"), (5059644681, "日语榜"), (19723756, "飙升榜"),
    (3778678, "热歌榜"), (3779629, "新歌榜"), (2884035, "原创榜"), (991319590, "中文说唱榜"), (71385702, "ACG榜"),
]

# เพลย์ลิสต์ YouTube ของผู้ใช้ที่ต้องดึงทั้งหมดก่อนเสมอ (ไม่นับในโควตาหมวด) — เสียงมาจากวิดีโอในเพลย์ลิสต์โดยตรง ส่วนเนื้อเพลงหาจาก NetEase ตามชื่อ
YT_PLAYLISTS: list[str] = [
    # ใส่ลิงก์เพลย์ลิสต์ของตัวเองที่นี่ หรือส่งตอนรันด้วย --yt-playlist <ลิงก์> (ใส่ซ้ำได้)
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


def youtube_playlist_entries(yt, url: str) -> list[dict]:
    """รายการวิดีโอในเพลย์ลิสต์ YouTube (ไม่โหลดเสียง) -> [{id,title,channel,duration}]"""
    res, _ = yt._run(lambda ydl: ydl.extract_info(url, download=False), extract_flat=True)
    out = []
    for e in (res or {}).get("entries") or []:
        if e and e.get("id") and e.get("duration"):
            out.append({"id": e["id"], "title": e.get("title") or "", "channel": (e.get("channel") or e.get("uploader") or "").replace(" - Topic", ""),
                        "duration": float(e["duration"])})
    return out


def _plain(text: str) -> str:
    return re.sub(r"[\W_]+", "", re.sub(r"[\(\[（].*?[\)\]）]", "", text).casefold())


def match_netease_for_video(entry: dict, tol_s: float = 12.0) -> dict | None:
    """วิดีโอ YouTube -> เพลง NetEase ที่ชื่อ/ศิลปินตรงและความยาวใกล้กัน (MV ยาวกว่าเสียงได้ เผื่อ ~12 วิ)
    ให้คะแนน: ชื่อตรงเป๊ะ (ไม่นับวงเล็บ) > ขึ้นต้นตรง · ศิลปินตรงกับช่อง · ความยาวใกล้ · ตัดฉบับ Live/Remix/Inst ที่วิดีโอไม่ได้ระบุ · ไม่เจอที่น่าเชื่อถือ = None"""
    want = _plain(entry["title"])
    chan = entry["channel"].casefold()
    bad_in_video = bool(BAD_WORDS.search(entry["title"]))
    best: tuple[float, dict] | None = None
    for q in (f"{entry['channel']} {entry['title']}", entry["title"]):
        d = http_json("https://music.163.com/api/search/get", {"s": q, "type": 1, "limit": 8, "offset": 0})
        for s_ in ((d or {}).get("result") or {}).get("songs") or []:
            dur = (s_.get("duration") or s_.get("dt") or 0) / 1000.0
            if not dur or abs(dur - entry["duration"]) > tol_s:
                continue
            name = s_.get("name") or ""
            if BAD_WORDS.search(name) and not bad_in_video:
                continue
            nm = _plain(name)
            if not nm or not want:
                continue
            score = 0.0
            if nm == want:
                score += 10.0
            elif nm.startswith(want) or want.startswith(nm):
                score += 4.0
            else:
                continue
            arts = " ".join(a.get("name", "") for a in artists_of(s_)).casefold()
            if chan and (chan in arts or arts in chan or any(tok and tok in arts for tok in chan.split())):
                score += 3.0
            score -= abs(dur - entry["duration"]) / 12.0
            if best is None or score > best[0]:
                best = (score, s_)
        if best is not None and best[0] >= 10.0:
            break
    return best[1] if best else None


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


def fetch_song(ctx: dict, song: dict, yt_id: str | None, query: str, allow_remix: bool = False):
    """ส่วนที่ใช้เครือข่าย/ซีพียู (ค้น YouTube → โหลดเสียง → ถอดรหัส) — รันขนานในเธรดได้ · คืน (yt_id, stereo) หรือข้อความเหตุผลที่เฟล (str)"""
    from app.ai.pipeline import audio

    out = ctx["out"] / f"ne{song['id']}"
    if (out / "vocals16k.npy").exists():
        return "มีแล้ว"
    yt = ctx["yt"]()
    if yt_id is None:
        try:
            picked = pick_youtube(yt, song, query, allow_remix)
        except Exception as e:  # noqa: BLE001 — ค้นหาล้มเหลว (เน็ตสะดุด/โดนจำกัด) ต้องข้ามเพลงนี้ ไม่ใช่ล้มทั้งรอบ
            return f"ค้นหาวิดีโอไม่ได้: {str(e)[:80]}"
        if picked is None:
            return "ไม่เจอวิดีโอที่ความยาวตรงกัน"
        yt_id = picked.video_id
    tmp = ctx["tmp"] / yt_id
    try:
        _info, dl = yt.fetch_and_download(yt_id, tmp)
        stereo = audio.decode(str(dl.path), 44100, 2, max_seconds=700)
    except Exception as e:  # noqa: BLE001
        return f"โหลดเสียงไม่ได้: {str(e)[:80]}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return yt_id, stereo


def separate_song(ctx: dict, fetched):
    """Demucs แยกเสียงร้อง (การ์ดจอ ช่วงที่ 1) · fetched = ผลจาก fetch_song -> (yt_id, เสียงร้อง 16k) หรือข้อความเหตุผลที่เฟล"""
    from app.ai.pipeline import stems

    if isinstance(fetched, str):
        return fetched
    yt_id, stereo = fetched
    w = ctx["worker"]
    voc = stems.separate_vocals(w.demucs(), stereo, w.device, w.mcfg.get("demucs", {}))
    return yt_id, stems.to_mono_16k(voc, 44100, w.device)


def process_song(ctx: dict, song: dict, lyr, level: str, fetched, category: str = "", allow_remix: bool = False) -> str:
    """ช่วงที่ 2: CTC หาค่าเลื่อน + บันทึก · fetched = ผลจาก separate_song"""
    import numpy as np

    from app.ai.pipeline import align
    from app.ai.pipeline.match import InLine, ctc_to_result

    if isinstance(fetched, str):
        return fetched
    yt_id, v16 = fetched
    out = ctx["out"] / f"ne{song['id']}"
    w = ctx["worker"]
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


def build_plan(total: int, only: set[str] | None = None) -> list[tuple[str, dict, bool]]:
    """-> [(หมวด, เพลง NetEase, allow_remix)] สลับหมวดตามสัดส่วนทุกช่วง (หยุดตรงไหนก็สมดุล) · เพลงซ้ำข้ามหมวดไม่นับซ้ำ
    only = เอาเฉพาะหมวดเหล่านี้ (ใช้เก็บภาษาที่ข้อมูลยังน้อย)"""
    import itertools

    cats: dict[str, list[dict]] = {}
    for name, cfg in PLAN.items():
        if only and name not in only:
            continue
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
    ap.add_argument("--sleep", type=float, default=6.0, help="หน่วงหลังแตะ YouTube แต่ละครั้ง (สุ่ม ±40%) ต่อเธรด")
    ap.add_argument("--workers", type=int, default=2, help="จำนวนเธรดโหลดเสียงล่วงหน้าขนานกับการ์ดจอ")
    ap.add_argument("--batch", type=int, default=100, help="จำนวนเพลงต่อ 1 รอบ (รอบละ 100 เพลง) — ท้ายรอบจะลองเพลงที่เฟลใหม่ในรอบถัดไป")
    ap.add_argument("--max-attempts", type=int, default=3, help="ลองเพลงที่เฟลซ้ำสูงสุดกี่ครั้ง")
    ap.add_argument("--cookies-dir", default="", help="โฟลเดอร์ไฟล์ cookies.txt (หลายบัญชี) ที่จะหมุนใช้สลับกันทีละเพลง · ไม่ใส่ = ใช้ cookies ของแอป")
    ap.add_argument("--cats", default="", help="เก็บเฉพาะหมวดนี้ (คั่นด้วยจุลภาค เช่น thai,korean) — ใช้เติมภาษาที่ข้อมูลน้อย")
    ap.add_argument("--word-only", action="store_true", help="เก็บเฉพาะเพลงที่เฉลยเป็นเวลารายคำจริง (ใช้เพิ่มชุดวัดผล/สอนให้แม่นขึ้น)")
    ap.add_argument("--max-new", type=int, default=0, help="หยุดเมื่อได้เพลงใหม่ครบเท่านี้ (นับต่อจากที่มีอยู่) แทนเป้าทั้งหมดของ --plan")
    ap.add_argument("--no-playlists", action="store_true")
    ap.add_argument("--yt-playlist", action="append", default=[], help="เพลย์ลิสต์ YouTube เพิ่ม (ใส่ซ้ำได้) — ดึงก่อนทุกอย่าง")
    ap.add_argument("--list", action="store_true", help="แค่แสดงรายการเพลงที่จะดึง (ไม่โหลด ไม่ใช้การ์ดจอ)")
    args = ap.parse_args()

    from app.core.dataset import DATASET_DIR

    done_dir = DATASET_DIR / "songs"

    def exists(song) -> bool:
        return (done_dir / f"ne{song['id']}" / "vocals16k.npy").exists()

    plan_items: list[tuple[str, dict, bool]] = []
    if args.plan:
        plan_items = build_plan(args.plan, set(args.cats.split(",")) if args.cats else None)
    if args.list:
        from app.audio.decoder import find_ffmpeg as _ff
        from app.core.paths import get_paths as _gp
        from app.media.youtube import YouTubeClient as _YT

        _paths, _f = _gp(), _ff()
        _yt = _YT(_paths.cookies_file, ffmpeg_dir=_f.parent if _f else None)
        pl_lines = []
        for url in list(YT_PLAYLISTS) + list(args.yt_playlist):
            for en in youtube_playlist_entries(_yt, url):
                song = match_netease_for_video(en)
                pl_lines.append(f"[playlist] {en['channel']} - {en['title']} -> " + (f"NetEase {song['id']} {song['name']}" if song else "ไม่เจอเนื้อเพลง NetEase ที่ตรงกัน") + (" [มีแล้ว]" if song and exists(song) else ""))
        if pl_lines:
            DATASET_DIR.mkdir(parents=True, exist_ok=True)
            (DATASET_DIR / "harvest_playlist.txt").write_text("\n".join(pl_lines), encoding="utf-8")
            print(f"เพลย์ลิสต์ของคุณ: {len(pl_lines)} วิดีโอ จับคู่เนื้อเพลงได้ {sum(1 for l in pl_lines if 'ไม่เจอ' not in l)} (รายละเอียด dataset/harvest_playlist.txt)")
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
    tmp_root = ROOT / "dataset" / "_tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    local = threading.local()

    cookie_files = sorted(Path(args.cookies_dir).glob("*.txt")) if args.cookies_dir else []
    cookie_files = cookie_files or [paths.cookies_file]
    rr = itertools.count()
    if len(cookie_files) > 1:
        print(f"หมุนใช้ cookies {len(cookie_files)} บัญชีสลับกัน (กระจายภาระ ลดโอกาสโดนบล็อก)", flush=True)

    def yt_client():
        """yt-dlp เขียน cookies กลับไฟล์ตอนปิด: หลายเธรดแชร์ไฟล์เดียวจะเขียนทับกันจนไฟล์พัง (และไฟล์ของแอปด้วย)
        → แต่ละเธรดใช้สำเนาของตัวเอง ไม่แตะไฟล์จริง · ทุกครั้งที่เรียก (ต่อ 1 เพลง) สลับไฟล์ cookies ตามลำดับ"""
        mine = tmp_root / f"cookies_{threading.get_ident()}.txt"
        src = cookie_files[next(rr) % len(cookie_files)]
        if src.exists():
            shutil.copyfile(src, mine)
        return YouTubeClient(mine, ffmpeg_dir=ff.parent if ff else None)

    ctx = {"out": done_dir, "tmp": tmp_root, "worker": worker, "yt": yt_client}
    ctx["out"].mkdir(parents=True, exist_ok=True)

    todo: list[tuple[str, dict, str | None, str, bool]] = []      # (หมวด, เพลง NetEase, youtube id หรือ None, คำค้น, อนุญาตรีมิกซ์)
    for url in list(YT_PLAYLISTS) + list(args.yt_playlist):      # เพลย์ลิสต์ของผู้ใช้: ก่อนทุกอย่าง
        try:
            entries = youtube_playlist_entries(yt_client(), url)
        except Exception as e:  # noqa: BLE001
            print(f"อ่านเพลย์ลิสต์ไม่ได้ ({str(e)[:80]}): {url}")
            continue
        found = 0
        for en in entries:
            song = match_netease_for_video(en)
            if song:
                todo.append(("playlist", song, en["id"], f"{en['channel']} {en['title']}", False))
                found += 1
        print(f"เพลย์ลิสต์ {url[-34:]}: {len(entries)} วิดีโอ จับคู่เนื้อเพลง NetEase ได้ {found}", flush=True)
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
    sel = set(args.cats.split(",")) if args.cats else None
    pl = {n: c for n, c in PLAN.items() if not sel or n in sel}
    tot_share = sum(c["share"] for c in pl.values()) or 1.0
    quota = {n: max(1, int(round(args.plan * c["share"] / tot_share))) for n, c in pl.items()} if args.plan else {}
    state_dir = DATASET_DIR
    failed_path, skipped_path = state_dir / "harvest_failed.json", state_dir / "harvest_skipped.json"
    failed: dict[str, dict] = _load_json(failed_path)            # id -> {song, query, category, yt_id, allow_remix, attempts, reason}
    skipped_ids: set[str] = set(_load_json(skipped_path).keys())    # เพลงที่ไม่มีเนื้อ/สั้นเกินไป: ไม่ต้องตรวจซ้ำทุกรอบ
    # นับของที่มีอยู่แล้ว (ทำต่อจากรอบก่อนได้ โควตาไม่เกิน)
    got: dict[str, int] = {}
    for mp in (done_dir.glob("*/meta.json") if done_dir.exists() else []):
        try:
            c = json.loads(mp.read_text(encoding="utf-8")).get("category") or "?"
        except ValueError:
            continue
        got[c] = got.get(c, 0) + 1
    done = sum(v for k, v in got.items() if k != "playlist")
    if args.max_new:
        target = done + args.max_new
    seen: set[int] = set()
    t0 = time.time()
    pos = 0
    rounds = max(1, -(-target // max(1, args.batch))) + 3      # +3: รอบของเพลย์ลิสต์ผู้ใช้ และรอบลองเพลงที่เฟลใหม่

    gate = {"until": 0.0, "streak": 0}      # YouTube บล็อก ("ยืนยันว่าไม่ใช่บอท") -> ทุกเธรดหยุดพักร่วมกัน แล้วค่อยลองใหม่
    gate_lock = threading.Lock()

    def is_blocked(msg) -> bool:
        return isinstance(msg, str) and ("ล็อกอิน" in msg or "Sign in" in msg or "not a bot" in msg)

    def wait_gate() -> None:
        while True:
            d = gate["until"] - time.time()
            if d <= 0:
                return
            time.sleep(min(d, 30.0))

    def prepare(item):
        """เธรดเตรียมของ: เนื้อเพลง NetEase + โหลดเสียง (ขนานกับที่การ์ดจอทำเพลงก่อนหน้า)"""
        cat, song, yt_id, query, rm = item
        lyr, level = netease_lyrics(song)
        if lyr is None:
            return item, None, None, None
        if args.word_only and level != "word":
            return item, False, None, None      # ข้ามเพลงที่เฉลยเป็นระดับบรรทัด (ไม่บันทึกว่าเฟล/ไม่มีเนื้อ)
        fetched = None
        for _try in range(4):
            wait_gate()
            fetched = fetch_song(ctx, song, yt_id, query, rm)
            if is_blocked(fetched):
                with gate_lock:
                    gate["streak"] += 1
                    wait_s = min(30 * 60, 120 * 2 ** min(gate["streak"] - 1, 4))      # 2, 4, 8, 16, 30 นาที
                    gate["until"] = max(gate["until"], time.time() + wait_s)
                    print(f"  ! YouTube ขอล็อกอิน/ตรวจบอท -> พัก {wait_s // 60} นาที ({time.strftime('%H:%M:%S')})", flush=True)
                continue
            if not isinstance(fetched, str) or fetched.startswith("โหลดเสียงไม่ได้"):
                gate["streak"] = 0
                time.sleep(args.sleep * random.uniform(0.6, 1.4))      # หน่วงเฉพาะเมื่อแตะ YouTube (โหลดจริง)
            break
        return item, lyr, level, fetched

    def finish(item, lyr, level, fetched, attempts_before: int = 0) -> bool:
        nonlocal done
        cat, song, yt_id, query, rm = item
        key = str(song["id"])
        if lyr is False:      # --word-only: ข้ามเพลงเฉลยระดับบรรทัด
            return False
        if lyr is None:       # ไม่มีเนื้อเพลง/สั้นเกินไป: ไม่ต้องลองซ้ำ
            skipped_ids.add(key)
            _save_json(skipped_path, {k: 1 for k in skipped_ids})
            failed.pop(key, None)
            return False
        status = process_song(ctx, song, lyr, level or "line", fetched, cat, rm)
        del fetched
        ok = status.startswith(("ผ่าน", "บันทึก", "มีแล้ว"))
        print(f"  ({cat}) {song.get('name')} — {status}  ({(time.time() - t0) / 60:.1f} นาที)", flush=True)
        if ok:
            failed.pop(key, None)
            if status != "มีแล้ว":
                got[cat] = got.get(cat, 0) + 1
                if cat != "playlist":
                    done += 1      # เพลงในเพลย์ลิสต์ของผู้ใช้ไม่นับเข้าเป้าหมายแผนหมวด
        else:
            rec = failed.get(key) or {"song": {"id": song["id"], "name": song.get("name"), "artists": artists_of(song), "dt": song.get("dt") or song.get("duration")},
                                      "query": query, "category": cat, "yt_id": yt_id, "allow_remix": rm, "attempts": 0}
            if not is_blocked(status):
                rec["attempts"] += 1      # โดนบล็อกชั่วคราวไม่นับเป็นการลองซ้ำของเพลงนี้
            rec["reason"] = status
            failed[key] = rec
        _save_json(failed_path, failed)
        return ok

    def round_items():
        """เพลงที่จะทำในรอบนี้ตามลำดับ: เฟลรอบก่อนใหม่ก่อน แล้วเพลงใหม่ (เช็กโควตาตอนหยิบ)"""
        nonlocal pos
        for key, rec in list(failed.items()):
            if rec["attempts"] < args.max_attempts:
                yield rec["category"], rec["song"], rec["yt_id"], rec["query"], bool(rec["allow_remix"])
        while pos < len(todo):
            cat, song, yt_id, query, rm = todo[pos]
            pos += 1
            key = str(song["id"])
            if song["id"] in seen or exists(song) or key in skipped_ids or key in failed:
                continue
            if quota and got.get(cat, 0) >= quota.get(cat, 10**9):
                continue
            seen.add(song["id"])
            yield cat, song, yt_id, query, rm

    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    pool = ThreadPoolExecutor(max_workers=max(1, args.workers))
    gpu2 = ThreadPoolExecutor(max_workers=1)      # ช่วงที่ 2 (CTC + บันทึก) ทำขนานกับ Demucs ของเพลงถัดไป
    for rnd in range(1, rounds + 1):
        if done >= target and not any(r["attempts"] < args.max_attempts for r in failed.values()):
            break
        ok_round = 0
        print(f"\n=== รอบ {rnd}/{rounds} (เป้า {args.batch} เพลงต่อรอบ · เสร็จแล้ว {done}/{target} · ค้างรอลองใหม่ {len(failed)}) ===", flush=True)
        it = round_items()
        inflight: deque = deque()
        pending2: deque = deque()
        exhausted = False
        while True:
            # เติมคิวเตรียมของล่วงหน้า (โหลดเสียงเพลงถัดไประหว่างที่การ์ดจอทำเพลงปัจจุบัน)
            while not exhausted and len(inflight) < args.workers + 1 and ok_round + len(inflight) + len(pending2) < args.batch and done + len(inflight) + len(pending2) < target:
                item = next(it, None)
                if item is None:
                    exhausted = True
                    break
                inflight.append(pool.submit(prepare, item))
            if not inflight:
                break
            item, lyr, level, fetched = inflight.popleft().result()
            sep = separate_song(ctx, fetched) if lyr is not None and lyr is not False else None
            del fetched
            pending2.append(gpu2.submit(finish, item, lyr, level, sep))
            del sep
            while len(pending2) > 1:
                ok_round += bool(pending2.popleft().result())
        while pending2:
            ok_round += bool(pending2.popleft().result())
        print(f"=== จบรอบ {rnd}: ได้ {ok_round} เพลง · ทั้งหมด {done}/{target} · ค้างรอลองใหม่ {len(failed)} (dataset/harvest_failed.json) ===", flush=True)
        if pos >= len(todo) and ok_round == 0:
            break
    pool.shutdown()
    gpu2.shutdown()
    print(f"เสร็จ: ได้ {done} เพลง · ตามหมวด: {got} · เฟลค้าง {len(failed)} เพลง (รันซ้ำเพื่อลองใหม่)")
    return 0


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    sys.exit(main())
