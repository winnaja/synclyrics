# DECISIONS.md — บันทึกการตัดสินใจ (ใหม่สุดอยู่บน)

รูปแบบ: **วันที่ · ตัดสินใจอะไร** — เพราะอะไร · ทางเลือกที่ไม่ได้เลือก

---

### 2026-10-20 · ใช้ Python 3.12.10 (ติดตั้งผ่าน winget แบบ user)
- เพราะ: python.org ไม่มีตัวติดตั้ง Windows ของ 3.12 รุ่นหลัง 3.12.10 แล้ว (ช่วง security-only ออกเป็น source อย่างเดียว) · test 106/106 ผ่าน และ pin ใน requirements.txt ติดตั้งได้ครบ

### 2026-10-19 · เฟส 0 ใช้ Python 3.13 ชั่วคราวรัน test (ภายหลังรันซ้ำบน 3.12.10 ผ่านแล้ว)
- เพราะ: ในเครื่องยังไม่มี Python 3.12 · test ของเฟส 0 ใช้แค่ pytest/pyyaml/pydantic/numpy ซึ่งเหมือนกันทั้งสองเวอร์ชัน (venv ชั่วคราวอยู่นอกโปรเจกต์)
- ต้องรันซ้ำบน 3.12 ด้วย `scripts\setup_venv.bat` + `scripts\run_tests.bat` (อยู่ใน checklist ของผู้ใช้)

### 2026-10-19 · pin เวอร์ชัน library จาก PyPI ณ วันนี้ (ยังไม่ได้ติดตั้งจริงบน 3.12)
- เพราะ: PROMPT ข้อ 11.2 ให้ล็อกทุกตัวยกเว้น yt-dlp · ตรวจแล้วว่ามี wheel สำหรับ cp312/win_amd64
- 2026-10-20: requirements.txt + requirements-dev.txt ติดตั้งผ่านบน 3.12.10 แล้ว · requirements-ai.txt ยืนยันในเฟส 4

### 2026-10-19 · ล็อก torch/torchaudio ที่ 2.11.0+cu128
- เพราะ: torchaudio หยุดพัฒนาที่ 2.11 (torch ไปถึง 2.14 แล้ว) และต้องใช้เวอร์ชันเดียวกับ torch · เปิด wheel 2.11 ตรวจแล้วว่ายังมี `functional.forced_align` และ `pipelines.MMS_FA` ที่ PROMPT ข้อ 5.1 ใช้ · cu128 มี wheel cp312 Windows และรองรับ RTX 4060
- ไม่ได้เลือก: torch 2.14 + ย้าย alignment ไป `ctc-forced-aligner` (เปลี่ยนจาก PROMPT และเสี่ยงกว่า) — พิจารณาใหม่ถ้าวันหนึ่ง 2.11 ใช้ไม่ได้

### 2026-10-19 · beat_this เป็นตัววิเคราะห์จังหวะหลัก, allin1 เป็นตัวเสริม
- เพราะ: allin1 ออกรุ่นล่าสุดปี 2023 ต้องใช้ natten/madmom ซึ่งติดตั้งยากบน Windows · PROMPT ข้อ 12.3 อนุญาตทางเลือก beat_this อยู่แล้ว
- ผลกระทบ: ท่อนเพลง (intro/chorus/outro) ถ้าไม่มี allin1 ใช้ตัวแบ่งท่อนแบบง่ายจาก vocal activity + energy (`pipeline/beats.py: simple_sections`)
- ไม่ได้เลือก: บังคับ allin1 (ผู้ใช้จะติดตั้งไม่ผ่านแล้วเฟส 4 ค้าง)

### 2026-10-19 · ใช้ Python 3.12 แทน 3.11 (ผู้ใช้ยืนยันแล้ว)
- เพราะ: numpy 2.5 และ librosa 1.0 ต้องใช้ Python ≥ 3.12 · torch 2.11, PySide6 6.12, demucs, beat_this, faster-whisper มี wheel 3.12 ครบ
- ไม่ได้เลือก: 3.11 (ต้องล็อก numpy/librosa รุ่นเก่า) · 3.13 (wheel ของไลบรารี AI บางตัวเสี่ยงไม่มี)

### 2026-10-19 · เพิ่มโฟลเดอร์ `app/core`, `app/media`, `app/player` (นอกเหนือจาก PROMPT ข้อ 1.3)
- เพราะ: ของที่ทุกส่วนใช้ร่วมกัน (path, config, log, DB, นาฬิกา, ข้อความ) ต้องมีที่อยู่กลางที่ไม่ import ส่วนอื่น (กันวงจร import) · yt-dlp/ปกไม่ใช่ทั้ง audio และ lyrics · ตัวควบคุมคิว/preload สั่งหลายส่วนพร้อมกันจึงไม่ควรอยู่ใน audio
- โฟลเดอร์ทั้งหมดใน PROMPT ข้อ 1.3 ยังอยู่ครบ (เป็นการเพิ่ม ไม่ได้เปลี่ยน)

### 2026-10-19 · audio engine อยู่ใน process หลัก (ตาม PROMPT) + ป้องกัน GIL
- เพราะ: ทำตาม PROMPT ข้อ 1.1 และง่ายกว่า · งานหนักแยก process แล้ว (AI, ffmpeg) · ตั้ง `sys.setswitchinterval(0.001)` · กติกาให้งาน Python ล้วนในตัวหลักแบ่งชิ้น < 5ms
- ทางหนีที่ออกแบบไว้แล้ว: ย้าย engine ไป process แยก (MediaClock รองรับ shared memory, PCM เป็นไฟล์ memmap, คำสั่งเป็น tuple) — ใช้ถ้าเฟส 5 วัดแล้วยังมี underrun
- ไม่ได้เลือก (ตอนนี้): process แยกตั้งแต่แรก (ซับซ้อนกว่า ทำให้เฟส 1 ช้า)

### 2026-10-19 · sample rate ของ engine = sample rate ของอุปกรณ์เสียง, ffmpeg resample ตอนถอดรหัส
- เพราะ: callback ไม่ต้อง resample (งานหนักและเสี่ยงกระตุก) · WASAPI shared ใช้ mix format ของ Windows อยู่แล้ว
- เปลี่ยนอุปกรณ์ที่ rate ต่างกัน → ถอดรหัสใหม่ (ยอมรับได้ เพราะเกิดน้อย)

### 2026-10-19 · PCM เก็บเป็นไฟล์ `.f32` + np.memmap ใช้ร่วมกันระหว่าง engine และ AI worker
- เพราะ: PROMPT ข้อ 5.1 ห้ามโหลดซ้ำ · ส่ง array ใหญ่ผ่าน Queue ช้าและกิน RAM สองเท่า · เล่นได้ระหว่างที่ยังถอดรหัสไม่เสร็จ · เป็น cache ไปในตัว
- ไม่ได้เลือก: shared_memory (หายเมื่อปิดโปรแกรม ต้องจัดการ lifecycle เอง)

### 2026-10-19 · time-stretch แบบ render ล่วงหน้าเป็น Segment ไม่ใช่ real-time
- เพราะ: Rubber Band ใน callback หนักเกินไป · PROMPT ข้อ 7.3 บอก "ล่วงหน้า" อยู่แล้ว · `Segment.media_rate` ทำให้นาฬิกาเนื้อเพลงยังถูก

### 2026-10-19 · AI worker ไม่แตะ SQLite — ส่งผลกลับให้ process หลักเขียน
- เพราะ: watchdog ฆ่า/เปิด worker ใหม่ได้ทุกเมื่อโดยไม่มี lock ค้างใน DB · scheduler อยู่ฝั่งหลัก คิวไม่หายเมื่อ worker ตาย

### 2026-10-19 · logic สื่อสารผ่าน EventBus ของเราเอง ไม่ใช้ Qt signal โดยตรง
- เพราะ: test logic ได้โดยไม่ต้องมี Qt · audio/player ทำงานต่อได้แม้ UI พัง · `BusAdapter` แปลงเป็น queued signal เข้า UI thread ที่เดียว

### 2026-10-19 · asyncio loop อยู่ใน thread แยก (ไม่ใช้ qasync)
- เพราะ: UI thread ว่างไว้ให้ QML อย่างเดียว · ไม่ผูก IO กับ Qt event loop
- ไม่ได้เลือก: qasync (เรียบกว่า แต่งาน IO ไปแย่งเวลา UI thread)

### 2026-10-19 · named pipe ตัวเดียวใช้ทั้ง bridge และ single instance
- เพราะ: เปิดโปรแกรมซ้ำ = ต่อ pipe ได้ = มีตัวเดิมอยู่ → ส่ง focus แล้วปิดตัวเอง · ไม่ต้องมีกลไกที่สอง · QLocalServer บน Windows คือ named pipe อยู่แล้ว และ host.py เปิดด้วย `open()` ธรรมดาได้ (ไม่ต้องใช้ pywin32)

### 2026-10-19 · นาฬิกาใช้ seqlock บน numpy array (MediaClock) และ wall clock เทียบ latency ในโหมดคู่หู (RemoteClock)
- เพราะ: callback เขียนได้โดยไม่ lock และไม่จองหน่วยความจำ · Chrome กับโปรแกรมอยู่เครื่องเดียวกัน `Date.now()` กับ `time.time()` จึงเทียบกันได้ตรงๆ
- คลาดเกิน 0.25 วิ = snap (generation +1), น้อยกว่านั้น = ค่อยๆ ไล่ใน 0.5 วิ

### 2026-10-19 · shader ที่คอมไพล์แล้ว (.qsb) commit ไว้ใน repo
- เพราะ: รันได้โดยไม่ต้องมีเครื่องมือคอมไพล์ shader · ตัวติดตั้งไม่ต้องรวม qsb

### 2026-10-19 · ย้ายโปรเจกต์ไปที่ `C:\lyrics` และเริ่ม git
- เพราะ: ผู้ใช้ขอ · path สั้น ไม่มีช่องว่าง/ภาษาไทย (เลี่ยงปัญหากับ PyInstaller/CUDA) · พรอมท์ต้นฉบับยังอยู่ในโฟลเดอร์ ส่วน `PROMPT.md` เป็นสำเนา
