"""ตัวเปิด SyncLyrics (exe เล็กๆ): เปิดโปรแกรมจาก .venv ของโฟลเดอร์เดียวกับไฟล์นี้ โดยไม่มีหน้าต่างคอนโซลค้าง"""
import ctypes
import os
import subprocess
import sys

base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
if os.path.basename(base).lower() == "build_launcher":
    base = os.path.dirname(base)
py = os.path.join(base, ".venv", "Scripts", "pythonw.exe")
if not os.path.exists(py):
    ctypes.windll.user32.MessageBoxW(0, f"ไม่พบ {py}\nรัน scripts\setup_venv.bat ก่อน", "SyncLyrics", 0x10)
    sys.exit(1)
subprocess.Popen([py, "-m", "app", *sys.argv[1:]], cwd=base,
                 creationflags=0x00000008 | 0x00000200 | 0x08000000)  # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
