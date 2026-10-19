@echo off
chcp 65001 >nul
rem เปิดโปรแกรม SyncLyrics (เฟส 1) ใช้ .venv ถ้ามี ส่งอาร์กิวเมนต์ต่อได้ เช่น ลิงก์ YouTube หรือ --safe-mode
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m app %*
) else (
    py -3.12 -m app %*
)
exit /b %ERRORLEVEL%
