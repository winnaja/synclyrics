"""สรุปเพลงที่ harvest ได้แล้ว -> dataset/harvest_done.txt (รันซ้ำได้ตลอด)"""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "dataset" / "songs"
rows = []
for mp in sorted(root.glob("*/meta.json")):
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
    except ValueError:
        continue
    rows.append((m.get("category") or "?", m.get("artist") or "", m.get("title") or "", m.get("ref_timing") or "", bool(m.get("suspect")), mp.parent.name))
rows.sort()
lines = [f"{'[ธง suspect] ' if sus else ''}{cat:10s} | {artist} - {title} | เฉลย:{lvl} | {d}" for cat, artist, title, lvl, sus, d in rows]
out = root.parent / "harvest_done.txt"
out.write_text(f"ทั้งหมด {len(rows)} เพลง · ใช้เทรนได้ {sum(1 for r in rows if not r[4])} · ติดธง suspect {sum(1 for r in rows if r[4])}\n" + "\n".join(lines), encoding="utf-8")
sys.stdout.buffer.write(f"เขียน {out} ({len(rows)} เพลง)\n".encode("utf-8"))
