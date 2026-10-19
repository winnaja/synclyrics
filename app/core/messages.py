"""รูปแบบข้อความระหว่าง process ทั้งหมด (สัญญากลาง — แก้ที่นี่ที่เดียว)

มี 2 ช่องทาง ใช้ซองจดหมาย (envelope) แบบเดียวกัน:

  {"v": 1, "type": "<ชนิด>", "id": "<uuid หรือ ''>", "payload": {...}}

1. Bridge: ส่วนขยาย Chrome <-> native host <-> โปรแกรมหลัก (ARCHITECTURE.md §6)
   - Chrome <-> host: stdio, ความยาว uint32 little-endian + JSON UTF-8 (มาตรฐาน Native Messaging)
   - host <-> โปรแกรม: named pipe (QLocalServer "synclyrics-<username>") framing แบบเดียวกัน
2. AI: โปรแกรมหลัก <-> AI worker process ผ่าน multiprocessing.Queue (ARCHITECTURE.md §5)
   ส่ง dict แบบเดียวกัน (ไม่ส่ง object ของ Python ตรงๆ เพื่อให้ worker restart ได้ทุกเมื่อ)
   ข้อมูลเสียงไม่ส่งผ่าน queue — ส่งเป็น path ของไฟล์ PCM ใน cache แทน

เพิ่มชนิดข้อความใหม่: เพิ่มชื่อใน set ที่เกี่ยวข้อง + เขียนลง ARCHITECTURE.md
ถ้าเปลี่ยนรูปแบบแบบไม่เข้ากับของเก่า ให้เพิ่ม PROTOCOL_VERSION
"""

from __future__ import annotations

import json
import struct
import uuid
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 1
# Chrome จำกัดข้อความจาก host ไปส่วนขยายที่ 1 MB และจากส่วนขยายไป host ที่ 64 MB
MAX_MESSAGE_BYTES = 1024 * 1024


# ---------------------------------------------------------------------------
# ชนิดข้อความของ bridge
# ---------------------------------------------------------------------------
EXT_TO_APP: frozenset[str] = frozenset({
    "hello",            # {ext_version, browser}  ส่งทันทีที่เชื่อมต่อ (wizard รอข้อความนี้)
    "play_now",         # {track: TrackRef, start_at?: float}  "เล่นเลย" / "เปิดในแอป"
    "enqueue",          # {tracks: [TrackRef], position: "end" | "next"}
    "enqueue_playlist", # {playlist_id, title, tracks: [TrackRef]}
    "up_next",          # {tracks: [TrackRef]}  รายการ Up next ของหน้าที่เปิดอยู่
    "companion_state",  # {video_id, current_time, rate, paused, sent_at_ms, seeked}
    "companion_track",  # {track: TrackRef}  เพลงเปลี่ยนในโหมดคู่หู
    "command",          # {name: "play_pause"|"next"|"automix_toggle"|"open_settings"|"focus"}
    "log",              # {level, msg, data}  log จากส่วนขยาย (เช่น selector หาไม่เจอ)
    "ping",             # {}
})
APP_TO_EXT: frozenset[str] = frozenset({
    "hello_ack",        # {app_version, protocol: int, mode: "app"|"companion"}
    "status",           # {playing, video_id, title, automix}
    "toast",            # {text}  ให้ส่วนขยายแสดง toast
    "selectors",        # {data}  ส่ง config/selectors.json ล่าสุดให้ส่วนขยาย
    "reload_extension", # {}  ส่วนขยายเรียก chrome.runtime.reload()
    "pause_tab",        # {video_id}  หยุดวิดีโอในแท็บ (หลัง "เปิดในแอป")
    "pong",             # {}
    "error",            # {code, message}
})

# ---------------------------------------------------------------------------
# ชนิดข้อความของ AI worker
# ---------------------------------------------------------------------------
AI_REQUESTS: frozenset[str] = frozenset({
    "warmup",           # {}  โหลดโมเดลค้างใน VRAM + warm-up ด้วยเสียงเงียบ
    "separate_chunk",   # {job_id, video_id, pcm_path, sample_rate, start, end}  -> stems ลง cache
    "align_chunk",      # {job_id, video_id, pcm_path, stems_dir, start, end, lines, language}
    "transcribe",       # {job_id, video_id, pcm_path, start, end, language?}
    "analyze_full",     # {job_id, video_id, pcm_path, stems_dir}  beat/ท่อน/key/LUFS/vocal
    "cancel",           # {job_ids?: [str], video_id?: str}
    "status",           # {}
    "shutdown",         # {}
})
AI_EVENTS: frozenset[str] = frozenset({
    "ready",            # {device, vram_total_mb, models: {...}}
    "heartbeat",        # {busy_job?: str, vram_used_mb}  ทุก 1 วิ (watchdog ใช้)
    "progress",         # {job_id, fraction}
    "result",           # {job_id, kind, data}
    "failed",           # {job_id, error, traceback, recoverable: bool}
    "degraded",         # {reason, action}  เช่น VRAM ใกล้เต็ม -> ลดขนาดโมเดล
})


@dataclass(slots=True)
class Envelope:
    """ซองข้อความกลาง"""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    v: int = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"v": self.v, "type": self.type, "id": self.id, "payload": self.payload}

    @staticmethod
    def new(type_: str, payload: dict[str, Any] | None = None, with_id: bool = False) -> "Envelope":
        return Envelope(type=type_, payload=payload or {}, id=uuid.uuid4().hex if with_id else "")

    @staticmethod
    def from_dict(d: dict[str, Any], allowed: frozenset[str] | None = None) -> "Envelope":
        """ตรวจรูปแบบ ถ้าผิดโยน MessageError (ผู้รับต้องจับแล้ว log ห้ามพัง)"""
        if not isinstance(d, dict):
            raise MessageError("ข้อความต้องเป็น object")
        t = d.get("type")
        if not isinstance(t, str):
            raise MessageError("ไม่มี type")
        if allowed is not None and t not in allowed:
            raise MessageError(f"ไม่รู้จักชนิดข้อความ {t!r}")
        payload = d.get("payload", {})
        if not isinstance(payload, dict):
            raise MessageError("payload ต้องเป็น object")
        v = d.get("v", PROTOCOL_VERSION)
        if not isinstance(v, int) or v > PROTOCOL_VERSION:
            raise MessageError(f"protocol v{v} ใหม่กว่าที่โปรแกรมรองรับ (v{PROTOCOL_VERSION})")
        return Envelope(type=t, payload=payload, id=str(d.get("id", "")), v=v)


class MessageError(ValueError):
    """ข้อความผิดรูปแบบ"""


def encode_frame(msg: Envelope | dict[str, Any]) -> bytes:
    """แปลงเป็น frame: uint32 LE ความยาว + JSON UTF-8"""
    d = msg.to_dict() if isinstance(msg, Envelope) else msg
    body = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_MESSAGE_BYTES:
        raise MessageError(f"ข้อความใหญ่เกิน {MAX_MESSAGE_BYTES} ไบต์")
    return struct.pack("<I", len(body)) + body


class FrameDecoder:
    """ตัวต่อ frame จาก stream ที่มาเป็นชิ้นๆ (ใช้ได้ทั้ง stdio และ named pipe)"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        """ป้อน byte ที่ได้มา คืนข้อความที่ครบแล้ว (อาจเป็น 0 หรือหลายข้อความ)"""
        self._buf.extend(data)
        out: list[dict[str, Any]] = []
        while len(self._buf) >= 4:
            (n,) = struct.unpack_from("<I", self._buf, 0)
            if n > 64 * 1024 * 1024:
                self._buf.clear()
                raise MessageError("ความยาว frame ผิดปกติ — ล้าง buffer")
            if len(self._buf) < 4 + n:
                break
            body = bytes(self._buf[4 : 4 + n])
            del self._buf[: 4 + n]
            out.append(json.loads(body.decode("utf-8")))
        return out
