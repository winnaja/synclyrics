"""ปุ่ม "คัดลอกรายงานปัญหา" (ข้อ 11.3) — ข้อความเดียวพร้อมส่งให้ AI

โครงของรายงาน:
  บรรทัดแรก: "อ่าน ARCHITECTURE.md ก่อนแก้"
  เวอร์ชันโปรแกรม / Windows / Python / GPU + ไดรเวอร์ / CUDA / PyTorch
  ผล health check
  error ล่าสุด + stack trace
  log 200 บรรทัดสุดท้ายของ module ที่มีปัญหา (จาก app.core.log.recent_entries)
  config ที่เกี่ยวข้อง (เฉพาะค่าที่ผู้ใช้เปลี่ยนจากค่าเริ่มต้น)
ห้ามมี: cookies, token, ชื่อผู้ใช้ Windows ใน path (แทนด้วย %USERPROFILE%), ประวัติเพลงเกินจำเป็น
ผ่าน log.redact() ทุกบรรทัดก่อนคืนค่า
"""

from __future__ import annotations


def build_report(problem_module: str | None = None) -> str:
    """เฟส 8 (เฟส 1 มีแบบง่ายใน log ไว้ก่อน)"""
    raise NotImplementedError("เฟส 8")
