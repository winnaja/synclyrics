"""ค่ากลางของ test: ทุก test ใช้โฟลเดอร์ข้อมูลชั่วคราว (ไม่แตะ %LOCALAPPDATA% จริง)"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.paths import AppPaths

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def app_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppPaths:
    monkeypatch.setenv("SYNCLYRICS_HOME", str(tmp_path / "home"))
    from app.core.paths import get_paths

    p = get_paths()
    p.ensure()
    return p
