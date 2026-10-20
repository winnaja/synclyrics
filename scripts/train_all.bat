@echo off
chcp 65001 >nul
rem ===== เทรนโมเดลของ SyncLyrics ตั้งแต่ต้นจนจบ (ปิดแอปก่อน!) =====
rem ใช้:  scripts\train_all.bat [จำนวนเพลงที่จะดึง]   ค่าเริ่มต้น 300   (ทำต่อจากที่ค้างได้ รันซ้ำได้)
cd /d "%~dp0.."
set N=%1
if "%N%"=="" set N=300
echo [1/4] ดึงเพลงสร้างชุดข้อมูล (%N% เพลง ใช้เวลาประมาณ %N% x 0.5 นาที) ...
.venv\Scripts\python scripts\harvest.py --limit %N%
if errorlevel 1 goto :err
echo [2/4] เทรนตัวแบ่งบรรทัด/เสียงประสาน ...
.venv\Scripts\python scripts\train_lines.py
echo [3/4] วัดตัวจัดเวลาเดิมก่อนเทรน (baseline) ...
.venv\Scripts\python scripts\eval_aligner.py --split val
echo [4/4] เทรนตัวจัดเวลา (fine-tune MMS) ...
.venv\Scripts\python scripts\train_ctc.py --epochs 3
echo.
echo เสร็จ — ดูผลด้านบน แล้วบอก Claude ให้ผูกโมเดลที่ดีกว่าเข้าแอป
pause
exit /b 0
:err
echo เกิดข้อผิดพลาด
pause
exit /b 1
