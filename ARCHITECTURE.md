# ARCHITECTURE.md — SyncLyrics

> **อ่านไฟล์นี้ก่อนแก้โค้ดทุกครั้ง** · อัปเดตทุกครั้งที่แก้โครงสร้าง
> สถานะ: เฟส 2 โค้ดเสร็จ รอผู้ใช้ทดสอบ — **แอปไม่เล่นเสียง (ผู้ใช้สั่ง 2026-10-20): เล่นใน YouTube อย่างเดียว แอปเป็นหน้าต่างเนื้อเพลงลอยตาม UX UI.txt** (ส่วนขยาย Chrome + native host + โหมดคู่หูโหมดเดียว + หน้าต่างลอย/ตั้งค่า/tray + health check — ดู §13; §2/§3/§7 ส่วนโหมดแอป/เสียง/AutoMix เป็นโค้ดที่ปิดอยู่) · เฟส 1 = เล่นเสียงจาก YouTube + เนื้อเพลง + ทีละคำแบบประมาณ · ส่วนที่ยังเป็น stub เขียนว่า "เฟส N" ใน docstring (ดู §12)
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
| ส่วนขยายต่อไม่ติด | ไอคอนจุดแดง = host ไม่ได้ลงทะเบียน (`app/bridge/registry.py`, `scripts\install_extension.bat`) · เทา = แอปไม่ได้เปิด · ดู `logs/bridge-host.log`, `app/bridge/host.py`, `app/bridge/pipe_server.py`, `app/bridge/service.py` |
| ส่งเพลงจาก YouTube เข้าแอปไม่ไป / เสียงซ้อน 2 ทาง | `extension/content.js` (`handoff`, `onVideoPlay`), `app/bridge/service.py` (`_h_play_now`) |
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
| `bridge.message` | type, payload, id, client | bridge (ข้อความดิบจากส่วนขยาย/ตัวเปิดซ้ำ; type="_disconnected" เมื่อ client หลุด) |
| `bridge.status` | connected, ext_version | BridgeService (หลัง hello / เมื่อ client สุดท้ายหลุด) |
| `mode.changed` | mode (app/companion) | player |
| `queue.changed` | items (dict ของ TrackRef), index | player |
| `health.report` | items (HealthItem), text | main (run_health ใน IO thread ตอนเปิด) |

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
ยังเป็น stub: `app/ai/*` (เฟส 4), `app/automix/*` (เฟส 6-7), `audio/dsp.py` ยกเว้น Limiter (เฟส 5-6), preload/คิวเต็มรูปแบบ (เฟส 5), shader/ธีม/ตั้งค่า (เฟส 3) — bridge/ส่วนขยาย/คิวขั้นต่ำเสร็จในเฟส 2 (§13)

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


---

## 13. สถานะจริงของเฟส 2: แอปแสดงเนื้อเพลงตามเพลงที่เล่นใน YouTube (ไม่เล่นเสียงเอง)

> ทิศทางผลิตภัณฑ์ (DECISIONS 2026-10-20): ผู้ใช้เล่นเพลงใน YouTube เท่านั้น · แอปไม่เล่นเสียง ไม่เปิดอุปกรณ์เสียง (`PlaybackSettings.app_audio=False`) · แอปเป็น "Premium Desktop Lyrics Utility" ตาม `add by win/UX UI.txt` · โค้ดโหมดแอปเดิม (engine/decoder/คิว/`controller.play`) เก็บไว้แต่ปิด — เฟส 5-7 ยังไม่ได้ตัดสินใจ (ถามผู้ใช้)

### โครงสร้าง (Chrome → แอป)
```
extension/content.js ─┐ chrome.runtime.sendMessage        ┌ extension/background.js (service worker)
 (ทุกแท็บ YouTube)    └──────────────────────────────────▶│  connectNative + เลือกแท็บต้นทางที่กำลังเล่น
   ส่งแค่ video_id + เวลา                                   └─── stdio (uint32 LE + JSON) ───▶ app/bridge/host.py (HostBridge)
   (ไม่ส่งชื่อเพลงจากหน้าเว็บ)                                                                      │ named pipe \\.\pipe\synclyrics-<user> (หรือ $SYNCLYRICS_PIPE)
                                                       app/bridge/pipe_server.py (BridgeServer, QLocalServer, UI thread) ◀┘
                                                                  │ EventBus "bridge.message"
                                                       app/bridge/service.py (BridgeService, ไม่รู้จัก Qt) ──▶ PlayerController (โหมด companion)
```
- **host อยู่ตลอดและไม่เปิดแอปเอง**: รอ pipe ทุก 1 วิ เปิดแอปเมื่อส่วนขยายส่ง `launch_app` เท่านั้น (กดไอคอน/เมนู) · host → ส่วนขยาย: `host_connected` (→ ส่งตัว `hello`), `status{connected:false}`, `error{app_not_running}`
- ฝั่งอ่าน pipe ใช้ `PeekNamedPipe` ก่อนอ่านเสมอ (handle แบบ synchronous ของ Windows ล็อกการเขียนระหว่างที่อ่านค้าง)
- จุดเข้าแอปคือ `python -m app` (ไม่ใช่ `-m app.main`) · ระหว่างพัฒนา Chrome เปิด `scripts\synclyrics-host.bat` · ตัวติดตั้ง (เฟส 8) ใช้ `synclyrics-host.exe`
- ส่วนขยาย ID คงที่ `jjafolpgjdghgjadopngdolglpllbhod` (key ใน manifest; `extension/key.pem` ห้าม commit — **สำรองไว้**)
- ข้อความ ส่วนขยาย→แอป: `hello, companion_track{track:{video_id}}, companion_state{video_id,current_time,rate,paused,sent_at_ms,seeked,duration}, command{play_pause|next|prev|seek|open_settings|focus}, launch_app (host จัดการเอง), log` · แอป→ส่วนขยาย: `hello_ack{auto_send}, status, tab_control{play|pause|seek|next|prev}, reload_extension, error` (`play_now/enqueue*` ยังมีในโปรโตคอลแต่แอปเมินเมื่อ `app_audio=False`)

### flow: เพลงเปลี่ยนใน YouTube → แอปตามทัน
1. content.js ฟัง `<video>` (play/pause/seeked/ratechange/loadedmetadata/…) + `yt-navigate-finish` + ส่งเวลาทุก 250ms ตอนเล่น (ตรวจการกรอจากเวลากระโดด >0.7 วิด้วย) · ไม่หยุด/ไม่แตะวิดีโอ
2. background.js เลือกแท็บต้นทาง: ยึดแท็บที่กำลังเล่น (แท็บอื่นที่หยุดอยู่ไม่แย่ง · แท็บอื่นเริ่มเล่น = ย้าย · เงียบเกิน 3 วิ = รับช่วงได้) · ปิดแท็บต้นทาง = ส่ง `paused:true`
3. แอป `controller.companion_state`: videoId ไม่ตรงเพลงปัจจุบัน → **จับเพลงใหม่เอง** (ไม่ต้องพึ่ง companion_track) → `companion_track` → เคลียร์หน้าจอทันที (TRACK_CHANGED ชื่อว่าง) → `_resolve_companion_track`: oEmbed (~0.2 วิ) + yt-dlp `fetch_info` (รอไม่เกิน `INFO_WAIT_S`=3 วิ) → `_side_tasks` (เนื้อเพลง → ปก) · **ชื่อ/ช่อง/Music section จากหน้าเว็บเป็นแค่คำใบ้** ใช้ Music section ก็ต่อเมื่อชื่อบนหน้าตรงกับชื่อที่ยืนยันแล้ว (`_same_title`)
4. เวลาเนื้อเพลง = `RemoteClock` (ชดเชย latency จาก `sent_at_ms`, สไลด์ค่อยๆ ไล่ถ้าคลาด <0.25 วิ, snap ถ้ากรอ) · ปุ่ม/คีย์ลัดในแอป → `controller._tab()` → `tab_control` → แท็บต้นทาง
5. ล้างแคชเนื้อเพลง/ชื่อที่บันทึกผิดจากบั๊กเก่าครั้งเดียวตอนเปิด (`db.purge_stale_companion_cache`, kv `purge_stale_companion_meta_v1`)

### UI (add by win/UX UI.txt) — `app/ui/qml/`
| ไฟล์ | หน้าที่ |
| --- | --- |
| `Main.qml` | รากเป็น `QtObject` (ไม่มีหน้าต่างหลัก): สร้าง `Overlay` + `SettingsWindow` + `Tray` · `showOverlay()/showSettings()` ให้ Python เรียก |
| `Overlay.qml` | หน้าต่างเนื้อเพลงลอย frameless/โปร่งใส/`Qt.Tool` (ไม่ขึ้น Taskbar)/always-on-top · 2 โหมดลอย: minimal(บรรทัดเดียว พื้นหลังโปร่งมาก ไม่มีเงา/ขอบ)/focus(3 บรรทัด ค่าเริ่มต้น) ขนาดจำแยกตามโหมด จำนวนบรรทัด→ความสูง · พื้นหลัง โปร่งใส/กระจกฝ้า(เบลอฉากหลังจริง acrylic)/ดำนุ่ม/ทึบ/gradient/กำหนดเอง + ความโปร่งใสทั้งหน้าต่าง · แถบควบคุมโผล่ตอนชี้เมาส์พร้อม tooltip (ย้าย/ล็อก/โหมด/เต็มจอ/แปล/ตัวอื่น/ตั้งค่า/ซ่อน) · ปรับขนาดที่ขอบ · click-through (บอกวิธีปิด) · จำตำแหน่ง/ขนาด · กันหลุดจอ · ตำแหน่งสำเร็จรูป + center_h + ตำแหน่งเริ่มต้น + เลือกจอ · snap ขอบจอ 18px |
| `FullWindow.qml` | **หน้าต่างโหมดเต็มแบบ Apple Music**: หน้าต่างปกติ (แถบชื่อ ย่อ/ขยาย/ปิดได้) + เต็มจอ (F/F11, Esc ออก) จำขนาด/ตำแหน่ง · พื้นหลังไหลลื่นสีจากปก (`shaders/fluid.frag`, สีมาจาก `player.palette` ← `artwork.dominant_colors`) · ปกซ้าย (`FullPanel`) เนื้อเพลงใหญ่ชิดซ้าย ขนาดตามความสูงหน้าต่าง × `fw_font_scale` · แถบควบคุม+เมาส์ซ่อนเองตอนเต็มจอ · เปิดแล้วหน้าต่างลอยซ่อน · หน้าต่างแคบ (<760px) = หัวเรื่องย่อ + เนื้อเพลงเต็มกว้าง · คีย์ลัด Space ←→ N P [ ] + − T |
| `LyricsView.qml` / `LyricLine.qml` | เลื่อนสปริง/ไฮไลต์ทีละคำ 4 แบบ (fill/word/glow/line)/แอนิเมชัน 4 แบบ/ลดการเคลื่อนไหว/คำแปลใต้บรรทัด/สถานะว่าง (รอเชื่อมต่อ·การเชื่อมต่อหลุด·กำลังค้นหา·ไม่พบ·ไม่รองรับ(ถ่ายทอดสด)) · **แอนิเมชันปรับแต่งได้ละเอียด** (ชุดสำเร็จรูป 5 ใน `anim_presets.py` + ความเร็ว/ความแรง/สปริง stiffness-damping/คลื่นหน่วงต่อบรรทัด/เบลอตามระยะ (MultiEffect เฉพาะ 6 บรรทัดใกล้)/ความจาง/ขนาดบรรทัดอื่น/การลอยของคำ/น้ำหนักบรรทัดปัจจุบัน) · ป้ายแหล่ง + "เวลาทีละคำเป็นการประมาณ" เมื่อเวลาแค่ระดับบรรทัด (spec 4.4) · รับสี/ขนาด/การจัดวาง/pastFilled ทับจากภายนอกได้ (FullWindow ใช้ซ้ำ) |
| `FullPanel.qml` | แผงเพลงฝั่งซ้ายของโหมดเต็ม: ปกมุมโค้ง **ครอปเต็มช่องใน shader** (`rounded_image.frag` รับ `imgSize` — ShaderEffect ใช้ texture ทั้งรูปเสมอ ไม่สน fillMode ถ้าไม่ครอปเองรูป 16:9 จะถูกบีบ), ชื่อ/ศิลปินชิดซ้าย, แถบเวลา (คลิก=สั่งกรอที่ YouTube), ◀◀ ❚❚ ▶▶ (สั่งแท็บ) |
| `SettingsWindow.qml` | ตั้งค่า 5 หมวด: รูปลักษณ์/เนื้อเพลง/หน้าต่าง/การซิงก์/ทั่วไป (คีย์ลัด, เปิดพร้อม Windows, รีเซ็ต) — เห็นผลทันที · ปิดหน้าต่าง = ซ่อน |
| `Tray.qml` | ไอคอนถาดระบบ: แสดง/ซ่อน, ตั้งค่า, คลิกทะลุ, ล็อก, เชื่อมต่อ YouTube, ออก |
- ค่าตั้งทั้งหมดอยู่ใน `cfg` (`QQmlPropertyMap`, คีย์ `ov_*` overlay, `look_*` ฟอนต์/เนื้อเพลง, `hk_*` คีย์ลัด, `st_*` เริ่มต้น) ← `app/ui/settings_bridge.py` + `settings_store.py` (ตรรกะล้วน ตรวจค่า/ธีมเปลี่ยนตาม/รีเซ็ต) + `themes.py` (ธีมสำเร็จรูป 5) · QML เขียน `cfg.ov_mode = "full"` ได้ตรงๆ → ตรวจ → เซฟ `settings.yaml` แบบ debounce 0.5 วิ
- **ปุ่ม ↺ รายตัว:** `Row2` ใน `SettingsWindow.qml` หา `key` จากตัวควบคุมตัวแรกในแถว (หรือ `resetKey:` ระบุเอง) แล้วถาม `settingsBridge.isDefault(key, cfg[key])` → `SettingsStore.is_default` · กด = `resetKey` → `SettingsStore.reset_key` (ผ่าน `set()` ผลข้างเคียงของธีม/ชุดแอนิเมชันทำงานเหมือนผู้ใช้ปรับเอง) · **ชุดการตั้งค่าตั้งชื่อ:** `app/ui/settings_presets.py` (`PresetStore` ไฟล์ `<data>/settings_presets.json` เขียนแบบ atomic ไฟล์พัง→.bad) + `SettingsStore.snapshot/apply_snapshot` (เฉพาะหมวด full/float/font/theme/lyrics/anim ยกเว้น ov_visible/ov_monitor/fw_maximized) · bridge: `savePreset/loadPreset/deletePreset/presetNames`
- คีย์ลัดทั้งระบบ `app/ui/hotkeys.py` (RegisterHotKey, เธรดเดียว, รายงานคีย์ซ้ำ) · เปิดพร้อม Windows `app/ui/startup.py` (HKCU Run)
- Qt 6 `quit()` ให้หน้าต่างปฏิเสธการปิดได้ → หน้าตั้งค่าที่ซ่อนลงถาดต้องยอมปิดเมื่อ `settingsBridge.quitting` (เคยทำให้ "ออกจากโปรแกรม" ค้าง)
- เบลอฉากหลังจริง (`app/ui/winfx.py`, ctypes): `SetWindowCompositionAttribute` acrylic + `DWMWA_WINDOW_CORNER_PREFERENCE` มุมโค้ง 8px (Windows 11; Windows 10 ถอยไปใช้ `SetWindowRgn`) — เฉพาะสไตล์ "กระจกฝ้า" + `ov_blur_behind` · `SetWindowRgn` อย่างเดียวบน Windows 11 ไม่ตัดส่วนที่เบลอ (มีมุมเหลี่ยมโผล่) จึงใช้ DWM
- ปก: `artwork.autocrop_black_bars` ตัดขอบดำ + **`find_art_square`** ตัดปกจัตุรัสออกจาก thumbnail แบบ Topic (ปกกลางพื้นหลังเบลอ 16:9: ตรวจจากรายละเอียดคอลัมน์ + ต้องกึ่งกลางและกว้างเท่าความสูง) · `dominant_colors` สีเด่น 4 สีของปก (Pillow median-cut; ปกขาวดำคงโทนเทา) → `TRACK_META_READY.palette` → `player.palette`
- ยังไม่ทำ (P2 ที่เหลือ): ตำแหน่งแยกต่อจอ, ธีม export/import, เนื้อเพลงไม่มีเวลา (โหมดไม่ซิงก์), ภาษา UI อังกฤษ, edge glow, ตัวเลือกคำแปลหลายภาษา

### ตัวช่วยติดตั้ง / health check
`app/bridge/installer.py`: คัดลอก `extension/` (ไม่รวม key.pem/README) → `%LOCALAPPDATA%\SyncLyrics\extension` + ลงทะเบียน host (HKCU) + path ใส่ clipboard + เปิด chrome://extensions (ปุ่ม "ติดตั้งส่วนขยาย" ใน UI/tray หรือ `scripts\install_extension.bat`) · `app/core/health.py`: ตรวจ Node.js/cookies/ส่วนขยาย (ffmpeg/อุปกรณ์เสียงเฉพาะเมื่อ `app_audio`) ไม่ใช้เครือข่าย

### ข้อควรรู้
- เสียงที่ yt-dlp ดึงได้ opus ~137k เท่ากันทั้งมีและไม่มี cookies — cookies มีประโยชน์กับวิดีโอจำกัดอายุเท่านั้น
- `youtube_subs`: ชื่อวิดีโอเป็นไทย/ญี่ปุ่น/เกาหลี แต่คำบรรยายไม่ตรงภาษา = ถือเป็นคำแปล ไม่ส่งเป็นผล
- ปก: iTunes (ต้นฉบับ) / thumbnail ของคลิป (รีมิกซ์/ไม่เจอ) + ตัดขอบดำของ thumbnail (`artwork.autocrop_black_bars`, Pillow)
- **ยังไม่แก้ (เฟส 4):** เวลาเนื้อเพลงของ MV/คลิปที่ไม่ใช่ official audio ไม่ตรงเสียงจริง — ต้องฟังเสียงจัดเวลา (ดู PROGRESS)
- test: `test_bridge.py`, `test_phase2.py`, `test_settings_store.py`, `test_hotkeys_startup.py`, `test_ui_smoke.py` (QML ทุกโหมด/ธีม), `test_extension_js.py` + `tests/js/background.test.js` · **end-to-end กับ Chrome ตัวจริง** (headless + `Extensions.loadUnpacked` ผ่าน `--remote-debugging-pipe` + host จริง + แอปจริง `SYNCLYRICS_PIPE=synclyrics-e2e`) — สคริปต์อยู่ใน scratchpad ของเซสชัน ยังไม่ได้ commit


---

## 14. เฟส 4: AI ฟังเสียงจัดเวลาเนื้อเพลง + แปลไทย (ใช้งานได้จริง — ผลวัดดู docs/handoff/PHASE-4.md)

> แอปไม่เล่นเสียง → AI โหลดเสียงของคลิปมาวิเคราะห์เบื้องหลังเอง (yt-dlp → ไฟล์ชั่วคราว `cache/analysis/<id>/` ลบหลังเสร็จ) · ทุกอย่างล้มเหลวได้เงียบๆ หน้าจอยังมีเวลาจากแหล่ง/ประมาณ (ข้อ 11.2)

### ภาพรวม
```
เนื้อเพลงสุดท้ายพร้อม (controller._emit_lyrics → _align_hook)
  ├─ LyricsAligner.start (process หลัก, asyncio) ── DB ai_results(kind='align', lyrics_key=hash ข้อความ) มีผล? → ใช้ทันที
  │     └ ไม่มี: รอ AiClient.available → (transcript ใน cache/stems/<id>/ ใช้ได้? ไม่ต้องโหลดเสียง) หรือ fetch_and_download → submit_align
  ├─ AiClient (thread ฟัง + watchdog) ── multiprocessing Queue ──▶ AI worker (spawn, BELOW_NORMAL, ต่อ site_dir เข้า sys.path)
  │     worker.job_align_song: ffmpeg decode 44.1k → ทีละช่วง 30 วิ (+บริบท 3 วิ) เริ่มจากช่วงที่กำลังฟัง:
  │        Demucs htdemucs (autocast fp16) → เสียงร้อง → 16k mono → faster-whisper large-v3-turbo (คำ+เวลา)
  │        → pipeline/match.py จับคู่ตัวอักษรเนื้อเพลง↔transcript (SequenceMatcher) → เวลาจริงทุกบรรทัด
  │        → pipeline/align.py (MMS_FA + uroman) เกลาเวลาคำของบรรทัดที่จับคู่ได้ (conf < 0.45 = ไม่เชื่อ)
  │        → ส่ง result kind=align_partial ทุกช่วง · align_final ตอนจบ (+ช่วงเสียงร้อง, coverage, version_mismatch)
  │        เก็บ cache: transcript.json (คำ+เวลา+ช่วงเสียงร้อง) + vocals16k.npy — สลับเนื้อเพลง/เปิดซ้ำไม่ต้องใช้ GPU
  └─ handler (thread ของ AiClient) → apply_result → EventBus LYRICS_RETIMED {lyrics, source_label, final, coverage, gaps}
        → UI: LyricsModel.retime (แก้ในที่ ไม่รีเซ็ตการเลื่อน/คำแปล) + ช่วงดนตรีจากเสียงร้องจริง (gapAfter/gapStart + edgeGaps อินโทร/เอาท์โทร)
ไม่มีเนื้อเพลงเลย → งานเดียวกันแต่ lines=[] → worker ถอดเสียงเป็นบรรทัด (group_words_into_lines) → Lyrics(ai_transcribed=True) ป้าย "ถอดเสียงโดย AI"
เนื้อเพลงจับคู่กับเสียงได้ < min_coverage (0.25) → version_mismatch: ไม่แตะเวลาเดิม · ป้ายบอก · controller.on_align_mismatch ลองเนื้อเพลงตัวถัดไป (≤3 ครั้ง/เพลง)
**โครงสร้างต่างจากเนื้อเพลง (รีมิกซ์ ฯลฯ)**: จับคู่แบบเรียงลำดับได้ < 50% และ transcript น่าเชื่อถือ (`transcript_reliable`) → ลอง `reconstruct_by_transcript`: สร้างบรรทัดตาม "ลำดับที่ร้องจริง" จาก transcript แล้วแทนข้อความด้วยบรรทัดเนื้อเพลงที่คล้ายพอ (≥0.62) · ใช้เมื่อได้ข้อความตรงเนื้อเพลงเพิ่ม ≥ 8 จุด% (`reconstruct_gain`) หรือเนื้อเพลงแทบไม่ตรงเลย (< `min_coverage`) → mode `reconstruct` → `lyrics_from_reconstruct` (ป้าย "จัดตามเสียงจริง", `restructured=True` → controller.on_lyrics_retimed ส่งแปลชุดใหม่)
ข้อควรระวัง: เสียงร้องไทยของ Whisper ได้เป็นชิ้นย่อย → `regroup_tokens` + pythainlp รวมเป็นคำจริงก่อนแสดง · Whisper มั่ว "yeah yeah…" วนซ้ำตอนดนตรีล้วน → `clean_transcript` ตัดก่อนจับคู่ · บรรทัดที่เลื่อนผิดแปลกจากเพื่อนบ้านที่ตรงกันเอง ถูกตัดทิ้ง (`_reject_outliers`) · cudnn.benchmark ต้องปิด (ความยาวอินพุตไม่คงที่ ช้าลง 10 เท่า)
แปลไทย: LyricsTranslator → worker job translate (**NLLB-200 distilled 1.3B แบบ CTranslate2 int8** 1.4 GB ผ่าน ctranslate2+sentencepiece ไม่ใช้ transformers · ซ้ำ=แปลครั้งเดียว) → TRANSLATION_READY → LyricsModel.set_translations · คุณภาพ: อ่านรู้เรื่องแต่ยังไม่ "สวย" (เช่น Milky Way → "ทางดวงนม") — ทางอัปเกรด = LLM ในเครื่อง (ต้องพื้นที่ดิสก์ ≥ 5 GB และ VRAM แบ่งกับ Whisper)
```

### ไฟล์
| ไฟล์ | หน้าที่ |
| --- | --- |
| `app/ai/client.py` | `AiClient`: spawn/ฟัง/watchdog (heartbeat), `submit_align/submit_translate`, `cancel_video` (ตาม job_id), restart + ส่งงานซ้ำ ≤2 ครั้ง · `ai_libs_present` ตรวจ torch/whisper/demucs โดยไม่ import |
| `app/ai/worker.py` | `Worker`: โหลดโมเดลค้าง (demucs/whisper/MMS), `job_align_song`, ยกเลิกระหว่างช่วง, heartbeat, degraded |
| `app/ai/aligner.py` | `LyricsAligner` + ฟังก์ชันล้วน `lyrics_key / lyrics_to_input / apply_result / lyrics_from_transcript / gaps_from_vocals` |
| `app/ai/translator.py`, `translate_job.py` | แปลไทย (ฝั่งหลัก / ฝั่ง worker, NLLB ct2 int8) · `plan()` กำจัดบรรทัดซ้ำ |
| `app/ai/cache.py` | ไฟล์ cache ต่อเพลง (กุญแจ = algo_version+โมเดล) + จำกัดจำนวนเพลง |
| `app/ai/env.py` | ต่อ `models.yaml: site_dir` (ต่อท้าย sys.path) + `model_dir` (HF_HOME/TORCH_HOME) |
| `app/ai/gpu.py` | `query_gpu()` ด้วย pynvml |
| `app/ai/pipeline/match.py` | **หัวใจ**: จับคู่เนื้อเพลง↔transcript ระดับตัวอักษร (ไม่พึ่ง torch ทดสอบได้) · บรรทัดที่ไม่จับคู่ = ยืด/เลื่อนเวลาเดิมตามจุดยึด |
| `app/ai/pipeline/{stems,transcribe,align,audio,vocal_activity}.py` | Demucs · faster-whisper · MMS_FA · ffmpeg decode · ช่วงเสียงร้อง/ช่วงดนตรี |
| `scripts/ai_eval.py <videoId>` | ทดสอบ pipeline กับคลิปจริงโดยไม่เปิดโปรแกรม (พิมพ์ coverage/offset/ตารางเวลา + "ความตรงกับเสียงร้องจริง" = สัดส่วนเวลาบรรทัดที่อยู่ในช่วงมีเสียงร้อง) |
| `scripts/ai_e2e.py <videoId> [--translate]` | ทดสอบครบวงจร: AiClient (worker process จริง) + LyricsAligner + translator + EventBus |

### การตั้งค่า/ที่เก็บ
- `models.yaml`: `site_dir` (เครื่องนี้ `%LOCALAPPDATA%/SyncLyrics/ai/site` — D: เป็น USB ช้า ใช้ไม่ได้ ดู DECISIONS) · `model_dir` · `analysis.{window_s,context_s,min_coverage,algo_version}` · `translate.*` · `whisper.keep_loaded=true`
- DB: ตาราง `ai_results(video_id, kind, lyrics_key, version, payload)` (migration ท้ายสุด) · ผลผูกกับ "ข้อความเนื้อเพลง" ไม่ใช่เวลา → เนื้อเพลงเดิมจากแหล่งเดิมใช้ผลซ้ำได้
- เปลี่ยนวิธีจัดเวลา → เพิ่ม `analysis.algo_version` (ผลเก่าหมดอายุเอง)
