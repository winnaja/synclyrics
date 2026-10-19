@echo off
chcp 65001 >nul
rem สร้าง .venv ด้วย Python 3.12 และติดตั้ง dependency หลัก + เครื่องมือ test
rem AI (torch/CUDA) ติดตั้งแยกในเฟส 4: .venv\Scripts\python -m pip install -r requirements-ai.txt
cd /d "%~dp0.."
py -3.12 --version || (
    echo [ผิดพลาด] ไม่พบ Python 3.12 — ติดตั้งจาก https://www.python.org/downloads/ ก่อน
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
exit /b %ERRORLEVEL%
