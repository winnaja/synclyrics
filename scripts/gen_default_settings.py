"""สร้าง config/settings.yaml จากค่าเริ่มต้นใน app/core/config.py (Settings)

รันทุกครั้งที่เพิ่ม/แก้ค่าใน Settings:  py -3.12 scripts/gen_default_settings.py
test_config_files.py จะเตือนถ้าไฟล์กับโค้ดไม่ตรงกัน
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402

HEADER = r"""# SyncLyrics — การตั้งค่าเริ่มต้น (ไฟล์นี้สร้างอัตโนมัติจาก app/core/config.py: Settings)
# ห้ามแก้ไฟล์นี้ด้วยมือ — แก้ค่าเริ่มต้นในโค้ดแล้วรัน scripts/gen_default_settings.py
# ค่าที่ผู้ใช้เปลี่ยนในหน้าตั้งค่าจะถูกเก็บที่ %LOCALAPPDATA%\SyncLyrics\settings.yaml
"""


def main() -> None:
    data = Settings().model_dump(mode="json")
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    (ROOT / "config" / "settings.yaml").write_text(HEADER + body, encoding="utf-8")
    print("เขียน config/settings.yaml แล้ว")


if __name__ == "__main__":
    main()
