"""ปกเพลงและสีจากปก (ข้อ 3.1, 3.2, 8)

นโยบาย (ผู้ใช้กำหนด): เพลงต้นฉบับใช้ปกทางการ ถ้าเป็นรีมิกซ์/เวอร์ชันอื่น (meta.version_tags ไม่ว่าง) หรือหาปกทางการไม่เจอ ใช้ปกของคลิป
ลำดับ: iTunes Search API (https://itunes.apple.com/search ไม่ต้องใช้ key)
แทน "100x100bb" ใน artworkUrl100 ด้วย "1000x1000bb" -> ไม่เจอใช้ thumbnail ของ YouTube (maxresdefault)
สีจากปก: k-means 4-5 สีใน OKLab บนรูปย่อ 64x64 (เร็ว ทำใน thread IO)
เก็บรูปใน cache/art/<videoId>.jpg และสีใน tracks.palette
การ interpolate สีระหว่างเพลงทำใน OKLCH (ข้อ 8) — ฟังก์ชันแปลงสีอยู่ที่นี่ให้ UI ใช้
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.log import get_logger
from app.core.models import TrackMeta, TrackRef


@dataclass(slots=True)
class Artwork:
    path: Path
    source: str                         # "itunes" | "youtube"
    palette: list[tuple[float, float, float]]  # OKLCH (L 0-1, C, H องศา)


ITUNES_URL = "https://itunes.apple.com/search"
MIN_ITUNES_SIMILARITY = 0.8  # ต้องคล้ายทั้งชื่อเพลงและศิลปินระดับนี้ถึงใช้ปกจาก iTunes
MIN_IMAGE_BYTES = 2000  # เล็กกว่านี้ไม่ใช่รูปจริง (เช่น placeholder)


def _similar(a: str, b: str) -> float:
    import re

    from rapidfuzz import fuzz

    na, nb = (re.sub(r"[\W_]+", " ", x.casefold()).strip() for x in (a, b))
    return fuzz.token_set_ratio(na, nb) / 100.0 if na and nb else 0.0


async def _download(client: Any, url: str, dest: Path) -> bool:
    try:
        r = await client.get(url, timeout=8.0)
        if r.status_code != 200 or len(r.content) < MIN_IMAGE_BYTES:
            return False
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(r.content)
        tmp.replace(dest)
        return True
    except Exception as e:  # เครือข่ายพัง = ลองแหล่งถัดไป
        get_logger("media").debug("ดาวน์โหลดปกไม่สำเร็จ", extra={"data": {"err": str(e)}})
        return False


def _name_variants(text: str) -> list[str]:
    """ข้อความเดิม + ที่ตัดเนื้อในวงเล็บ + เนื้อในวงเล็บแยกต่างหาก (เช่น "ป๊อบ ปองกูล (POP PONGKOOL)")"""
    import re

    out = [text]
    stripped = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", text).strip()
    if stripped and stripped != text:
        out.append(stripped)
    out += re.findall(r"[\(\[]([^\)\]]+)[\)\]]", text)
    return out


def _best_sim(a: str, b: str) -> float:
    return max(_similar(x, y) for x in _name_variants(a) for y in _name_variants(b))


async def _itunes_url(client: Any, meta: TrackMeta) -> str | None:
    """หาปกทางการจาก iTunes: ชื่อเพลงและศิลปินต้องคล้าย และเป็นเวอร์ชันเดียวกัน (ไม่ใช่ live/remix ฯลฯ)

    ไม่ใช้ความยาวตัดสิน: MV ยาวกว่าเพลงจริงได้มาก (ฉากเปิดเรื่อง) — ใช้เป็นตัวตัดสินเมื่อคะแนนเท่ากันเท่านั้น
    ค้นทั้งร้านค้าไทยและสากล (ชื่อไทยมักมีเฉพาะร้านไทย)
    """
    from app.lyrics.title_parser import clean_title

    if not meta.title:
        return None
    term = f"{meta.artist} {meta.title}".strip()
    best: tuple[float, float, str] | None = None
    for country in ("TH", "US"):
        try:
            r = await client.get(ITUNES_URL, params={"term": term, "entity": "song", "limit": 8,
                                                     "country": country}, timeout=6.0)
            if r.status_code != 200:
                continue
            results = r.json().get("results") or []
        except Exception:
            continue
        for it in results:
            url = it.get("artworkUrl100")
            if not url:
                continue
            name, tags = clean_title(it.get("trackName", ""))
            if tags != meta.version_tags:
                continue  # คนละเวอร์ชัน (live/remix ...) ปกอาจไม่ใช่ของเพลงนี้
            t = _best_sim(name or it.get("trackName", ""), meta.title)
            a = _best_sim(it.get("artistName", ""), meta.artist) if meta.artist else 1.0
            score = min(t, a)
            if score < MIN_ITUNES_SIMILARITY:
                continue
            dur_gap = abs(it["trackTimeMillis"] / 1000 - meta.duration) if (
                meta.duration and it.get("trackTimeMillis")) else 0.0
            cand = (score, -dur_gap, url.replace("100x100bb", "1000x1000bb"))
            if best is None or cand[:2] > best[:2]:
                best = cand
        if best is not None:
            break  # ร้านแรกที่เจอก็พอ
    return best[2] if best else None


async def fetch_artwork(track: TrackRef, meta: TrackMeta, target_dir: Path, client: Any = None) -> Artwork | None:
    """หาปก: iTunes (1000x1000) -> thumbnail ของ YouTube คืน None ถ้าไม่ได้เลย

    ปกที่เคยโหลดแล้ว (cache/art/<videoId>.jpg) ใช้ซ้ำทันที palette ทำในเฟส 3 (ตอนนี้คืนลิสต์ว่าง)
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    # แยกไฟล์ตามที่มา (ปกทางการ / ปกคลิป) เพื่อให้เปลี่ยนนโยบายแล้วปกเก่าไม่ค้าง และเพลงที่เคยได้แค่ปกคลิปลองหาปกทางการใหม่ได้
    official = target_dir / f"{track.video_id}.itunes.jpg"
    thumb = target_dir / f"{track.video_id}.youtube.jpg"
    if official.exists() and official.stat().st_size >= MIN_IMAGE_BYTES and not meta.version_tags:
        return Artwork(path=official, source="cache-itunes", palette=[])
    if thumb.exists() and thumb.stat().st_size >= MIN_IMAGE_BYTES and meta.version_tags:
        return Artwork(path=thumb, source="cache-youtube", palette=[])  # เวอร์ชันอื่น = ใช้ปกคลิปเสมอ ไม่ต้องหาใหม่
    own = client is None
    if own:
        import httpx

        client = httpx.AsyncClient(follow_redirects=True)
    try:
        # เพลงต้นฉบับ -> ปกทางการ (iTunes) · รีมิกซ์/สด/คัฟเวอร์/สปีดอัป ฯลฯ ไม่มีปกต้นฉบับของเวอร์ชันนั้น -> ใช้ปกคลิป YouTube
        url = None if meta.version_tags else await _itunes_url(client, meta)
        if url and await _download(client, url, official):
            return Artwork(path=official, source="itunes", palette=[])
        if thumb.exists() and thumb.stat().st_size >= MIN_IMAGE_BYTES:
            return Artwork(path=thumb, source="cache-youtube", palette=[])
        vid = track.video_id
        for yt in (track.thumbnail_url, f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                   f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"):
            if yt and await _download(client, yt, thumb):
                return Artwork(path=thumb, source="youtube", palette=[])
        return None
    finally:
        if own:
            await client.aclose()


def srgb_to_oklch(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """แปลงสี sRGB (0-1) เป็น OKLCH — เฟส 3"""
    raise NotImplementedError("เฟส 3")


def oklch_lerp(a: tuple[float, float, float], b: tuple[float, float, float], t: float) -> tuple[float, float, float]:
    """ผสมสีใน OKLCH (hue วิ่งทางที่สั้นกว่า) — เฟส 3"""
    raise NotImplementedError("เฟส 3")
