# ARCHITECTURE.md — SyncLyrics

> **อ่านไฟล์นี้ก่อนแก้โค้ดทุกครั้ง** · อัปเดตทุกครั้งที่แก้โครงสร้าง
> สถานะ: เฟส 1 เสร็จ (เล่นเสียงจาก YouTube + เนื้อเพลง + ทีละคำแบบประมาณ + UI ขั้นต่ำ) — ส่วนที่ยังเป็น stub เขียนว่า "เฟส N" ใน docstring (ดู §12)
> ปรับล่าสุด: 2026-10-20

ภาพรวม: โปรแกรมเล่นเพลงบน Windows (Python 3.12 + PySide6/QML) เล่นเสียงจาก YouTube พร้อมเนื้อเพลงทีละคำ, AutoMix ที่เรียนรู้จากดาว และ AI บน GPU ในเครื่อง คู่กับส่วนขยาย Chrome ที่เป็นแค่ตัวส่งเพลง/รีโมต

---

## 0. แผนที่ด่วน: "อาการนี้ แก้ที่ไฟล์ไหน"

| อาการ | ดูที่ |
| --- | --- |
| เสียงกระตุก / แตก / คลิก | `app/audio/engine.py` (`_callback` + กฎเหล็ก), `app/audio/dsp.py`, สถิติ underrun ในหน้า debug |
| เนื้อเพลงไม่ตรงเวลา (ทั้งเพลงเลื่อน) | `app/ai/pipeline/offset.py`, `tracks.lyrics_offset_s`, `app/core/clock.py` (latency) |
| ไฮไลต์ทีละคำเพี้ยนบางช่วง | `app/ai/pipeline/align.py`, `alignment_chunks` ใน DB, `app/lyrics/timing_estimate.py` |
| เนื้อเพลงผิดเพลง | `app/lyrics/title_parser.py` → `app/lyrics/scoring.py` (เพิ่มกรณีใน `tests/fixtures/titles.json`) |
| แหล่งเนื้อเพลงหนึ่งพัง | `app/lyrics/sources/<ชื่อ>.py` (ปิดได้ในหน้าตั้งค่า ระบบข้ามเอง) |
| โหลดเพลงไม่ได้ / 403 / cookies | `app/media/youtube.py` → อัปเดต yt-dlp ก่อนเสมอ (สาเหตุอันดับ 1) |
| ปุ่มบน YouTube หาย | `config/selectors.json` (ไม่ต้องแก้โค้ด) |
| ส่วนขยายต่อไม่ติด | `app/bridge/host.py`, `app/bridge/registry.py`, `app/bridge/pipe_server.py` |
| AI ค้าง / VRAM เต็ม | `app/ai/client.py` (watchdog), `config/models.yaml`, `app/ai/worker.py` |
| มิกซ์ไม่เพราะ | `config/automix_rules.yaml` (มีผลทันที) → `app/automix/planner.py` → ปุ่ม "รายงานมิกซ์ที่ไม่เพราะ" |
| ภาพกระตุก / FPS ตก | `app/ui/qml/*`, `app/ui/shaders/*` (ลด blur), ห้ามสร้าง node ข้อความใหม่ทุกเฟรม |
| เปิดโปรแกรมไม่ขึ้น | เปิดแบบ Safe Mode (กด Shift ค้าง) → `logs/app-*.jsonl` → `app/main.py` |

---

## 1. Process และ thread

```
┌──────────────────────────── process หลัก: SyncLyrics.exe (Python 3.12) ────────────────────────────┐
│                                                                                                    │
│  UI thread (Qt event loop)            PortAudio callback thread           IO thread (asyncio)     │
│  ├─ QML scene graph ──┐               └─ AudioEngine._callback            ├─ yt-dlp (ใน executor)  │
│  │  (render thread    │                  2 deck → mix → limiter           ├─ LyricsService (httpx) │
│  │   ของ Qt, ไม่ใช้ GIL)                  เขียน MediaClock (seqlock)       ├─ artwork / palette     │
│  ├─ BridgeServer (QLocalServer)                                           └─ งานรายวัน (yt-dlp -U) │
│  ├─ BusAdapter ← EventBus              engine control thread                                        │
│  └─ อ่าน Clock ทุกเฟรม                 └─ underrun → buffer ใหญ่ขึ้น      decoder threads (ffmpeg)  │
│                                                                                                    │
│  AiClient: thread ฟัง event queue + watchdog          SQLite: connection แยกต่อ thread (WAL)        │
└───────────────┬────────────────────────────────────────────────────────────────────────────────────┘
                │ multiprocessing.Queue (dict ตาม messages.AI_REQUESTS / AI_EVENTS)
                ▼                                             เสียง: ไฟล์ .f32 ใน cache (np.memmap)
┌──────── AI worker process (priority ต่ำ) ────────┐
│ torch + CUDA: Demucs, MMS_FA, faster-whisper,     │   ← import torch ได้ที่นี่ที่เดียว
│ beat_this/allin1, librosa, pyloudnorm            │   ← ห้ามแตะ SQLite / ฆ่าทิ้งได้ทุกเมื่อ
└──────────────────────────────────────────────────┘

┌── Chrome ──┐  stdio (uint32 LE + JSON)  ┌── synclyrics-host.exe ──┐  named pipe  ┌── process หลัก ──┐
│ ส่วนขยาย    │ ─────────────────────────▶ │ ส่งต่อข้อความอย่างเดียว   │ ───────────▶ │ BridgeServer     │
└────────────┘                            └─────────────────────────┘              └──────────────────┘
```

กฎที่ทำให้ "เสียงห้ามสะดุด" เป็นจริงได้:

1. **audio callback** ทำแค่: อ่านคำสั่งจาก deque → ก็อป PCM → คูณ gain/filter → limiter → เขียนนาฬิกา ห้าม lock, I/O, log, DB, จองหน่วยความจำ (รายละเอียดใน docstring ของ `engine.py`)
2. **GIL**: งานหนักทุกอย่างอยู่นอก process หลัก (AI worker, ffmpeg subprocess) หรือ release GIL (numpy, sqlite3, httpx I/O) · ตั้ง `sys.setswitchinterval(0.001)` · งาน Python ล้วนใน process หลักต้องแบ่งเป็นชิ้น < 5ms (เช่น ตัดคำไทยทีละบรรทัด)
3. **UI พังเสียงต้องเล่นต่อ**: engine ไม่ import Qt และเริ่มก่อน UI · error ใน QML ไม่ไปถึง engine
4. ทางหนีสุดท้าย (ถ้าเฟส 5 วัดแล้วยัง underrun เพราะ GIL): ย้าย engine ไป process แยก — ออกแบบไว้แล้ว: `MediaClock` รับ buffer จาก `shared_memory` ได้, คำสั่งเป็น tuple ธรรมดา, PCM เป็นไฟล์ memmap

---

## 2. การไหลของข้อมูล: กดเล่นจนเนื้อเพลงขึ้น (โหมดแอป)

```
ผู้ใช้กด "เล่นเลย" (ส่วนขยาย / ค้นหา / Ctrl+V)
  └▶ PlayerController.play(TrackRef)
       ├─[IO] cache DB? ──มี──▶ เล่นทันที + เนื้อเพลงทีละคำจาก alignment_chunks
       ├─[IO] YouTubeClient.fetch_info → download_audio (cookies Premium) → Decoder(ffmpeg → .f32 memmap)
       │        └ PCM พอ ~2 วิ ─▶ engine.load + play                    เป้า: เสียงออก < 3 วิ
       ├─[IO] title_parser → LyricsService.find (ทุกแหล่งพร้อมกัน) → scoring → timing_estimate
       │        └▶ EventBus LYRICS_READY → LyricsModel → QML           เป้า: เนื้อเพลงขึ้น < 1 วิ*
       ├─[IO] artwork (iTunes → YouTube thumbnail) + palette
       └─[AI] plan_chunks → Jobs: separate_chunk + align_chunk ช่วงแรก 20-30 วิ (PLAYING_SOON)
                 → ทยอยช่วงละ ~20 วิ นำหน้าตัวเล่น ≥ 30 วิ (CURRENT_REST)
                 → analyze_full (CURRENT_ANALYSIS) ต้องเสร็จก่อนจุดมิกซ์ ≥ 30 วิ
                 → ผลแต่ละช่วง: DB alignment_chunks → LYRICS_TIMING_UPDATED → UI morph เวลาแบบ smooth
                                                     → ALIGN_COVERAGE → แถบบน progress bar
* นับจากที่ได้ผลจากแหล่งแรก — แหล่งช้าใช้ผลที่มาก่อนแล้วสลับถ้าผลที่มาทีหลังคะแนนดีกว่า (ก่อนบรรทัดแรกเริ่มร้อง)
```

กติกาสำคัญ:

- **ตัวเล่นไม่รอ AI เด็ดขาด** ช่วงไหน AI ยังไม่เสร็จใช้เวลาแบบประมาณ (`WordTimingSource.ESTIMATED`)
- **seek** ไปช่วงที่ยังไม่คำนวณ → `AiClient.on_seek` → `JobScheduler.promote` ดันขึ้นหัวคิว
- **ข้ามเพลง** → `JobScheduler.cancel_video` + ส่ง `cancel` ให้ worker
- เนื้อเพลงไม่เจอเลย → `transcribe` (faster-whisper) แสดงป้าย "ถอดเสียงโดย AI อาจมีคำผิด"

โหมดคู่หู: ส่วนขยายส่ง `companion_state` → `RemoteClock.update` (ชดเชย latency จาก `sent_at_ms`) → UI อ่าน `RemoteClock` แทน `MediaClock` · ไม่มี AutoMix · ไม่โหลดเสียง (AI ใช้ไม่ได้ จึงใช้เวลาจากแหล่งหรือแบบประมาณ เว้นแต่เพลงนั้นมีใน cache)

---

## 3. Audio engine (`app/audio/`)

| ไฟล์ | หน้าที่ |
| --- | --- |
| `engine.py` | `AudioEngine`: stream WASAPI shared, 2 deck, คิวคำสั่ง (deque), `clocks[deck]`, `frames_rendered`, สถิติ |
| `deck.py` | `PcmBuffer` (memmap .f32, `frames_ready` เพิ่มทีละก้อน), `Segment`/program (time-stretch แบบ render ล่วงหน้า), `Deck` |
| `decoder.py` | ffmpeg → f32le stereo ที่ sample rate ของ engine → เขียนลง PcmBuffer ทีละก้อน |
| `automation.py` | `AutomationLane` (จุดหักตามเวลา engine), curve linear / equal_power / s_curve — **เขียนจริงแล้ว + มี test** |
| `dsp.py` | Biquad (EQ 3 ย่าน, HP/LP), Echo, Limiter |

การตัดสินใจหลัก:

- **sample rate ของ engine = ของอุปกรณ์** (WASAPI shared ใช้ mix format ของ Windows) → resample ครั้งเดียวตอนถอดรหัส callback ไม่ต้อง resample
- **รูปแบบ PCM**: float32 interleaved stereo, ไฟล์ `cache/audio/<videoId>.f32` — deck และ AI worker เปิดไฟล์เดียวกัน (ไม่โหลดซ้ำ)
- **time-stretch** (Rubber Band) ทำล่วงหน้าเป็น Segment แยก แล้วต่อด้วยต้นฉบับ — `Segment.media_rate` ทำให้นาฬิกาเพลงยังถูกต้องระหว่างช่วงที่ยืด
- **ทุกค่าเปลี่ยนตาม lane** ที่คำนวณไว้ก่อน → ไม่มีค่ากระโดด → ไม่มีเสียงคลิก
- **นาฬิกา**: แต่ละ deck มี `MediaClock` ของตัวเอง (ระหว่างมิกซ์มีสองเพลงพร้อมกัน UI เลือกอ่านของ deck ที่แสดงอยู่) · `host_time = perf_counter() + output latency` = เวลาที่ sample ออกลำโพงจริง
- buffer เริ่ม 15ms (ตั้งได้ 5-200) underrun ซ้ำ → engine control thread เปิด stream ใหม่ด้วย buffer ใหญ่ขึ้น (สูงสุด 120ms)

---

## 4. EventBus และ UI (`app/core/events.py`, `app/ui/`)

logic ทั้งหมดไม่รู้จัก Qt — ส่งเหตุการณ์ผ่าน `EventBus` แล้ว `BusAdapter` แปลงเป็น Qt signal แบบ queued เข้า UI thread

| เหตุการณ์ | payload | ผู้ส่ง |
| --- | --- | --- |
| `track.changed` | video_id, track_ref, deck | player |
| `track.meta_ready` | meta, cover_path, palette | player/media (ส่ง 2 รอบ: ชื่อก่อน แล้วปกตามมา) |
| `playback.state` | playing, video_id | player |
| `lyrics.ready` | lyrics, source_label, candidates_count | lyrics |
| `lyrics.timing` | start, end, words | ai client |
| `lyrics.coverage` | ranges | ai client |
| `analysis.ready` | analysis | ai client |
| `queue.changed` / `preload.status` | items / stage, fraction | player |
| `mix.planned` / `mix.started` / `mix.finished` / `mix.rating_request` | plan / mix_id | automix |
| `ai.status` / `bridge.status` / `error` | … | ai / bridge / ทุกส่วน |
| `lyrics.offset` | video_id, offset | player (ปรับด้วย [ ] — UI เป็นคนเลื่อนเวลา: เวลาเนื้อเพลง = เวลาเสียง − offset) |
| `player.status` | text | player ("กำลังโหลดเสียง 40%") |
| `bridge.message` | type, payload, id, client | bridge (ข้อความดิบจากส่วนขยาย/ตัวเปิดซ้ำ) |

QML (โครงใน `app/ui/qml/Main.qml`): NowPlaying, LyricsView/LyricLine (shader mask ทีละคำ), Background (Fluid/Blur Cover/Video/…), Transitions, RatingPopup, SettingsPage, DebugPage, DesktopLyrics
กฎประสิทธิภาพ: อ่านนาฬิกาทุกเฟรม (ไม่ใช้ Timer), node ข้อความสร้างครั้งเดียวต่อบรรทัด, วาดเฉพาะบรรทัดใกล้จอ, FPS < 50 → ลดเอฟเฟกต์อัตโนมัติ

---

## 5. AI (`app/ai/`)

| ไฟล์ | process | หน้าที่ |
| --- | --- | --- |
| `client.py` | หลัก | เปิด worker (spawn, BELOW_NORMAL), ส่งงานทีละงาน, watchdog (heartbeat), เขียนผลลง DB |
| `scheduler.py` | หลัก | `JobScheduler` (priority + cancel + promote) และ `plan_chunks` — **เขียนจริงแล้ว + มี test** |
| `gpu.py` | หลัก | อ่าน VRAM ด้วย pynvml (ไม่ต้อง import torch) |
| `worker.py` | worker | โหลดโมเดลค้าง VRAM, warm-up, วนทำงาน, heartbeat, ลดขนาดโมเดลเมื่อ VRAM ใกล้เต็ม |
| `pipeline/*.py` | worker | stems, beats, key_loudness, vocal_activity, align, transcribe, offset |

ลำดับความสำคัญ: `PLAYING_SOON (0) > CURRENT_REST (1) > CURRENT_ANALYSIS (2) > NEXT_TRACK (3)` · GPU ทำทีละงาน
งบ VRAM (RTX 4060 8 GB): รวม ≤ 6.5 GB เหลือ ≥ 1.2 GB ให้ UI/วิดีโอ — ค่าทั้งหมดใน `config/models.yaml`
ข้อจำกัดเวอร์ชัน: **torch/torchaudio ล็อกที่ 2.11** เพราะ torchaudio หยุดพัฒนาที่ 2.11 และเป็นรุ่นสุดท้ายที่ยังมี `forced_align` + `MMS_FA` (ตรวจจาก wheel แล้ว)
beat/ท่อน: `beat_this` เป็นตัวหลัก (ติดตั้งง่าย) · `allin1` เป็นตัวเสริม (ออกรุ่นล่าสุด 2023, natten/madmom ติดตั้งยากบน Windows)

ข้อความ worker (ดู `app/core/messages.py`):
- ขอ: `warmup`, `separate_chunk`, `align_chunk`, `transcribe`, `analyze_full`, `cancel`, `status`, `shutdown`
- ตอบ: `ready`, `heartbeat` (ทุก 1 วิ), `progress`, `result`, `failed`, `degraded`

---

## 6. Bridge กับส่วนขยาย (`app/bridge/`, `extension/`)

- ซองข้อความกลาง: `{"v":1, "type":..., "id":..., "payload":{...}}` · framing: uint32 little-endian + JSON UTF-8 (ทั้ง stdio และ pipe)
- ชื่อ host: `com.synclyrics.host` · registry: `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.synclyrics.host` · `allowed_origins` มีแค่ extension ID ของเรา (คำนวณจาก `"key"` ใน manifest ด้วย `registry.extension_id_from_key`)
- named pipe: `\\.\pipe\synclyrics-<username>` (QLocalServer) — **ตัวเดียวกันใช้ทำ single instance**
- host ต่อ pipe ไม่ได้ → เปิดโปรแกรม (`--from-host`) แล้วลองใหม่ 15 วิ · ส่วนขยายต่อใหม่ทุก 2 วิ
- ส่วนขยาย → โปรแกรม: `hello, play_now, enqueue, enqueue_playlist, up_next, companion_state, companion_track, command, log, ping`
- โปรแกรม → ส่วนขยาย: `hello_ack, status, toast, selectors, reload_extension, pause_tab, pong, error`

---

## 7. AutoMix (`app/automix/`)

```
analysis A,B ──▶ compat.py (0-100) ──┬─ < 40 ─────────▶ CLEAN_CUT (ห้ามทดลอง)
                                     ├─ 40-70 ────────▶ crossfade นุ่ม
                                     └─ ≥ 70 ─▶ candidates ─▶ iron_rules.allowed_actions ─▶ bandit.choose
                                                                                                │
             MixPlan (จุดเข้า/ออก, lanes, tempo, beat_times, visual_transition, decision_log) ◀──┘
                │──▶ engine.set_lanes / play(at_frame)          │──▶ UI ทรานซิชั่น (ยาวเท่ามิกซ์จริง)
                └──▶ mixlog (ตาราง mixes) ──▶ rewards (ดาว/สัญญาณ) ──▶ bandit.update
```

- **กฎเหล็ก** (`iron_rules.py`) เป็นด่านสุดท้ายเสมอ รวมตอนทดลอง ถ้าไม่เหลือ action ใดเลย → `CLEAN_CUT` (ผ่านทุกกฎ)
- ข้อมูลไม่พร้อม / AutoMix พัง → `planner.fallback_crossfade`
- **bandit**: Thompson Sampling + Bayesian linear regression ต่อแขน · prior จาก `automix_rules.yaml` · decay ตาม half-life · feature ใน `bandit.CONTEXT_FEATURES` (เพิ่มท้ายเท่านั้น)
- `config/automix_rules.yaml` แก้แล้วมีผลทันที (เฝ้าไฟล์) และคือที่เดียวที่เก็บตัวเลขของ AutoMix

---

## 8. ข้อมูลและไฟล์

### ที่เก็บ

| ที่ | อะไร |
| --- | --- |
| `<โปรเจกต์>/config/` | config ค่าเริ่มต้น (อ่านอย่างเดียว) |
| `%LOCALAPPDATA%\SyncLyrics\` | ข้อมูลผู้ใช้ทั้งหมด (`app/core/paths.py`) — test ใช้ `SYNCLYRICS_HOME` |
| `…\settings.yaml`, `…\config\*.yaml` | ค่าที่ผู้ใช้เปลี่ยน (deep merge ทับค่าเริ่มต้น) |
| `…\synclyrics.sqlite3` | ฐานข้อมูลเดียว |
| `…\cache\audio\*.f32`, `cache\stems\`, `cache\art\` | cache (มีจำกัดขนาด + ปุ่มล้าง) |
| `…\logs\<module>-YYYY-MM-DD.jsonl` | log 7 วัน |
| `…\secrets\cookies.txt` | cookies สำรอง — ห้ามออกนอกเครื่อง |
| `…\state.json` | สถานะทุก 5 วิ (กู้หลัง crash) |

### config (`app/core/config.py`)

ทุกไฟล์มี `version` · ลำดับ: ค่าเริ่มต้น → ของผู้ใช้ → migrate → deep merge → pydantic · **ไฟล์ผู้ใช้พัง = ใช้ค่าเริ่มต้น + คำเตือน (ไม่ crash)**
`config/settings.yaml` สร้างจากโค้ด: `scripts/gen_default_settings.py` (test เตือนถ้าไม่ตรง)

### SQLite (`app/core/db.py`)

- WAL, foreign keys, busy_timeout 5s · migration ด้วย `PRAGMA user_version` (เพิ่มท้าย `MIGRATIONS` เท่านั้น)
- **process หลักเท่านั้นที่เปิด DB** · connection แยกต่อ thread · audio callback ห้ามแตะ

| ตาราง | ใช้ทำอะไร |
| --- | --- |
| `tracks` | ข้อมูลเพลง, ชื่อที่แยกแล้ว, palette, `no_mix`, `theme_id`, `lyrics_offset_s` |
| `audio_cache` | ไฟล์ PCM + LRU |
| `lyrics`, `lyrics_choice`, `user_timing` | ผลจากทุกแหล่ง, ตัวเลือกของผู้ใช้, Tap Sync |
| `analysis`, `alignment_chunks` | ผล AI ทั้งเพลง / ทีละช่วง |
| `queue_items`, `playback_state`, `playlists`, `playlist_items` | คิวและสถานะ |
| `mixes`, `mix_events`, `bandit_state`, `pair_overrides` | AutoMix + การเรียนรู้ |
| `kv` | ค่าทั่วไป (wizard เสร็จแล้ว, อัปเดต yt-dlp ล่าสุด …) |

---

## 9. ของภายนอกที่ต้องมี

| อะไร | ใช้ทำ | หาจากไหน |
| --- | --- | --- |
| Python 3.12.10 (64-bit) | ทั้งโปรแกรม | `winget install --id Python.Python.3.12 -e --scope user` · โปรเจกต์ใช้ `.venv` |
| ffmpeg | ถอดรหัสเสียง | มีในเครื่องแล้ว (8.1) · ตัวติดตั้งจะรวม `bin/ffmpeg.exe` |
| libmpv-2.dll | วิดีโอ (เลือกเปิด) | เฟส 3 |
| rubberband.exe | time-stretch | เฟส 6 |
| CUDA (ผ่าน torch cu128) | AI | `requirements-ai.txt` · ไดรเวอร์ NVIDIA ปัจจุบัน 616.92 รองรับ |

---

## 10. Test

- รันทั้งหมด: `scripts\run_tests.bat` (ใช้ `.venv` ถ้ามี) — ต้องผ่านก่อน build ทุกครั้ง
- `test_smoke_imports.py`: ทุก module import ได้ และ **ไม่ดึง torch/PySide6 ตอน import**
- `test_config_files.py`, `test_db_schema.py`, `test_core_contracts.py`: สัญญากลางของเฟส 0
- marker: `gpu`, `network`, `qt` (ข้ามได้) · fixture ห้ามมีเนื้อเพลงจริง

---

## 11. จุดที่น่าจะพังบ่อย (และทางแก้ที่วางไว้)

1. **YouTube เปลี่ยนระบบ** → yt-dlp อัปเดตเองวันละครั้ง, selector อยู่ใน JSON ไฟล์เดียว
2. **Chrome ล็อกไฟล์ cookies** (Chrome เปิดอยู่) → fallback `cookies.txt` + คำแนะนำใน wizard
3. **API ไม่เป็นทางการ (NetEase/QQ) เปลี่ยน** → plugin ข้ามเงียบๆ, ปิดได้
4. **GIL ทำ audio กระตุก** → ดู §1 ข้อ 2 และทางหนีข้อ 4
5. **VRAM เต็ม** (เกม/เบราว์เซอร์ใช้ GPU ด้วย) → ลดขนาด whisper, unload, watchdog
6. **torch/torchaudio อัปเวอร์ชันแล้ว alignment หาย** → ห้ามอัปเกิน 2.11 (DECISIONS)
7. **allin1 ติดตั้งไม่ได้บน Windows** → beat_this + ตัวแบ่งท่อนแบบง่าย
8. **ตัดคำไทยช้า/วาดสระผิด** → warm-up pythainlp ตอนเปิด, ใช้ grapheme cluster, text shaping ของ Qt


---

## 12. สถานะจริงของเฟส 1 (อัปเดตให้ตรงกับโค้ด)

ทำงานจริงแล้ว: ทุกอย่างในโฟลเดอร์ `app/media`, `app/audio` (deck เดียว), `app/lyrics`, `app/player/controller.py`, `app/main.py`, `app/ui`, single instance (`bridge/pipe_server.py`)
ยังเป็น stub: `app/ai/*` (เฟส 4), `app/automix/*` (เฟส 6-7), `bridge/host.py` + โปรโตคอลส่วนขยาย (เฟส 2), `audio/dsp.py` ยกเว้น Limiter (เฟส 5-6), queue/preload (เฟส 5), shader/ธีม/ตั้งค่า (เฟส 3)

### เส้นทางตั้งแต่กดเล่นจนมีเสียง (วัดจริง: เสียงออก ~2.7 วิจากสถานะเย็น, เนื้อเพลง ~4 วิ)
`PlayerController.play` → `IoThread` → `YouTubeClient.fetch_and_download` (**extract ครั้งเดียว**: `on_info` ถูกเรียกทันทีที่รู้ข้อมูล → เริ่มหาเนื้อเพลง+ปกขนานกับการโหลดเสียง) → `Decoder` (ffmpeg → `.f32` memmap) → `wait_for_frames(2 วิ)` → `engine.load(full_program(buf))` + `play`
เพลงที่เคยเล่น: `audio_cache` ใน DB + `open_cached` (sidecar `<id>.f32.meta.json`) → เล่นทันทีโดยไม่เรียก yt-dlp

### ไฟล์ที่เพิ่ม/ขยายในเฟส 1
| ไฟล์ | หน้าที่ |
| --- | --- |
| `app/core/io_thread.py` | `IoThread`: asyncio loop ใน daemon thread, `submit(coro)` จาก thread ใดก็ได้, `stop()` ยกเลิกงานค้าง |
| `app/media/youtube.py` | `YouTubeClient`: ลำดับ cookies chrome → cookies.txt → ไม่ล็อกอิน (ลดระดับอัตโนมัติ), `fetch_and_download`, `search`, `test_cookies`; ใช้ Node.js ใน PATH แก้โจทย์ JS ของ YouTube (yt-dlp-ejs) |
| `app/media/cache.py` | จำกัดขนาด cache เสียงแบบ LRU, ปุ่มล้าง, ลงทะเบียนไฟล์ |
| `app/media/artwork.py` | ปก: iTunes 1000x1000 (ต้องคล้ายทั้งชื่อ+ศิลปิน+ความยาว) → thumbnail YouTube (palette เฟส 3) |
| `app/audio/engine.py` | `start(open_stream=False)` ใช้ใน test/ไม่มีลำโพง, `_callback` ขับเองได้, control thread ขยาย buffer เมื่อ underrun |
| `app/audio/decoder.py` | `open_cached`, `wait_for_frames`, sidecar meta, ยกเลิกได้ |
| `app/audio/deck.py` | `full_program(buf)` สร้าง program ของ buffer ที่ยังถอดรหัสไม่เสร็จได้ |
| `app/lyrics/service.py` | ค้นทุกแหล่งพร้อมกัน, `on_update` ส่งผลชั่วคราวทันทีที่แหล่งแรกตอบ, cache+ตัวเลือกผู้ใช้ใน DB, `next_candidate`, `set_manual_lyrics` |
| `app/lyrics/title_parser.py` | แยกชื่อ/ศิลปิน (Music section > yt-dlp > ช่อง Topic > ชื่อวิดีโอ, รูปแบบ `ศิลปิน 'เพลง'`, สลับลำดับ), `alt_titles` ให้ scoring |
| `app/lyrics/scoring.py` | คะแนน 0-100: ชื่อ/ศิลปิน/ความยาว/ระดับเวลา/เวอร์ชัน + `TITLE_GATE` (ชื่อไม่คล้ายต้องไม่ผ่านแม้ความยาวตรง) + โทษแบบนุ่มเมื่อความยาวต่าง >10 วิ (MV ยาวกว่าเสียง) |
| `app/lyrics/parsers/*` | LRC/Enhanced LRC, YRC, QRC (ข้อความที่ถอดแล้ว), VTT, plain |
| `app/lyrics/sources/*` | lrclib, netease (YRC ทีละคำ), qqmusic (LRC บรรทัด), lyrics_ovh, youtube_subs (หลายภาษา เรียงตามภาษาร้องที่เดา) |
| `app/player/controller.py` | ประกอบทุกอย่างข้างต้น, offset ต่อเพลง, กู้/บันทึกสถานะ 5 วิ |
| `app/ui/*` | `UiContext`, `PlayerBridge`, `ClockBridge` (QML อ่านนาฬิกาทุกเฟรมผ่าน FrameAnimation), `LyricsModel`, QML 4 ไฟล์, `python -m app.ui.demo` (ข้อมูลปลอม) |
| `scripts/run_app.bat`, `check_cookies.bat/.py` | เปิดโปรแกรม / ตรวจ cookies Premium |

### กติกาที่เพิ่มหลังผู้ใช้ทดสอบเฟส 1
- **ปก:** เพลงต้นฉบับ → iTunes (ปกทางการ) · มี version tag (remix/live/cover/sped up ...) หรือหาปกทางการไม่เจอ → ปกคลิป YouTube (`artwork.fetch_artwork`)
- **เครดิตในเนื้อเพลง** ("作词 : ...", "Produced by: ...", "เนื้อร้อง : ...") ถูกกรองออกที่ parser ทุกตัว (`parsers/lrc.is_credit_line`)
- **403 จาก googlevideo:** `fetch_and_download` ลองซ้ำ 3 แบบ (`FALLBACK_VARIANTS`: ปกติ → ไม่แบ่ง chunk → ไคลเอนต์ tv/web_safari)
- UI มีแถบระดับเสียง (`player.setVolume` → `engine.set_master_volume`)

### ข้อจำกัดที่รู้ (ตั้งใจเลื่อน)
- QRC ของ QQ ทีละคำ: ถอดรหัสไม่ได้ (DES ดัดแปลง) → qqmusic ให้เฉพาะ LRC ระดับบรรทัด
- เนื้อเพลงที่ความยาวต่างจากวิดีโอ >10 วิ: เวลาเหมือนจะเลื่อนทั้งเพลง — แสดงคำเตือนที่ป้ายแหล่ง และปรับมือด้วย `[` `]` · แก้อัตโนมัติด้วย AI ในเฟส 4 (`offset.py`)
- ฟอนต์หลัก **SF Thonburi** (ผู้ใช้เลือก) ต้องติดตั้งในเครื่อง (ไม่ฝังกับโปรแกรม เพราะเป็นฟอนต์ของ Apple) ไม่มี = ใช้ `lyrics_look.font_fallbacks`
