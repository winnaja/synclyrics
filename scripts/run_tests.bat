@echo off
chcp 65001 >nul
rem รัน test ทั้งหมดด้วยคำสั่งเดียว (ข้อ 11.3) — ต้องรันก่อน build ทุกครั้ง
rem ใช้ .venv ของโปรเจกต์ถ้ามี ไม่งั้นใช้ py -3.12
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pytest %*
) else (
    py -3.12 -m pytest %*
)
exit /b %ERRORLEVEL%
