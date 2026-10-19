# Handoff — เฟส 0: วางโครงทั้งระบบ
2026-10-19 · Opus 5.5 (ผู้ใช้ยืนยันระดับการคิด high ตอนเริ่มเฟส)

## สรุปสั้น (5 บรรทัด)
1. ตั้งโปรเจกต์ที่ `C:\lyrics` (git init แล้ว ยังไม่มี commit) และคัดลอกพรอมท์เป็น `PROMPT.md`
2. เขียน `ARCHITECTURE.md` ครบ: process/thread, การไหลของข้อมูล, audio engine, AI, bridge, AutoMix, DB, จุดพังบ่อย
3. สร้างโครงโค้ดทุก module (ส่วนใหญ่เป็น interface + docstring ไทย ที่โยน `NotImplementedError("เฟส N")`)
4. ส่วนที่เป็น "สัญญากลาง" เขียนจริงแล้วพร้อม test: paths, log, config, DB schema, นาฬิกา, ข้อความ, คิวงาน AI, การแบ่งช่วง, curve
5. เปลี่ยนจาก PROMPT: Python 3.12 (ผู้ใช้ยืนยัน), torch ล็อก 2.11, beat_this เป็นตัวหลัก, เพิ่ม `app/core|media|player`

## สิ่งที่สร้างเสร็จ (ทีละฟีเจอร์ + สถานะ)
| ฟีเจอร์ | สถานะ |
| --- | --- |
| โครงโฟลเดอร์ตาม PROMPT 1.3 (+ core/media/player) | ใช้ได้ |
| `app/core/paths.py` — path ทั้งหมด, `SYNCLYRICS_HOME` สำหรับ test | ใช้ได้ |
| `app/core/log.py` — JSON lines ต่อ module, ลบเกิน 7 วัน, ring buffer, `redact()` | ใช้ได้ (ยังไม่มี test เฉพาะ) |
| `app/core/config.py` — pydantic models, migrate, deep merge, ไฟล์ผู้ใช้พัง = ค่าเริ่มต้น | ใช้ได้ + test |
| `app/core/db.py` — schema v1 (16 ตาราง), migration ด้วย user_version | ใช้ได้ + test |
| `app/core/clock.py` — MediaClock (seqlock), RemoteClock (latency + slew) | ใช้ได้ + test |
| `app/core/messages.py` — envelope, ชนิดข้อความ bridge/AI, framing uint32+JSON | ใช้ได้ + test |
| `app/core/events.py` — EventBus + ชื่อเหตุการณ์มาตรฐาน | ใช้ได้ + test |
| `app/ai/scheduler.py` — JobScheduler, plan_chunks | ใช้ได้ + test |
| `app/audio/automation.py` — curve 3 แบบ, AutomationLane | ใช้ได้ + test |
| `app/player/state.py` — save/load state แบบ atomic | ใช้ได้ + test |
| `app/media/youtube.py: parse_video_id`, `app/bridge/registry.py: extension_id_from_key` | ใช้ได้ + test |
| `app/lyrics/sources/base.py: discover()` — ระบบ plugin | ใช้ได้ (5 plugin เป็น stub) |
| config ค่าเริ่มต้น: settings / models / automix_rules / selectors + ธีม minimal | ใช้ได้ + test |
| audio engine, decoder, dsp, lyrics service/parsers, AI worker/pipeline, automix, bridge host, UI | ยังไม่ได้ (stub ตามเฟส) |

## ไฟล์ที่สร้างหรือแก้ (path + หน้าที่ + จุดสำคัญในไฟล์)
- `PROMPT.md` — สำเนาพรอมท์หลัก (ต้นฉบับ `SyncLyrics — มาสเตอร์พรอมท์.md` อยู่ข้างกัน)
- `ARCHITECTURE.md` — §0 "อาการ → ไฟล์", §1 แผนผัง process + กฎ GIL, §2 การไหลของข้อมูล, §8 ตาราง DB
- `.gitignore` — กัน cookies, `extension/key.pem`, `.venv`, cache, `*.sqlite3`
- `pyproject.toml` — ตั้งค่า pytest (markers gpu/network/qt, asyncio_mode=auto), `requires-python >=3.12,<3.13`
- `requirements.txt` (หลัก), `requirements-ai.txt` (torch cu128 + AI), `requirements-ai-optional.txt` (allin1), `requirements-dev.txt` (pytest)
- `scripts/setup_venv.bat` — สร้าง `.venv` ด้วย py -3.12 + ติดตั้ง requirements-dev
- `scripts/run_tests.bat` — รัน test ทั้งหมดด้วยคำสั่งเดียว
- `scripts/gen_default_settings.py` — สร้าง `config/settings.yaml` จาก `Settings()` (ห้ามแก้ไฟล์ yaml ด้วยมือ)
- `config/models.yaml` — ค่าสำหรับ RTX 4060 (งบ VRAM 6500 MB, Demucs fp16 segment 7s, whisper large-v3-turbo)
- `config/automix_rules.yaml` — กฎเหล็ก, น้ำหนักความเข้ากัน (รวม = 1.0), เกณฑ์ 40/70, รูปแบบมิกซ์, ค่าการเรียนรู้, ตารางรางวัล
- `config/selectors.json` — selector เบื้องต้น (ต้องตรวจกับหน้า YouTube จริงในเฟส 2)
- `themes/minimal.json` — ธีมตัวอย่าง (key ตรงกับ `LyricsLook`/`BackgroundSettings`)
- `app/core/*` — ดูตารางด้านบน · `app/core/health.py`, `report.py` เป็น stub
- `app/audio/engine.py` — **docstring ระบุกฎเหล็กของ callback** อ่านก่อนเขียนเฟส 1
- `app/audio/deck.py` — `PcmBuffer.open_file` (memmap), `Segment.media_rate`, `Deck.media_position()`
- `app/ai/scheduler.py` — `Priority`, `JobScheduler.promote` (seek), `plan_chunks` (ไม่ตัดกลางบรรทัด)
- `app/automix/planner.py` — `MixStyle` (+ `safety_rank`), `MixAction`, `MixPlan` = สัญญาระหว่าง automix/engine/UI
- `app/automix/bandit.py` — `CONTEXT_FEATURES` (ลำดับ = ลำดับใน vector ห้ามแทรก)
- `app/bridge/host.py` — `pipe_name()` = `synclyrics-<username>` ต้องตรงกับ QLocalServer
- `app/main.py` — ลำดับการเปิดโปรแกรม 8 ขั้น, `shift_held()` สำหรับ Safe Mode
- `extension/README.md` — แผนไฟล์ของส่วนขยาย (ยังไม่มี manifest — เฟส 2)
- `tests/` — 4 ไฟล์ test, `tests/fixtures/README.md`
- `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/handoff/PHASE-0.md`

## วิธีรันและทดสอบ (คำสั่งจริงที่ใช้ได้ทันที)
```bat
cd C:\lyrics
scripts\setup_venv.bat
scripts\run_tests.bat
```
ยังเปิดโปรแกรมไม่ได้ (`py -m app` จะเจอ NotImplementedError("เฟส 1") — ตั้งใจ)

## ผล test (ผ่านกี่ข้อ ไม่ผ่านข้อไหน เพราะอะไร)
- 2026-10-19 รันบน Python 3.13.5 (venv ชั่วคราวนอกโปรเจกต์ มีแค่ pytest, pytest-asyncio, PyYAML, pydantic, numpy): **106 passed, 0 failed**
  - smoke import ทุก module (+ ตรวจว่าไม่ดึง torch/PySide6 ตอน import)
  - config 10 ข้อ, DB 4 ข้อ, สัญญากลาง 16 ข้อ
- ระหว่างทำ: เจอ test เขียนผิด 1 ข้อ (สตริง `"::: not yaml ["` YAML อ่านได้จริงเป็น mapping) แก้เป็นกรณี syntax ผิด + ชนิดข้อมูลผิด
- 2026-10-20 รันบน **Python 3.12.10** ใน `.venv` (ติดตั้ง requirements-dev.txt ครบ): **106 passed, 0 failed**
- pin ทุกตัวใน requirements.txt ติดตั้งผ่านบน 3.12 (PySide6 6.12.0, numpy 2.5.4 ฯลฯ) · sounddevice เห็นอุปกรณ์เสียง 46 รายการ

## สิ่งที่ผู้ใช้ทดสอบแล้วและผลที่ได้
- ผู้ใช้ให้ AI ทำแทน: ติดตั้ง Python 3.12.10 ด้วย `winget install --id Python.Python.3.12 -e --scope user` → `scripts\setup_venv.bat` ผ่าน → `scripts\run_tests.bat` 106 passed
- หมายเหตุ: python.org ไม่มีตัวติดตั้ง Windows ของ 3.12 รุ่นใหม่กว่า 3.12.10 แล้ว (เหลือแต่ source) — ใช้ 3.12.10

## บั๊กที่รู้แต่ยังไม่แก้
- ไม่มี

## การตัดสินใจและเหตุผล (รวมสิ่งที่ต่างจาก PROMPT.md)
ดู `docs/DECISIONS.md` (2026-10-19 ทั้งหมด) สรุปที่ต่างจาก PROMPT:
- Python 3.12 แทน 3.11 (ผู้ใช้เลือก)
- torch/torchaudio ล็อก 2.11.0+cu128 (torchaudio รุ่นสุดท้ายที่ยังมี MMS_FA)
- beat_this เป็นตัวหลัก, allin1 เป็นตัวเสริม
- เพิ่มโฟลเดอร์ `app/core`, `app/media`, `app/player`

## สิ่งที่ผู้ใช้บอกหรือขอระหว่างแชต
- ย้ายโปรเจกต์ไปที่ `C:\lyrics` (ทำแล้ว · โฟลเดอร์เดิม `C:\Users\user\Downloads\lyrics` ว่างแล้ว)
- เลือก Python 3.12
- คุยภาษาไทย

## สภาพแวดล้อม
- Windows 11 Pro 10.0.26200 · คอมตั้งโต๊ะ
- GPU: NVIDIA GeForce RTX 4060 8 GB · ไดรเวอร์ 616.92
- Python: **3.12.10** (ติดตั้งแบบ user ผ่าน winget) + 3.13.5 · โปรเจกต์ใช้ `C:\lyrics\.venv` (3.12) · คำสั่ง `python` เฉยๆ ชี้ไป Microsoft Store — ใช้ `.venv\Scripts\python` หรือ `py -3.12`
- ffmpeg 8.1.2 (gyan.dev full build) อยู่ใน PATH · git 2.54 · Node 24.18
- ติดตั้งใน .venv แล้ว: requirements.txt + pytest · ยังไม่ติดตั้ง: requirements-ai.txt (torch — เฟส 4), CUDA toolkit ไม่จำเป็น (torch cu128 มี runtime ในตัว)

## กับดักที่เจอ
- **heredoc ใน Bash tool ทำ `\\` เหลือ `\`** และ heredoc ยาวๆ บางครั้ง parse พัง → เขียนไฟล์ด้วย Write tool แทน หรือใช้ raw string
- console ของ Windows เป็น cp874 → Python พิมพ์ภาษาไทยเพี้ยน ใช้ `PYTHONIOENCODING=utf-8` (ไฟล์ไม่เพี้ยน)
- `.bat` ที่มีภาษาไทยต้องมี `chcp 65001` และบรรทัดแบบ CRLF
- YAML อ่านข้อความแปลกๆ เป็น mapping ได้ (`"::: x"` → `{'::': 'x'}`) อย่าใช้เป็นตัวอย่าง "ไฟล์พัง"
- `pip index versions` ใช้ได้ แต่ต้องดู `requires_python` จาก `https://pypi.org/pypi/<pkg>/json` ด้วย (numpy 2.5/librosa 1.0 ต้อง ≥3.12)

## interface ที่เฟสถัดไปต้องใช้
- **ข้อมูลเพลง/เนื้อเพลง**: `app/core/models.py` — `TrackRef`, `TrackMeta`, `Lyrics/Line/Word` (+ `TimingLevel`, `WordTimingSource`, `Voice`), `Analysis`
- **นาฬิกา**: engine เรียก `clocks[deck].publish(media_pos, host_time, rate, playing, generation)` ทุก callback · UI เรียก `position()` ทุกเฟรม
- **engine API** (เฟส 1 เขียนจริง): `start/stop/set_device`, `load(deck, video_id, program)`, `play(deck, at_frame)`, `pause`, `seek`, `set_lanes`, `clear_deck`, `set_master_volume`, `stats`
- **PCM**: `PcmBuffer.open_file(path, sample_rate, total_frames)` → decoder เขียน + เพิ่ม `frames_ready` → เฟส 1 ใช้ program 1 segment
- **เนื้อเพลง**: `LyricsService.find(track, duration) -> LyricsResult` · plugin: `LyricsSource.search(query, client)` + `SOURCE = ...` · `scoring.WEIGHTS` · `timing_estimate.estimate_lyrics`
- **yt-dlp**: `YouTubeClient.fetch_info / download_audio / fetch_subtitles / search / test_cookies`
- **EventBus**: ชื่อเหตุการณ์ใน `app/core/events.py` (เพิ่มได้ ต้องเขียนลง ARCHITECTURE §4)
- **DB**: `db.connect(paths.db_file)` (migration อัตโนมัติ) · ตารางที่เฟส 1 ใช้: `tracks`, `audio_cache`, `lyrics`, `lyrics_choice`, `playback_state`, `kv`
- **config**: `load_model(paths, "settings.yaml", Settings)` → `(settings, warnings)` · `save_settings()`
- **log**: `setup_logging(paths.logs_dir)` ครั้งเดียว · `get_logger("audio")` · ห้ามเรียกใน audio callback
- **single instance**: `bridge.pipe_server.notify_existing_instance(argv)` + `BridgeServer.start()` (ส่วนนี้เฟส 1 ต้องทำพร้อมหน้าต่างหลัก)

## สิ่งที่เฟสถัดไปต้องรู้ก่อนเริ่ม และควรเริ่มจากตรงไหน
1. `.venv` (Python 3.12.10) พร้อมแล้ว test 106 ข้อผ่าน — เริ่มเฟส 1 ด้วย `scripts\run_tests.bat` ให้เห็นว่ายังเขียวก่อนแก้อะไร
2. ลำดับแนะนำของเฟส 1:
   1. `media/youtube.py` (info + download + cookies fallback) → test กับวิดีโอจริง (marker `network`)
   2. `audio/decoder.py` + `audio/engine.py` แบบ deck เดียว + Limiter แบบง่าย → เล่นเสียงได้ก่อนอย่างอื่น
   3. `lyrics/parsers/lrc.py` + `sources/lrclib.py` + `title_parser.py` + `scoring.py` + `timing_estimate.py` + `thai.py` (มี test ทุกตัวด้วย fixture สมมติ)
   4. แหล่งที่เหลือ (youtube_subs, netease, qqmusic, lyrics_ovh) + parsers yrc/qrc/subtitles
   5. `player/controller.py` + `main.py` + UI ขั้นต่ำ (QML แสดงเนื้อเพลงทีละคำแบบ wipe ง่ายๆ อ่าน MediaClock ทุกเฟรม) + single instance
3. **ห้ามละเมิดกฎ audio callback** ใน docstring ของ `engine.py` แม้แต่ในเฟส 1
4. ห้ามฝังเนื้อเพลงจริงใน test — ใช้ข้อความสมมติ

## คำถามที่ยังไม่ได้คำตอบจากผู้ใช้
- ไม่มี (คำถามเรื่อง Python ตอบแล้ว)

## ข้อความสำหรับวางในแชตใหม่ (copy ได้ทันที)
```
อ่าน PROMPT.md, ARCHITECTURE.md, docs/PROGRESS.md, docs/DECISIONS.md
และ docs/handoff/PHASE-0.md ให้ครบ แล้วเริ่มเฟส 1
```
