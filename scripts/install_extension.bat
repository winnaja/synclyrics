@echo off
chcp 65001 >nul
rem ติดตั้งส่วนขยาย Chrome (คัดลอกไฟล์ + ลงทะเบียน native host + ใส่ path ใน clipboard + เปิด chrome://extensions)
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m app.bridge.installer
pause
