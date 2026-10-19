# Handoff — เฟส 1: เล่นเสียงจาก YouTube + หาเนื้อเพลง + ทีละคำแบบประมาณ
2026-10-20 · Sonnet 5.5 (ผู้ใช้ไม่ได้ยืนยันระดับการคิด; ผมไม่รู้ระดับการคิดของเซสชัน) · ใช้ subagent ขนาน 2 ตัว (เสียง, UI) ตามที่ผู้ใช้ขอ

## สรุปสั้น (5 บรรทัด)
1. โปรแกรมเปิดได้ (`scripts\run_app.bat`) วางลิงก์ YouTube → เสียงออก ~2.7 วิ + เนื้อเพลง + ปก + ชื่อเพลง (ผู้ใช้ทดสอบแล้ว)
2. เนื้อเพลงค้น 5 แหล่งพร้อมกัน ให้คะแนน เลือกอัตโนมัติ กด "ผลถัดไป" ได้ ประมาณเวลาทีละคำจากเวลาบรรทัด
3. ผู้ใช้ทดสอบแล้วเจอปัญหา → แก้แล้ว: ปกไม่ขึ้น, เนื้อเพลงซ้อนกัน, เครดิตโผล่เป็นเนื้อเพลง, 403, ไม่มีปุ่มเสียง, ปกไม่ใช่ปกทางการ, ชื่อเพลง/ศิลปินสลับ
4. **ยังเหลือ:** เวลาเนื้อเพลง MV/รีมิกซ์เลื่อน (ต้องใช้ AI ฟังเสียง = เฟส 4), "เสียงหายกลางเพลง" และ "กรอไม่ได้" (จำลองซ้ำไม่ได้)
5. **ผู้ใช้เปลี่ยนทิศทาง:** ระบบก่อนความสวย · เล่นจาก YouTube แล้วลิงก์เข้าแอป (ส่วนขยาย) · เนื้อเพลงต้องผ่านการวิเคราะห์เสียงก่อนเชื่อ → ลำดับเฟสใหม่ **2 → 4 → 3 → 5 → 6 → 7 → 8** (ดู DECISIONS)

## สิ่งที่สร้างเสร็จ (ทีละฟีเจอร์ + สถานะ)
| ฟีเจอร์ | สถานะ |
| --- | --- |
| โหลดเสียงจาก YouTube (yt-dlp, extract ครั้งเดียว, ลด cookies chrome→file→none, retry 403 สามแบบ) | ใช้ได้ · cookies Chrome ใช้ไม่ได้ตอน Chrome เปิดอยู่ (ตกไปโหมด none) — ผู้ใช้ยังไม่ได้รัน `check_cookies.bat` |
| ถอดรหัส ffmpeg → `.f32` memmap ทยอย + cache เสียง (LRU, ล้างได้) | ใช้ได้ |
| Audio engine deck เดียว (WASAPI, limiter, seek/pause fade, นาฬิกา seqlock, buffer 30ms, watchdog ตรวจ stream ค้าง) | ใช้ได้ (วัดเล่นเต็มเพลง 3.5 นาที ไม่มี underrun) · ยังไม่มี 2 deck/EQ (เฟส 5-6) |
| เนื้อเพลง: lrclib, netease (YRC ทีละคำ+คำแปล), qqmusic (LRC บรรทัด), lyrics_ovh, youtube_subs (หลายภาษา) | ใช้ได้ · QRC ทีละคำของ QQ ถอดรหัสไม่ได้ |
| แยกชื่อเพลง (Music section > yt-dlp > Topic > ชื่อวิดีโอ; รูปแบบ `ศิลปิน 'เพลง'`; สลับลำดับตามผลเนื้อเพลง) | ใช้ได้ (กรณีทดสอบใน `tests/fixtures/titles.json`) |
| ให้คะแนนเนื้อเพลง (ชื่อ/ศิลปิน/ความยาว/เวลา/เวอร์ชัน, TITLE_GATE, โทษแบบนุ่มเมื่อความยาวต่าง) | ใช้ได้ แต่เป็นแค่ฮิวริสติก — **ไม่ได้ตรวจกับเสียงจริง** |
| เวลาแบบประมาณทีละคำ + กรองบรรทัดเครดิต | ใช้ได้ |
| ปก: ต้นฉบับ=iTunes (TH→US, ไม่ใช้ความยาวตัดสิน) · remix/เวอร์ชันอื่น/ไม่เจอ=ปกคลิป | ใช้ได้ |
| PlayerController (deck เดียว, offset ต่อเพลง, กู้/บันทึกสถานะ, หยุด/กรอ/เสียง) | ใช้ได้ |
| UI QML: ปก, ชื่อ, progress+seek, ปุ่มเล่น, แถบเสียง, ช่องวางลิงก์, เนื้อเพลงเติมสีทีละคำ, คลิกบรรทัดเพื่อ seek, ปุ่มผลถัดไป, คีย์ลัด Space/←/→/[/]/Ctrl+V | ใช้ได้ · มุมปกยังไม่โค้ง (layer.effect ไม่ทำงาน) |
| single instance + `BridgeServer` (QLocalServer) | ใช้ได้ส่วน focus · โปรโตคอลส่วนขยายเป็นเฟส 2 |
| เพลงถัดไป/ก่อนหน้า, คิว, preload, AI, AutoMix, ส่วนขยาย, ธีม/shader, ตั้งค่า | ยังไม่ได้ (เฟสหลัง) |

## ไฟล์ที่สร้างหรือแก้ (path + หน้าที่ + จุดสำคัญ)
ดูตารางละเอียดใน `ARCHITECTURE.md` §12 (ตรงกับโค้ดแล้ว) จุดที่ควรรู้เพิ่ม:
- `app/main.py` — ประกอบทุกอย่าง `UiContext.on_started(raise_window)` ถูกเรียกใน UI thread หลัง QML โหลด (เปิด bridge, กู้สถานะ, แจ้ง error เสียง)
- `app/player/controller.py` — `_play_async` (ไหลหลัก), `_side_tasks` (เนื้อเพลง → แล้วค่อยปก เพราะปกต้องใช้ชื่อที่ยืนยันแล้ว), `_ticker_loop` (เพลงจบ + บันทึกสถานะ 5 วิ)
- `app/lyrics/service.py` — `find(track, duration, extras, on_update)`, `_reconcile_meta` (สลับ เพลง/ศิลปิน), `source_label` (+คำเตือนความยาวต่าง)
- `app/audio/engine.py` — `start(open_stream=False)` สำหรับ test, `_control_loop` (ขยาย buffer เมื่อ underrun + watchdog stream ค้าง + log สถิติ)
- `app/ui/qml/LyricLine.qml` — **ห้ามผูก `y`/`x` ของลูกใน `Flow` โดยตรง** (เคยทำให้คำกระโดดไปทับแถวแรก) ใช้ Item ครอบแล้วขยับข้างใน
- `app/ui/qml/LyricsView.qml` — `cacheBuffer: 100000` เพื่อให้ `positionViewAtIndex` แม่นหลัง seek ไกล · มี `dumpLines/dumpTree` ไว้ไล่บั๊กเลย์เอาต์
- `app/ui/qml/NowPlaying.qml` — ห้ามซ่อน (visible:false) ต้นฉบับของปกแล้วใช้ MultiEffect แยก (Image ข้างในไม่โหลด)
- `scripts/run_app.bat`, `scripts/check_cookies.bat/.py`

## วิธีรันและทดสอบ (คำสั่งจริง)
```bat
cd C:\lyrics
scripts\run_tests.bat            :: 232 ข้อ
scripts\run_app.bat              :: เปิดโปรแกรม (ใส่ลิงก์ต่อท้ายได้)
scripts\check_cookies.bat        :: ตรวจ cookies Premium (ปิด Chrome ก่อน)
.venv\Scripts\python -m app.ui.demo   :: ดู UI ด้วยข้อมูลปลอม
```
สคริปต์ไล่บั๊ก UI ที่ใช้ได้ผล (อยู่ใน scratchpad ของเซสชัน ไม่ได้ commit): เปิดหน้าต่างจริง + `Main.qml: saveShot(path)` (เรียกผ่าน `QMetaObject.invokeMethod`) แล้วแคปภาพ/dump โครงสร้าง item

## ผล test
- 232 ผ่าน 0 ไม่ผ่าน (เฟส 0 มี 106) · ครอบคลุม: parser ทุกตัว, title parser 14 กรณี, scoring, estimate, service (แหล่งพัง/cache/ผลถัดไป/on_update), cache เสียง, IoThread, engine (ไม่ต้องมีลำโพง), decoder (ffmpeg จริง), controller (media ปลอม), UI (รัน Qt ใน subprocess), youtube client (retry 403), artwork policy
- ยังไม่มี test อัตโนมัติสำหรับ: การเล่นเสียงจริงผ่านลำโพงเกิน 3 นาที, การคลิก UI จริง, เครือข่ายจริง (ผมตรวจด้วยสคริปต์มือกับ 5 วิดีโอ)

## สิ่งที่ผู้ใช้ทดสอบแล้วและผลที่ได้
- เพลง: Out of Time (สากล), NewJeans Bubble Gum (k-pop), Thon remix (HgXkF7XWjNg), เกี่ยวกันไหม (kRRrsIUxPpM), สลักจิต (rPzC1o8E4t0)
- พบ: เนื้อเพลงซ้อนกัน/ไม่นุ่ม/ปกไม่ขึ้น/เสียงหายกลางเพลง/กรอไม่ได้/ไม่มีปุ่มเสียง/เวลาเนื้อเพลง MV ไม่ตรง/ปกไม่ใช่ทางการ/ชื่อเพลงสลับ → แก้แล้วทั้งหมดยกเว้นที่ระบุใน "บั๊กที่รู้"
- `check_cookies.bat` (ผู้ใช้รันแล้ว): **อ่าน cookies Chrome ไม่ได้** ("Could not copy Chrome cookie database") → แอปเล่นแบบไม่ล็อกอิน opus 136k (= ไม่ใช่คุณภาพ Premium) · ตัวตรวจเคยรายงานผิดว่า "อ่านได้" แก้แล้ว (แตะ `ydl.cookiejar` จริง) · ยังไม่มี `cookies.txt`
- ยังไม่ได้ตอบ: ผลรอบทดสอบหลังแก้ล่าสุด

## บั๊กที่รู้แต่ยังไม่แก้
1. **เสียงหายกลางเพลง (ผู้ใช้เจอ)** — จำลองซ้ำไม่ได้: เล่นเต็มเพลง 3.5 นาทีพร้อม UI ไม่มีสะดุด/ไม่มี underrun, จบแล้วหยุดถูกต้อง ครั้งหนึ่งตอนที่ผมรันสคริปต์เล่นเสียงสองตัวพร้อมกันบนอุปกรณ์เดียวกัน นาฬิกากระโดดและ callback ของอีกตัวหยุดที่ 45 ครั้ง (น่าจะเกิดจากการแย่งอุปกรณ์ ไม่ใช่บั๊กโปรแกรม) สิ่งที่ทำไว้: watchdog เปิด stream ใหม่เมื่อ callback หยุด >1.5 วิ, buffer 30ms, log "สถิติเสียง" ใน `logs/audio-*.jsonl` เมื่อ starvation/underrun/error เพิ่ม → **ถ้าเกิดอีก ขอ log นั้น + ว่าตอนนั้นทำอะไร/Chrome เล่นอะไรอยู่**
2. **กรอเพลงไม่ได้ (ผู้ใช้เจอ)** — คลิกแถบ progress ในหน้าต่างจริงด้วย QTest กรอได้ปกติ (16s→158s) ยังไม่รู้ว่าผู้ใช้กดตรงไหน (แถบ/คลิกบรรทัด/ลูกศร?)
3. เวลาเนื้อเพลงเลื่อนเมื่อวิดีโอยาวกว่าเพลง (MV ฉากเปิดเรื่อง) / รีมิกซ์ — รอเฟส 4 (ตอนนี้แค่เตือนที่ป้ายแหล่ง + ปรับมือ [ ])
4. มุมปกยังเป็นสี่เหลี่ยม (`layer.effect: MultiEffect` + mask ไม่ทำงาน) — เฟส 3
5. `youtube_subs` อาจได้คำบรรยาย*คำแปล* (ไม่ใช่ภาษาร้อง) — เรียงภาษาตามที่เดาจากชื่อวิดีโอ ผิดกด "ผลถัดไป"
6. cookies Chrome ใช้ไม่ได้ขณะ Chrome เปิด (Chrome 127+ app-bound encryption อาจใช้ไม่ได้เลย) — ต้องใช้ `cookies.txt` สำรอง ยังไม่ได้ทดสอบกับบัญชี Premium จริง (เสียงที่ได้ตอนนี้ opus ~130-136k แบบไม่ล็อกอิน)

## การตัดสินใจและเหตุผล (รวมที่ต่างจาก PROMPT.md)
ดู `docs/DECISIONS.md` (2026-10-20) สรุปที่ต่างจาก PROMPT: buffer 30ms (PROMPT 10-20ms), ฟอนต์หลัก SF Thonburi (PROMPT: Prompt ฯลฯ), โทษความยาวนุ่ม (PROMPT: ต่างเกิน 3 วิ ตัด), QQ ใช้ LRC บรรทัด, yt-dlp ต้องมี Node.js, **ลำดับเฟสเปลี่ยนเป็น 2→4→3**

## สิ่งที่ผู้ใช้บอกหรือขอระหว่างแชต (สำคัญมาก — อ่านก่อนเริ่มเฟส 2/4)
- ใช้ background/subagent กับงานที่ขนานได้ เพื่อความเร็ว
- **ฟอนต์หลัก SF Thonburi** ทั้งไทยและอังกฤษ
- **ระบบต้องดีก่อน ความสวยค่อยทีหลัง**
- **การใช้งานหลักคือกดเล่นใน YouTube แล้วลิงก์เข้าแอปเรียลไทม์ผ่านส่วนขยาย** ไม่ใช่วางลิงก์ในแอป (ช่องวางลิงก์ = ทางสำรอง) ถ้าแอปยังประมวลผลไม่เสร็จให้**หน่วง/หยุดวิดีโอใน YouTube** จนแอปพร้อม · แอปเป็นตัวแสดงเนื้อเพลง (และเล่นเสียงเอง)
- **เนื้อเพลงที่หามาได้ไม่ใช่คำตอบสุดท้าย ต้องวิเคราะห์ก่อนใช้**: AI ฟังเสียงว่าคำร้องเริ่มวินาทีไหน และเป็นเวอร์ชันไหน (official/MV/รีมิกซ์) — MV/รีมิกซ์/ที่ไม่ใช่ official audio **ยึดเสียงจริงของคลิป** (รีมิกซ์มักตัดต่อท่อน เอาท่อนฮุกขึ้นก่อน เอาท่อนร้องหลายเพลงมาผสม) ใช้ ASR ฟรี หลายภาษา · เพลงปกติ/official audio ใช้เนื้อสำเร็จรูปได้เพื่อความเร็ว แต่ต้องมีเงื่อนไขตรวจเยอะๆ กันพลาด · "ความยาวต่าง" ไม่ใช่แค่คำเตือน ต้องแก้จริงด้วยการฟัง
- ปก: ต้นฉบับ → ปกทางการ · รีมิกซ์/ไม่มีปกต้นฉบับ → ปกคลิป
- ต้องมีปุ่มเสียง (ทำแล้ว) และเพลงถัดไป/ก่อนหน้า (รอคิว เฟส 5)
- เพลงทดสอบ: สากล `2yqYAsUpdSc` · k-pop `ft70sAYrFyY` · รีมิกซ์ `HgXkF7XWjNg` · ไทย `kRRrsIUxPpM` · ไทย MV ยาวกว่าเพลง `rPzC1o8E4t0`
- คุยภาษาไทย

## สภาพแวดล้อม
- Windows 11 Pro · RTX 4060 8GB · Python 3.12.10 ใน `C:\lyrics\.venv` · PySide6 6.12.0 · yt-dlp 2026.8.19 + `yt-dlp-ejs` (ติดตั้งผ่าน `yt-dlp[default]`) · Node.js 24 ใน PATH (จำเป็นสำหรับ yt-dlp) · ffmpeg 8.1.2 ใน PATH · Chrome ผู้ใช้ล็อกอิน Premium (ยังไม่ยืนยันว่าแอปใช้ cookies ได้)
- ฟอนต์ SF Thonburi ติดตั้งในเครื่องแล้ว (Qt เห็นชื่อ "SF Thonburi")
- requirements-ai.txt (torch 2.11+cu128) **ยังไม่ได้ติดตั้ง** — เฟส 4 ต้องติดตั้ง

## กับดักที่เจอ
- bash heredoc ทำ `\\`/Thai เพี้ยน และ `python - <<EOF` ที่มี `\s` ใน string ปกติทำ regex พัง → เขียนไฟล์ด้วย Write/Edit tool หรือใช้ raw string
- Python บน Windows มองไม่เห็น `/tmp` ของ bash ใช้ scratchpad; `pkill/pgrep` ไม่มีใน Git Bash ใช้ PowerShell `Get-CimInstance Win32_Process`
- `QQuickWindow.grabWindow` เรียกจาก PySide ไม่ได้ (ได้ QWindow) ใช้ฟังก์ชัน QML `saveShot` แทน
- QML: ผูก `y`/`x` ของลูกใน Flow = ทับตำแหน่งที่ Flow จัด (ทำให้ข้อความซ้อน) · `visible:false` + `layer.enabled` ทำให้ Image ข้างในไม่โหลด · `ListView.positionViewAtIndex` ประมาณความสูงของ delegate ที่ยังไม่สร้าง
- `grep "แบบ regex ที่มี |" ` ฯลฯ ไม่เกี่ยว แต่: `python -m pytest` ที่ไม่ได้ตั้ง `PYTHONIOENCODING=utf-8` จะพิมพ์ไทยเพี้ยน
- รันสคริปต์เล่นเสียงจริงสองตัวพร้อมกันบนอุปกรณ์เดียว → ผลแปลก (อย่าทำตอนไล่บั๊กเสียง)
- yt-dlp ดึง cookies จาก Chrome ขณะ Chrome เปิดไม่ได้ ("Could not copy Chrome cookie database") → ลดไป none อัตโนมัติ
- googlevideo ตอบ 403 เป็นครั้งคราว (ไม่เกี่ยวกับ cookies) → retry อัตโนมัติ

## interface ที่เฟสถัดไปต้องใช้
- **`PlayerController`**: `play(TrackRef, start_at=0, autoplay=True)`, `play_url(text)`, `toggle_pause()`, `seek(s)`, `set_volume(v)`, `adjust_offset(delta)`, `next_lyrics_candidate()`, `restore(state)`, `snapshot()`, `start_background_tasks()`, `shutdown()`, `get_clock()`; thread ใดเรียกก็ได้ (งานจริงใน `IoThread`)
- **EventBus เพิ่ม:** `lyrics.offset {video_id, offset}`, `player.status {text}`, `bridge.message {type, payload, id, client}`; `lyrics.ready` มี `final`, `needs_ai_transcription`; `track.meta_ready` ส่ง 2 รอบ (ชื่อ แล้วปก)
- **`BridgeServer`** (`app/bridge/pipe_server.py`): รับ frame JSON → publish `bridge.message`; `send(type, payload)` ถึงส่วนขยาย; `notify_existing_instance(argv)` · ฝั่งส่วนขยายเฟส 2 ต้องทำ `bridge/host.py` + registry + `extension/` · ข้อความมีใน `app/core/messages.py` (`EXT_TO_APP`/`APP_TO_EXT`) เช่น `play_now`, `pause_tab`, `companion_state`
- **`LyricsService.find(track, duration, extras={"subtitles":...}, on_update)` → `LyricsResult(chosen, candidates, source_label, from_cache, needs_ai_transcription, meta, final)`**; `LyricsCandidate.score_detail` มี `duration_diff_s`; จุดเสียบ ASR: ตรวจ `candidate` กับเสียงก่อนเชื่อ (เฟส 4) + `TimingLevel`/`WordTimingSource.ALIGNED`
- **`UiContext(bus, get_clock, controller, settings, shutdown, on_started)`**; UI อ่านนาฬิกาผ่าน `ClockBridge.position()` ต่อเฟรม; เวลาเนื้อเพลง = เวลาเสียง − `lyricsOffset`
- **เสียง:** `AudioEngine.load(deck, video_id, full_program(buf))`, `play/pause/seek/set_master_volume/clear_deck`, `clocks[deck]`, `stats` · PCM เป็นไฟล์ `.f32` + sidecar `.meta.json` ใน `cache/audio` (AI worker เปิดไฟล์เดียวกันได้: float32 stereo, sample rate ของ engine ใน sidecar)
- **DB ที่ใช้แล้ว:** `tracks` (title/artist ที่ยืนยันแล้วไม่ถูกเขียนทับ), `audio_cache`, `lyrics`, `lyrics_choice`, `playback_state` (ยังใช้ state.json แทน), `kv` ยังไม่ใช้

## งานค้างทั้งหมดที่ผู้ใช้สั่งให้ย้ายไปทำในเฟส 2 (รายการเดียวกับ PROGRESS.md)
1. บั๊กเสียงหายกลางเพลง + กรอไม่ได้ (ไล่ต่อด้วย log `audio-*.jsonl`) 2. เสียง Premium (cookies — ข้อเสนอส่งผ่านส่วนขยาย ต้องถามผู้ใช้) 3. ปุ่มเพลงถัดไป/ก่อนหน้า + คิวขั้นต่ำ (รับจาก playlist/Up next ของส่วนขยาย; preload/คิวเต็มยังเป็นเฟส 5) 4. มุมปกโค้ง 5. การเลือกภาษาของ youtube_subs 6. health check Node.js/ffmpeg/cookies 7. ให้ผู้ใช้ทดสอบซ้ำ (สลักจิต ฯลฯ)
**ยังไม่ย้าย:** ASR/ตรวจเวอร์ชัน/แก้เวลาเนื้อเพลง MV-รีมิกซ์ = เฟส 4 (ถามผู้ใช้อีกครั้งในแชตเฟส 2 ว่าจะย้ายมาด้วยไหม — ใหญ่มาก ต้อง torch/GPU และควรใช้ Sonnet high)

## สิ่งที่เฟสถัดไปต้องรู้ก่อนเริ่ม และควรเริ่มจากตรงไหน
**ลำดับเฟสใหม่: 2 (ส่วนขยาย YouTube→แอป) → 4 (AI ฟังเสียง) → 3 (หน้าตา) → 5 → 6 → 7 → 8**
เฟส 2 (Sonnet 5.5 medium) แนะนำเริ่มจาก:
1. อ่าน PROMPT ส่วนที่ 10 + `extension/README.md` + `app/core/messages.py` + `app/bridge/pipe_server.py`
2. native host (`bridge/host.py`) + registry (`registry.py`) + manifest/service worker + content script (ปุ่มบน thumbnail, `config/selectors.json` ต้องตรวจกับหน้า YouTube จริง) + wizard ติดตั้ง
3. **flow หลักตามผู้ใช้:** content script ตรวจว่ามีวิดีโอเล่นใน YouTube → ส่ง `play_now` อัตโนมัติ (มีสวิตช์ตั้งค่า) → **หยุดวิดีโอในแท็บทันทีและค้างไว้ (`pause_tab`) จนแอปส่งสถานะ "พร้อมเล่น"** แล้วค่อยให้แอปเริ่มเล่น (แอปเล่นเสียงเอง; ไม่ใช่เสียงซ้อนกับ YouTube) · ต้องมีข้อความสถานะ `status` จากแอปเพื่อบอกส่วนขยายว่ากำลังประมวลผล/พร้อม
4. ส่ง "Music section" (song/artist/album) ไปกับ `TrackRef.music_section` — ทำให้ชื่อเพลงแม่นขึ้นมาก (title_parser ใช้เป็นอันดับแรกอยู่แล้ว)
5. **ข้อเสนอเรื่อง cookies Premium (ต้องถามผู้ใช้ก่อนทำ เพราะต่างจาก PROMPT 2.1):** yt-dlp อ่าน cookies Chrome ไม่ได้บนเครื่องผู้ใช้ (Chrome ใหม่เข้ารหัสแบบ app-bound) → ให้ส่วนขยาย (chrome.cookies API) ส่ง cookies ของ youtube.com เข้าแอปผ่าน native messaging แล้วแอปเขียน `secrets/cookies.txt` (เก็บในเครื่องเท่านั้น ห้ามใส่ log/รายงานปัญหา) แทนที่จะให้ผู้ใช้ export มือ
6. ช่องวางลิงก์ในแอป ซ่อนเป็นทางสำรอง
7. โหมดคู่หู (`RemoteClock`) ตามเดิม
เฟส 4 (Sonnet 5.5 high) — **ต้องออกแบบใหม่ตามที่ผู้ใช้สั่ง:** ASR (faster-whisper, หลายภาษา) เป็นตัวยืนยัน/จัดเวลา · ตรวจ "เวอร์ชัน" จากเสียง (official audio vs MV vs รีมิกซ์) · MV/รีมิกซ์ยึดเสียงจริง · ต้องได้เวลาแม้เนื้อเพลงสำเร็จรูปไม่ตรงเวอร์ชัน · ตัวตัดสินระดับเชื่อเนื้อเพลงสำเร็จรูป (เร็ว) กับต้องถอดเสียงเต็ม (ช้ากว่า แต่แม่น) ต้องมีเงื่อนไขกันพลาด

## คำถามที่ยังไม่ได้คำตอบจากผู้ใช้
- ผลรอบทดสอบหลังแก้ล่าสุด (ปก ชื่อเพลง เนื้อเพลงไม่ซ้อน)
- ผู้ใช้อยากได้เสียงระดับ Premium ไหม และยอมให้ส่วนขยาย export cookies ส่งเข้าแอปเองผ่าน native messaging ไหม (เสนอสำหรับเฟส 2 — ดูด้านล่าง)
- "กรอไม่ได้" ผู้ใช้กดตรงไหน / "เสียงหาย" ตอนทำอะไร (และขอ `logs\audio-*.jsonl` ถ้าเกิดอีก)

## ข้อความสำหรับวางในแชตใหม่ (copy ได้ทันที)
```
อ่าน PROMPT.md, ARCHITECTURE.md, docs/PROGRESS.md, docs/DECISIONS.md
และ docs/handoff/PHASE-1.md ให้ครบ แล้วเริ่มเฟส 2
(ลำดับเฟสใหม่ตามที่ตกลงกัน: 2 → 4 → 3 → 5 → 6 → 7 → 8)
```
