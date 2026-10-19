"""แยกชื่อเพลง/ศิลปินจากข้อมูล YouTube ให้แม่น (ข้อ 4.1)

ลำดับความน่าเชื่อถือ: ส่วน "Music" ใต้วิดีโอ > metadata ของ yt-dlp (track/artist) >
ชื่อช่องแบบ "<ศิลปิน> - Topic" > แยกจากชื่อวิดีโอ
ตัดคำขยะ: (Official MV), [Lyrics], Official Audio/Video, 4K, HD, ft./feat., Prod. by, VEVO, - Topic ...
เก็บ version tag: live / remix / cover / acoustic / sped up / slowed / instrumental / karaoke
คำค้นหลายแบบ: "ศิลปิน เพลง", "เพลง", ชื่อไทย/อังกฤษแยกกัน (ชื่อแบบ "ชื่อไทย (English Title)"), สลับลำดับ

ทดสอบด้วย tests/fixtures/titles.json (เพิ่มกรณีที่เคยแยกผิดทุกครั้ง)
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from app.core.models import TrackMeta, TrackRef
from app.lyrics.thai import has_thai

# คำที่ถ้าอยู่ในวงเล็บแล้วทั้งก้อนเป็นขยะ (ตัดทิ้ง)
_JUNK_WORDS = (
    r"official|mv|m/v|music video|lyric(?:s)?(?: video)?|audio|video|visuali[sz]er|4k|8k|hd|hq|1080p|720p|"
    r"color coded|lyrics? ?video|full ?(?:song|version)|with lyrics|eng ?sub|thai ?sub|sub ?th|romanized|"
    r"เนื้อเพลง|เนื้อร้อง|ซับไทย|ซับ|เพลงประกอบ|ost|theme song|prod\.? ?by.*|produced by.*|"
    r"out now|new|premiere|teaser|trailer|reupload|re-upload|topic"
)
_JUNK_BRACKET_RE = re.compile(
    rf"^\s*(?:(?:{_JUNK_WORDS})[\s,/&+\-:|]*)+\s*$", re.I
)
_BRACKET_RE = re.compile(r"[\(\[【「『〈《](.*?)[\)\]】」』〉》]")
_FEAT_RE = re.compile(r"\s*[\(\[]?\s*\b(?:ft|feat|featuring)\b(?:\.\s*|\s+)[^\)\]\-–—|]*[\)\]]?", re.I)
_PROD_RE = re.compile(r"\s*[\(\[]?\s*prod\.?(?: by)?\s+[^\)\]\-–—|]*[\)\]]?", re.I)
_TRAILING_JUNK_RE = re.compile(
    r"[\s\-–—|:]*\b(?:official\s+(?:music\s+)?(?:video|audio|mv|lyric\s+video|visuali[sz]er)|"
    r"lyric\s+video|lyrics?|official|m/?v|audio|visuali[sz]er|4k|hd)\b\s*$",
    re.I,
)
_SEP_RE = re.compile(r"\s+[-–—|｜:]\s+|\s*[｜|]\s*")

# version tag -> pattern ที่เจอ "ในวงเล็บ" หรือ "นอกวงเล็บตามหลังตัวคั่น"
_VERSION_PATTERNS: dict[str, re.Pattern[str]] = {
    "live": re.compile(r"\blive\b|คอนเสิร์ต", re.I),
    "remix": re.compile(r"\bre-?mix\b|\bmix\b(?=\s*$)", re.I),
    "cover": re.compile(r"\bcover\b", re.I),
    "acoustic": re.compile(r"\bacoustic\b|\bunplugged\b", re.I),
    "sped up": re.compile(r"\bsped\s*up\b|\bnightcore\b|\bspeed\s*up\b", re.I),
    "slowed": re.compile(r"\bslowed\b|\breverb\b", re.I),
    "instrumental": re.compile(r"\binstrumental\b", re.I),
    "karaoke": re.compile(r"\bkaraoke\b|คาราโอเกะ", re.I),
}
# นอกวงเล็บ ตรวจเฉพาะรูปแบบที่ชัดเจน กันชนกับชื่อเพลงจริง เช่น "Live and Let Die"
_VERSION_UNBRACKETED: dict[str, re.Pattern[str]] = {
    "live": re.compile(r"[-–—]\s*live\s*$|\blive\s+(?:at|in|from|version|performance|session)\b", re.I),
    "remix": re.compile(r"\bremix\b", re.I),
    "sped up": re.compile(r"\bsped\s*up\b|\bnightcore\b", re.I),
    "slowed": re.compile(r"\bslowed\b", re.I),
    "instrumental": re.compile(r"[-–—]\s*instrumental\s*$", re.I),
    "karaoke": re.compile(r"\bkaraoke\b", re.I),
    "acoustic": re.compile(r"[-–—]\s*acoustic(?:\s+version)?\s*$", re.I),
}

_CHANNEL_JUNK_RE = re.compile(
    r"\s*[-–—]?\s*\b(?:topic|vevo|official(?:\s+channel)?|music|records?|entertainment)\b\s*$", re.I
)


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", " ", s.casefold()).strip()


def clean_title(title: str) -> tuple[str, frozenset[str]]:
    """ตัดคำขยะออกจากชื่อ คืน (ชื่อที่สะอาด, version tags)"""
    tags: set[str] = set()

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        found = [t for t, p in _VERSION_PATTERNS.items() if p.search(inner)]
        if found:
            tags.update(found)
            return " "
        if _JUNK_BRACKET_RE.match(inner):
            return " "
        return m.group(0)  # เช่น "(English Title)" เก็บไว้

    s = _BRACKET_RE.sub(repl, title)
    for tag, pat in _VERSION_UNBRACKETED.items():
        if pat.search(s):
            tags.add(tag)
    s = _FEAT_RE.sub("", s)
    s = _PROD_RE.sub("", s)
    for _ in range(3):  # ตัดคำขยะท้ายชื่อซ้อนกันได้หลายชั้น
        new = _TRAILING_JUNK_RE.sub("", s)
        if new == s:
            break
        s = new
    s = re.sub(r"\s+", " ", s).strip(" -–—|:｜\t")
    return s, frozenset(tags)


def _clean_channel(channel: str) -> str:
    c = channel.strip()
    for _ in range(2):
        c = _CHANNEL_JUNK_RE.sub("", c).strip()
    return c


def _split_artist_title(cleaned: str, channel: str) -> tuple[str | None, str]:
    """แยก "ศิลปิน - เพลง" ถ้าเป็นไปได้ คืน (ศิลปิน หรือ None, ชื่อเพลง)"""
    parts = [p.strip() for p in _SEP_RE.split(cleaned) if p.strip()]
    if len(parts) < 2:
        return None, cleaned
    left, right = parts[0], " - ".join(parts[1:])
    ch = _norm(_clean_channel(channel))
    if ch:
        # ถ้าชื่อช่องตรงกับฝั่งขวา แปลว่ารูปแบบ "เพลง - ศิลปิน"
        sr = fuzz.token_set_ratio(_norm(right), ch)
        sl = fuzz.token_set_ratio(_norm(left), ch)
        if sr >= 85 and sr > sl:
            return right, left
    return left, right


def _bilingual(title: str) -> list[str]:
    """"ชื่อไทย (English Title)" -> ["ชื่อไทย", "English Title"]; ไม่ใช่รูปนี้คืน []"""
    m = re.fullmatch(r"(.+?)\s*[\(\[]([^\)\]]+)[\)\]]\s*", title)
    if m and has_thai(m.group(1)) != has_thai(m.group(2)):
        return [m.group(1).strip(), m.group(2).strip()]
    return []


def _first_artist(artist: str) -> str:
    return re.split(r"\s*(?:,|&|×|x|and|/|;)\s*", artist, maxsplit=1, flags=re.I)[0].strip()


_ANY_BRACKET_RE = re.compile(r"[\(\[【「『〈《][^\)\]】」』〉》]*[\)\]】」』〉》]")
_QUOTED_RE = re.compile(r"^(.+?)\s+['\"‘“「『](.+?)['\"’”」』]\s*$")


def _no_brackets(s: str) -> str:
    return re.sub(r"\s+", " ", _ANY_BRACKET_RE.sub(" ", s)).strip(" -–—|:｜")


def _alt_titles(cleaned: str) -> tuple[str, ...]:
    """ทุกชิ้นที่อาจเป็นชื่อเพลง/ศิลปิน: ทั้งชื่อ, แต่ละส่วนที่คั่นด้วย - |, ส่วนนั้นที่ไม่มีวงเล็บ, เนื้อในวงเล็บ"""
    out: list[str] = []

    def add(x: str) -> None:
        x = re.sub(r"\s+", " ", x).strip(" -–—|:｜'\"")
        if len(x) >= 2 and x.casefold() not in {o.casefold() for o in out}:
            out.append(x)

    add(cleaned)
    for part in _SEP_RE.split(cleaned):
        add(part)
        add(_no_brackets(part))
        for inner in _ANY_BRACKET_RE.findall(part):
            add(inner[1:-1])
    return tuple(out)


def parse_track(track: TrackRef) -> TrackMeta:
    """คืน TrackMeta พร้อมคำค้นเรียงตามความน่าจะถูก"""
    ms = track.music_section or {}
    yt = track.ytdlp_meta or {}
    album: str | None = ms.get("album") or yt.get("album") or None

    cleaned_full, tags = clean_title(track.title)
    title: str
    artist: str
    if ms.get("song") and ms.get("artist"):
        title, t2 = clean_title(ms["song"])
        artist, tags = ms["artist"].strip(), tags | t2
    elif yt.get("track") and (yt.get("artist") or yt.get("creator")):
        title, t2 = clean_title(str(yt["track"]))
        artist = str(yt.get("artist") or yt.get("creator")).strip()
        tags = tags | t2
    else:
        cleaned = cleaned_full
        ch = _clean_channel(track.channel)
        topic = bool(re.search(r"-\s*topic\s*$", track.channel, re.I))
        quoted = _QUOTED_RE.match(cleaned) if not _SEP_RE.search(cleaned) else None
        if quoted:  # รูปแบบ  ศิลปิน 'ชื่อเพลง'  (พบบ่อยใน MV เกาหลี)
            art, title = quoted.group(1).strip(), quoted.group(2).strip()
        else:
            art, title = _split_artist_title(cleaned, track.channel)
        if topic:
            # ช่อง "ศิลปิน - Topic" = ชื่อวิดีโอคือชื่อเพลงล้วนๆ (ถ้ายังมี "ศิลปิน - " นำหน้าให้ตัดออก)
            artist = ch
            title = cleaned if art is None or fuzz.token_set_ratio(_norm(art), _norm(ch)) < 85 else title
        else:
            artist = art if art else ch
    title = title.strip()
    artist = artist.strip()

    queries: list[str] = []

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q.casefold() not in {x.casefold() for x in queries}:
            queries.append(q)

    t_nb, a_nb = _no_brackets(title) or title, _no_brackets(artist) or artist
    names = _bilingual(title)
    if (t_nb, a_nb) != (title, artist):
        add(f"{a_nb} {t_nb}")  # ตัดเนื้อในวงเล็บ เช่น "NewJeans (뉴진스)" -> "NewJeans" ค้นแม่นกว่า
    add(f"{artist} {title}")
    add(t_nb)
    add(title)
    first = _first_artist(a_nb)
    if first and first != a_nb:
        add(f"{first} {t_nb}")
    for n in names:
        add(f"{a_nb} {n}")
        add(n)
    add(f"{t_nb} {a_nb}")
    alts = _alt_titles(cleaned_full)
    # ชื่อวิดีโอที่แยกไม่ออกจริงๆ (เช่น รีมิกซ์ที่ตั้งชื่อยาว): ใช้ส่วนที่ไม่มีวงเล็บของแต่ละท่อนเป็นคำค้นเพิ่ม
    for alt in alts[1:4]:
        add(alt)
    return TrackMeta(
        title=title, artist=artist, album=album, duration=track.duration,
        version_tags=frozenset(tags), queries=tuple(queries), alt_titles=alts,
    )


def swap_meta(meta: TrackMeta) -> TrackMeta:
    """สลับชื่อเพลง/ศิลปิน (ชื่อวิดีโอเป็น "เพลง - ศิลปิน" แต่เราแยกเป็น "ศิลปิน - เพลง") ตัด feat. ออกจากชื่อศิลปินใหม่"""
    new_title = meta.artist.strip()
    new_artist = re.sub(r"\s+", " ", _FEAT_RE.sub("", meta.title)).strip() or meta.title
    a_nb = _no_brackets(new_artist) or new_artist
    queries = tuple(dict.fromkeys(q for q in (f"{a_nb} {new_title}", new_title, f"{new_artist} {new_title}") if q.strip()))
    return TrackMeta(title=new_title, artist=new_artist, album=meta.album, duration=meta.duration,
                     version_tags=meta.version_tags, queries=queries, alt_titles=meta.alt_titles)
