@echo off
rem native messaging host ช่วงพัฒนา — Chrome เปิดไฟล์นี้ (stdin/stdout ต้องไม่ถูกแตะ) ตัวติดตั้งจะใช้ synclyrics-host.exe แทน
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m app.bridge.host
