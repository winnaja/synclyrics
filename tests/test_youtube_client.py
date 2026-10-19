"""YouTubeClient: ลำดับ cookies, retry เมื่อ 403 (ไม่ใช้เครือข่ายจริง)"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import MediaError
from app.media.youtube import FALLBACK_VARIANTS, YouTubeClient


def test_parse_errors_to_thai_messages() -> None:
    assert "403" in YouTubeClient._wrap(Exception("ERROR: unable to download video data: HTTP Error 403: Forbidden")).user_message
    assert "เปิดไม่ได้" in YouTubeClient._wrap(Exception("Video unavailable")).user_message
    assert "ล็อกอิน" in YouTubeClient._wrap(Exception("Sign in to confirm you're not a bot")).user_message


def test_403_retries_with_other_variants_then_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = YouTubeClient(tmp_path / "no.txt")
    seen: list[dict] = []
    f = tmp_path / "vid00000001.webm"

    def fake_run(work, **extra):
        seen.append(extra)
        if len(seen) < 3:
            raise MediaError("media", "YouTube ปฏิเสธการโหลด (403)")
        from app.core.models import TrackRef
        from app.media.youtube import VideoInfo

        f.write_bytes(b"x" * 10)

        vi = VideoInfo(track=TrackRef(video_id="vid00000001"), duration=1.0)
        return (vi, {"requested_downloads": [{"filepath": str(f)}], "format_id": "251", "acodec": "opus", "abr": 130}), "none"

    monkeypatch.setattr(c, "_run", fake_run)
    vi, dl = c.fetch_and_download("vid00000001", tmp_path)
    assert len(seen) == 3 and dl.path == f
    assert "extractor_args" in seen[2] and "extractor_args" not in seen[0]
    assert len(FALLBACK_VARIANTS) == 3


def test_non_403_error_is_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = YouTubeClient(tmp_path / "no.txt")
    calls: list[int] = []

    def fake_run(work, **extra):
        calls.append(1)
        raise MediaError("media", "วิดีโอนี้เปิดไม่ได้")

    monkeypatch.setattr(c, "_run", fake_run)
    with pytest.raises(MediaError):
        c.fetch_and_download("vid00000001", tmp_path)
    assert len(calls) == 1


def test_mode_order_prefers_last_working_and_skips_missing_file(tmp_path: Path) -> None:
    c = YouTubeClient(tmp_path / "no.txt")
    assert c._mode_order() == ["chrome", "none"]  # ไม่มี cookies.txt -> ไม่ลอง file
    c.cookie_mode = "none"
    assert c._mode_order()[0] == "none"
    (tmp_path / "no.txt").write_text("# cookies")
    c.cookie_mode = "file"
    assert c._mode_order()[0] == "file"
