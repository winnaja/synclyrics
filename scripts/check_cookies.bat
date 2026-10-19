@echo off
chcp 65001 >nul
rem ตรวจว่า yt-dlp ดึง cookies Premium จาก Chrome ได้ไหม (แสดงแค่ผล ไม่แสดงค่า cookie) ควรปิด Chrome ก่อน
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\check_cookies.py
pause
