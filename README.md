# SyncLyrics

โปรแกรมเล่นเพลงจาก YouTube บน Windows พร้อมเนื้อเพลงคาราโอเกะทีละคำ, AutoMix ที่เรียนรู้จากดาว และ AI บน GPU ในเครื่อง (ใช้ส่วนตัว)

- สเปกทั้งหมด: [PROMPT.md](PROMPT.md)
- โครงสร้างระบบ (อ่านก่อนแก้โค้ด): [ARCHITECTURE.md](ARCHITECTURE.md)
- สถานะ: [docs/PROGRESS.md](docs/PROGRESS.md) · การตัดสินใจ: [docs/DECISIONS.md](docs/DECISIONS.md) · ส่งต่อแต่ละเฟส: [docs/handoff/](docs/handoff/)

## เริ่มต้น (นักพัฒนา)

ต้องมี Python 3.12 (64-bit) และ ffmpeg

```bat
scripts\setup_venv.bat
scripts\run_tests.bat
```
