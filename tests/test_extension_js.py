"""รัน test ของส่วนขยาย (JavaScript) ด้วย Node — ข้ามถ้าไม่มี Node (Node จำเป็นกับ yt-dlp อยู่แล้ว)"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="ไม่มี Node.js")
def test_background_js_logic() -> None:
    r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "background.test.js")], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(NODE is None, reason="ไม่มี Node.js")
def test_page_js_volume_goes_through_the_youtube_player() -> None:
    r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "page.test.js")], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(NODE is None, reason="ไม่มี Node.js")
@pytest.mark.parametrize("name", ["background.js", "content.js", "page.js"])
def test_extension_scripts_have_valid_syntax(name: str) -> None:
    r = subprocess.run([NODE, "--check", str(ROOT / "extension" / name)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


def test_manifest_is_mv3_with_stable_key_and_minimal_permissions() -> None:
    m = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert m["manifest_version"] == 3 and m["key"]
    assert set(m["permissions"]) <= {"nativeMessaging", "contextMenus", "storage", "alarms"}
    assert all("youtube.com" in h for h in m["host_permissions"])  # ไม่ขอสิทธิ์เว็บอื่น
    for f in [m["background"]["service_worker"], *[j for cs in m["content_scripts"] for j in cs["js"]]]:
        assert (ROOT / "extension" / f).exists(), f
    for size, rel in m["icons"].items():
        assert (ROOT / "extension" / rel).exists(), rel


def test_extension_only_reports_video_id_and_time() -> None:
    """ส่วนขยายต้องไม่ส่งชื่อเพลงจากหน้าเว็บ (เคยทำให้เนื้อเพลง/ปกเป็นของเพลงก่อนหน้า) และไม่แตะวิดีโอ/หน้าเว็บ"""
    import re

    raw = (ROOT / "extension" / "content.js").read_text(encoding="utf-8")
    src = re.sub(r"//[^\n]*", "", raw)  # ตรวจเฉพาะโค้ด ไม่รวมคอมเมนต์ที่อธิบายว่า "ไม่ทำ"
    assert "document.title" not in src and "watch_title" not in src and "innerText" not in src
    assert "MutationObserver" not in src and "createElement" not in src  # ไม่แก้หน้า YouTube
    assert ".pause()" in src  # มีแค่ในคำสั่งจากแอป (applyControl) — ไม่หยุดเองเมื่อวิดีโอเล่น
    assert src.count(".pause()") == 1 and "case \"pause\"" in src
    assert "play_now" not in src and "enqueue" not in src
