"""ปกเพลงและสีจากปก (ข้อ 3.1, 3.2, 8)

นโยบาย (ผู้ใช้กำหนด): เพลงต้นฉบับใช้ปกทางการ ถ้าเป็นรีมิกซ์/เวอร์ชันอื่น (meta.version_tags ไม่ว่าง) หรือหาปกทางการไม่เจอ ใช้ปกของคลิป
ลำดับ: iTunes Search API (https://itunes.apple.com/search ไม่ต้องใช้ key)
แทน "100x100bb" ใน artworkUrl100 ด้วย "1000x1000bb" -> ไม่เจอใช้ thumbnail ของ YouTube (maxresdefault)
สีจากปก: k-means 4-5 สีใน OKLab บนรูปย่อ 64x64 (เร็ว ทำใน thread IO)
เก็บรูปใน cache/art/<videoId>.jpg และสีใน tracks.palette
การ interpolate สีระหว่างเพลงทำใน OKLCH (ข้อ 8) — ฟังก์ชันแปลงสีอยู่ที่นี่ให้ UI ใช้
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.log import get_logger
from app.core.models import TrackMeta, TrackRef

log = get_logger("media")


@dataclass(slots=True)
class Artwork:
    path: Path
    source: str                         # "itunes" | "youtube"
    palette: list[str]  # สีเด่นของปก 4 สี เป็น "#RRGGBB" ปรับให้เหมาะกับพื้นหลังมืด (ใช้กับพื้นหลัง fluid ของโหมดเต็ม)


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


DEFAULT_PALETTE = ["#2a2f3d", "#343947", "#232733", "#2e3340"]  # เทาอมน้ำเงินกลางๆ ไม่มีม่วงหรือสีสดที่ไม่ใช่ของปก


def dominant_colors(path: Path, n: int = 4) -> list[str]:
    """สีเด่น n สีของปก (median-cut ของ Pillow บนรูปย่อ) เรียงตามพื้นที่ แล้วปรับเป็นโทนสำหรับพื้นหลังมืด:
    เพิ่มความอิ่มสีขั้นต่ำและบีบความสว่างให้อยู่ช่วงที่ตัวอักษรสีขาวอ่านชัด · ไม่ได้/รูปเสีย = DEFAULT_PALETTE
    """
    try:
        import colorsys

        from PIL import Image

        with Image.open(path) as im:
            small = im.convert("RGB").resize((72, 72))
        q = small.quantize(colors=max(n * 3, 12), method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette() or []
        counts = sorted(q.getcolors() or [], reverse=True)  # [(จำนวนพิกเซล, index)]
        picked: list[tuple[float, float, float]] = []
        for _, idx in counts:
            r, g, b = (pal[idx * 3 + k] / 255.0 for k in range(3))
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            if v < 0.08:  # ดำสนิท (ขอบ) ไม่เอา
                continue
            # ไม่ซ้ำกับสีที่เลือกไปแล้ว (ห่างกันพอ ทั้งเฉดสี ความอิ่ม และความสว่าง — ปกที่เป็นสีเดียวหลายเฉด เช่นทะเลสีน้ำเงิน ต้องได้หลายเฉดของสีนั้น)
            if any(min(abs(h - ph), 1 - abs(h - ph)) < 0.05 and abs(s - ps) < 0.15 and abs(v - pv) < 0.12 for ph, ps, pv in picked):
                continue
            picked.append((h, s, v))
            if len(picked) == n:
                break
        if not picked:
            return list(DEFAULT_PALETTE)
        k = 0
        while len(picked) < n:  # สีไม่พอ: ทำเฉดสว่าง/มืดของสีเดิม (ห้ามหมุนเฉดสี: เคยทำให้ปกสีน้ำเงินมีสีม่วงโผล่มาที่ไม่มีในปก)
            h, s, v = picked[k % len(picked)]
            picked.append((h, s, max(0.1, min(1.0, v * (0.7 if k % 2 == 0 else 1.25)))))
            k += 1
        out = []
        for h, s, v in picked[:n]:
            # โทนสดแบบ Apple Music: เพิ่มความอิ่มสี และยกความสว่างขึ้นเป็นช่วง 0.42-0.88 (พื้นหลังยังมืดพอให้ตัวอักษรขาวอ่านชัด)
            if s < 0.12:  # ปกขาว-ดำ/เทา: คงพื้นหลังเป็นโทนเทาเป็นกลาง (ห้ามเติมความอิ่มสีจนกลายเป็นสีอื่น) และมืดกว่าสีสด
                s, v = s, 0.18 + 0.30 * v
            else:
                s = max(0.30, min(0.95, s * 1.1))      # คงโทนของปก ไม่ดันให้สดเกินจริง
                v = 0.26 + 0.56 * v
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            out.append("#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255)))
        return out
    except Exception:  # noqa: BLE001 — สีพื้นหลังไม่สำคัญพอจะทำให้ปกพัง
        log.exception("หาสีเด่นของปกไม่สำเร็จ")
        return list(DEFAULT_PALETTE)


def find_content_box(gray: Any, dark: int = 24, min_bar_frac: float = 0.03, min_keep_frac: float = 0.4):
    """หากรอบเนื้อรูปที่ไม่ใช่ขอบดำ (letterbox/pillarbox ที่ YouTube ใส่ใน thumbnail)

    gray = array 2 มิติ (ความสว่าง 0-255) คืน (x0, y0, x1, y1) หรือ None ถ้าไม่มีขอบดำที่ควรตัด
    ขอบดำ = แถว/คอลัมน์ที่ทุกพิกเซลมืดมาก (max < dark) ต่อเนื่องจากขอบ และกว้างอย่างน้อย min_bar_frac ของด้าน
    (ปกที่มืดจริงๆ มีรายละเอียดอยู่ จึงไม่ถูกตัด) · เหลือเนื้อรูปน้อยกว่า min_keep_frac ของพื้นที่ = ไม่ตัด (กันตัดผิด)
    """
    import numpy as np

    g = np.asarray(gray)
    if g.ndim != 2 or g.size == 0:
        return None
    h, w = g.shape
    rows = np.where(g.max(axis=1) >= dark)[0]
    cols = np.where(g.max(axis=0) >= dark)[0]
    if rows.size == 0 or cols.size == 0:
        return None
    y0, y1, x0, x1 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    if (y0 < h * min_bar_frac) and (h - y1 < h * min_bar_frac):
        y0, y1 = 0, h
    if (x0 < w * min_bar_frac) and (w - x1 < w * min_bar_frac):
        x0, x1 = 0, w
    if (x0, y0, x1, y1) == (0, 0, w, h):
        return None
    if (x1 - x0) * (y1 - y0) < w * h * min_keep_frac:
        return None
    return x0, y0, x1, y1


def find_art_square(gray: Any, min_aspect: float = 1.4, tol: float = 0.05):
    """thumbnail ของเพลงแบบ "Topic" (auto-generated) = รูปปกจัตุรัสวางกึ่งกลางพื้นหลังเบลอเรียบ 16:9 -> หากรอบปกจริง

    หลักการ: พื้นหลังเบลอมีความต่างระหว่างคอลัมน์ติดกันน้อยมาก ส่วนปกมีรายละเอียดมาก — หาคอลัมน์แรก/สุดท้ายที่เริ่มมีรายละเอียด
    ถ้าตรงกับกรอบจัตุรัสกึ่งกลาง (กว้างเท่าความสูง ±tol) = นั่นคือปก คืน (x0, 0, x0+h, h) หรือ None (ไม่ใช่รูปแบบนี้ ไม่ตัด)
    """
    import numpy as np

    g = np.asarray(gray, dtype=float)
    if g.ndim != 2 or g.size == 0:
        return None
    h, w = g.shape
    if w / h < min_aspect:
        return None
    col = np.abs(np.diff(g, axis=1)).mean(axis=0)  # รายละเอียดแนวตั้งของแต่ละคอลัมน์
    margin = max(4, int(w * 0.03))
    bg = float(np.median(np.concatenate([col[:margin], col[-margin:]])))
    x0 = (w - h) // 2
    inner = col[x0 + 10: x0 + h - 10]
    if inner.size == 0:
        return None
    # เกณฑ์ "มีรายละเอียด": อิงตัวปกเอง (กัน banding เล็กน้อยของพื้นหลังเบลอที่ผ่าน JPEG ถูกนับว่าเป็นรายละเอียด)
    thr = max(0.8, 6.0 * bg, 0.25 * float(np.median(inner)))
    active = np.where(col > thr)[0]
    if active.size == 0:
        return None
    left, right = int(active[0]), int(active[-1]) + 1
    if abs(left - x0) > tol * h or abs(right - (x0 + h)) > tol * h:
        return None
    # ข้างนอกกรอบต้องเรียบจริง (ไม่มีรายละเอียดซ่อนอยู่) ไม่งั้นอาจเป็นภาพ 16:9 ปกติ
    outside = np.concatenate([col[: max(0, x0 - 2)], col[min(len(col), x0 + h + 2):]])
    if outside.size == 0 or float(np.percentile(outside, 90)) > thr:
        return None
    return x0, 0, x0 + h, h


def autocrop_black_bars(path: Path) -> bool:
    """ตัดขอบดำของรูปที่ path (เขียนทับ) คืน True ถ้ามีการตัด — ใช้กับ thumbnail ของ YouTube เท่านั้น

    ใช้ Pillow ถอดรหัส/บันทึก JPEG (ไม่ผูกกับ Qt — ห้าม import PySide6 นอก UI) รูปเสียก็ข้ามเงียบๆ
    """
    try:
        import numpy as np
        from PIL import Image

        with Image.open(path) as im:
            im.load()
            rgb = im.convert("RGB")
            box = find_content_box(np.asarray(rgb.convert("L")))
            if box is not None:
                rgb = rgb.crop(box)
            art = find_art_square(np.asarray(rgb.convert("L")))  # ปกจัตุรัสกลางพื้นหลังเบลอ (Topic)
            if art is not None:
                rgb = rgb.crop(art)
            elif box is None:
                return False
        rgb.save(path, "JPEG", quality=92)
        return True
    except Exception:
        log.exception("ตัดขอบดำของปกไม่สำเร็จ")
        return False


async def fetch_artwork(track: TrackRef, meta: TrackMeta, target_dir: Path, client: Any = None) -> Artwork | None:
    """หาปก: iTunes (1000x1000) -> thumbnail ของ YouTube คืน None ถ้าไม่ได้เลย

    ปกที่เคยโหลดแล้ว (cache/art/<videoId>.jpg) ใช้ซ้ำทันที palette ทำในเฟส 3 (ตอนนี้คืนลิสต์ว่าง)
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    # แยกไฟล์ตามที่มา (ปกทางการ / ปกคลิป) เพื่อให้เปลี่ยนนโยบายแล้วปกเก่าไม่ค้าง และเพลงที่เคยได้แค่ปกคลิปลองหาปกทางการใหม่ได้
    official = target_dir / f"{track.video_id}.itunes.jpg"
    thumb = target_dir / f"{track.video_id}.youtube.jpg"
    if official.exists() and official.stat().st_size >= MIN_IMAGE_BYTES and not meta.version_tags:
        return Artwork(path=official, source="cache-itunes", palette=await asyncio.to_thread(dominant_colors, official))
    if thumb.exists() and thumb.stat().st_size >= MIN_IMAGE_BYTES and meta.version_tags:
        await asyncio.to_thread(autocrop_black_bars, thumb)  # ปกที่เก็บไว้ก่อนมีการตัดขอบดำ (ตัดซ้ำปลอดภัย)
        return Artwork(path=thumb, source="cache-youtube", palette=await asyncio.to_thread(dominant_colors, thumb))  # เวอร์ชันอื่น = ใช้ปกคลิปเสมอ ไม่ต้องหาใหม่
    own = client is None
    if own:
        import httpx

        client = httpx.AsyncClient(follow_redirects=True)
    try:
        # เพลงต้นฉบับ -> ปกทางการ (iTunes) · รีมิกซ์/สด/คัฟเวอร์/สปีดอัป ฯลฯ ไม่มีปกต้นฉบับของเวอร์ชันนั้น -> ใช้ปกคลิป YouTube
        url = None if meta.version_tags else await _itunes_url(client, meta)
        if url and await _download(client, url, official):
            return Artwork(path=official, source="itunes", palette=await asyncio.to_thread(dominant_colors, official))
        if thumb.exists() and thumb.stat().st_size >= MIN_IMAGE_BYTES:
            await asyncio.to_thread(autocrop_black_bars, thumb)
            return Artwork(path=thumb, source="cache-youtube", palette=await asyncio.to_thread(dominant_colors, thumb))
        vid = track.video_id
        for yt in (track.thumbnail_url, f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                   f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"):
            if yt and await _download(client, yt, thumb):
                await asyncio.to_thread(autocrop_black_bars, thumb)  # thumbnail ของ YouTube มีขอบดำ (hqdefault = 4:3 ใส่ขอบ)
                return Artwork(path=thumb, source="youtube", palette=await asyncio.to_thread(dominant_colors, thumb))
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
