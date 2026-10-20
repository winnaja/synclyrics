# Handoff — เฟส 2: ส่วนขยาย Chrome + โหมดคู่หู + หน้าต่างเนื้อเพลงลอยตาม UX UI
2026-10-20 · Sonnet 5.5 (ผู้ใช้ไม่ได้ยืนยันระดับการคิด) · **สถานะ: โค้ดเสร็จ ผ่าน test อัตโนมัติ 296/296 + ทดสอบกับ Chrome ตัวจริงด้วยสคริปต์ — รอผู้ใช้ทดสอบเองก่อนปิดเฟส** (ต้องเติมหัวข้อ "ผู้ใช้ทดสอบแล้ว" แล้วค่อยปิด)

## สรุปสั้น (5 บรรทัด)
1. **ทิศทางเปลี่ยน (ผู้ใช้สั่ง):** แอปไม่เล่นเสียง — เล่นเพลงใน YouTube อย่างเดียว แอปคือ "Premium Desktop Lyrics Utility" ตาม `add by win/UX UI.txt` (ไม่ใช่หน้าต่างเล่นเพลง) · เฟส 5-7 (คิว/AutoMix/เรียนรู้จากดาว) ไม่มีเสียงให้ทำ → รอผู้ใช้ตัดสินใจ
2. **แก้บั๊ก "ชื่อ/ปก/เนื้อเพลงไม่ตรงกับเพลงที่เล่น":** ต้นเหตุคือส่วนขยายส่ง "videoId ใหม่ + ชื่อเพลงเก่า" (URL เปลี่ยนก่อนชื่อบนหน้า) → ตอนนี้ส่วนขยายส่งแค่ videoId + เวลา แอปยืนยันชื่อ/ปกจาก YouTube เอง · ทดสอบกับ Chrome จริง: เปลี่ยนเพลงแล้วแอปตามใน ~4 วิ ตรงกับ URL
3. UI ใหม่ทั้งหมดตาม UX UI: หน้าต่างลอย Minimal/Focus/Full, ตั้งค่า 5 หมวดเห็นผลทันที, tray, คีย์ลัดทั้งระบบ, ธีม 5 แบบ, เปิดพร้อม Windows
4. ค้าง: **เวลาเนื้อเพลงของ MV/คลิปที่ไม่ใช่ official ไม่ตรงเสียง = เฟส 4 (ผู้ใช้สั่งซ้ำ 2 ครั้ง ห้ามหล่น)** · ผู้ใช้ยังไม่ได้ทดสอบรุ่นนี้
5. ข้อค้นพบ: เสียงที่ yt-dlp ดึงได้ opus ~137k เท่ากันทั้งมีและไม่มี cookies · ใน Chrome ที่ไม่ใช่ Premium มีโฆษณา → ส่วนขยายรายงานว่า "หยุด" ระหว่างโฆษณา

## สิ่งที่สร้างเสร็จ
| ฟีเจอร์ | สถานะ |
| --- | --- |
| ส่วนขยาย MV3 ใหม่ (`content.js` รายงาน videoId+เวลาทุก 250ms, จับกรอ/หยุด/เล่น/เปลี่ยนเพลง/โฆษณา, รับ tab_control; `background.js` เลือกแท็บที่กำลังเล่น, กดไอคอน=เปิดหน้าต่าง, เมนูคลิกขวา) | ใช้ได้ (e2e กับ Chrome จริงผ่านส่วนใหญ่ — ดูหัวข้อผลทดสอบ) |
| native host `HostBridge` (รอ pipe ไม่เปิดแอปเอง, `launch_app`, `SYNCLYRICS_PIPE` สำหรับ test) + registry + installer (`ติดตั้งส่วนขยาย`, `scripts\install_extension.bat`) | ใช้ได้ |
| `BridgeService` + `PlayerController` โหมด companion: ยืนยันเพลงจาก videoId (oEmbed + yt-dlp), เคลียร์หน้าจอตอนเปลี่ยนเพลง, จับเพลงใหม่จาก `companion_state`, `RemoteClock`, `tab_control` | ใช้ได้ |
| ล้างแคชเนื้อเพลง/ชื่อที่บันทึกผิดครั้งเดียว (`db.purge_stale_companion_cache`) | ใช้ได้ |
| หน้าต่างเนื้อเพลงลอย `Overlay.qml`: frameless/Tool/always-on-top, 3 โหมด (ขนาดแยกต่อโหมด), พื้นหลัง 5 แบบ (โปร่งใสแยกจากตัวอักษร), แถบควบคุมตอนชี้เมาส์, ปรับขนาดที่ขอบ, ล็อก, click-through (+ข้อความบอกวิธีปิด), จำตำแหน่ง/ขนาด, กันหลุดจอ, ตำแหน่งสำเร็จรูป | ใช้ได้ (ตรวจด้วยภาพจริงของหน้าต่าง) · **ยังไม่ได้ทดสอบกับหลายจอ/DPI 125-150%/คีย์ลัดจริงบนเดสก์ท็อปของผู้ใช้** |
| `LyricsView/LyricLine`: ไฮไลต์ 4 แบบ, แอนิเมชัน 4 แบบ, ลดการเคลื่อนไหว, ข้อความสถานะ (รอเชื่อมต่อ/กำลังค้นหา/ไม่พบ), คำแปลใต้บรรทัด | ใช้ได้ |
| `FullPanel.qml` (โหมด full): ปก ครอปเต็มช่องมุมโค้ง, ชื่อ, ศิลปิน, แถบเวลา (กรอที่ YouTube), ◀◀ ❚❚ ▶▶ | ใช้ได้ |
| `SettingsWindow.qml` 5 หมวด + `settings_store/settings_bridge/themes` + บันทึก settings.yaml debounce | ใช้ได้ |
| tray (`Tray.qml`), คีย์ลัดทั้งระบบ (`hotkeys.py`), เปิดพร้อม Windows (`startup.py`) | ใช้ได้ในโค้ด/test · **ผู้ใช้ยังไม่ได้ลอง** |
| health check (Node/cookies/ส่วนขยาย; ffmpeg/เสียงเฉพาะ app_audio) | ใช้ได้ |
| ปก: ตัดขอบดำ thumbnail, มุมโค้ง · youtube_subs ไม่ส่งคำแปลแทนเนื้อร้อง · ปุ่มเปิด/ปิดคำแปล (ซ่อนที่ไม่ใช่ไทย) | ใช้ได้ |
| โหมดแอป (เล่นเสียงเอง: engine/decoder/คิว/`controller.play`) | **ปิดอยู่** (`app_audio=False`) โค้ดเก็บไว้ + test ยังรัน |
| ไม่ได้ทำ (P2 ในไฟล์ UX UI → เฟส 3): blur จริงหลังหน้าต่าง, snap ขอบจอ, ตำแหน่งแยกต่อจอ, ธีม export/import, เนื้อเพลงไม่มีเวลา, ค้นเนื้อเพลงเอง | — |

## ไฟล์ที่สร้างหรือแก้ (ย่อ — ดู ARCHITECTURE §13)
ใหม่: `app/bridge/{service,installer}.py`, `app/core/health.py`, `app/ui/{settings_store,settings_bridge,themes,hotkeys,startup}.py`, `app/ui/qml/{Overlay,FullPanel,SettingsWindow,Tray}.qml`, `app/ui/assets/tray.png`, `app/ui/shaders/rounded_image.frag(.qsb)`, `extension/{manifest.json,background.js,content.js,icons/*}`, `scripts/{synclyrics-host.bat,install_extension.bat,gen_extension_icons.py}`, `tests/{test_bridge,test_phase2,test_settings_store,test_hotkeys_startup,test_extension_js}.py`, `tests/js/background.test.js`, `tests/e2e/{chrome_e2e.js,README.md}`
แก้: `app/bridge/{host,registry,pipe_server}.py`, `app/player/{controller,queue}.py`, `app/core/{config,db,events,messages}.py`, `app/main.py`, `app/ui/app_window.py`, `app/ui/qml/{Main,LyricsView,LyricLine}.qml`, `app/media/{artwork,youtube}.py`, `app/lyrics/sources/youtube_subs.py`, `config/{selectors.json,settings.yaml}`, `requirements.txt` (+pillow), `PROMPT.md` (+ข้อ 0.3.1), เอกสาร
ลบ: `app/ui/qml/NowPlaying.qml` (แทนด้วย FullPanel), `extension/{content.css,selectors.json}`
จุดสำคัญ: `controller._resolve_companion_track` / `_companion_async` / `companion_state` (จับเพลงใหม่เอง) · `extension/content.js` → `report()`, `adShowing()` · `extension/background.js` → `accept()` (เลือกแท็บต้นทาง) · `Overlay.qml` → `applyModeSize/ensureVisible/placePreset` · `settings_store.SettingsStore.set` (ธีมเปลี่ยนตาม)

## วิธีรันและทดสอบ
```bat
cd C:\lyrics
scripts\run_tests.bat                       :: 306 ข้อ (ต้องมี ffmpeg + Node)
scripts\run_app.bat                         :: เปิดแอป (= python -m app)
scripts\install_extension.bat               :: คัดลอกส่วนขยาย + ลงทะเบียน host (หรือปุ่ม "ติดตั้งส่วนขยาย")
node tests\e2e\chrome_e2e.js                :: ทดสอบกับ Chrome ตัวจริง (headless, ใช้อินเทอร์เน็ต, ไม่ชนแอปที่เปิดอยู่)
.venv\Scripts\python -m app.ui.demo         :: (เดิม) ดู UI ข้อมูลปลอม — ยังไม่ได้อัปเดตให้เข้ากับ UI ใหม่
```
ถ่ายภาพหน้าต่างจริงเพื่อไล่บั๊กหน้าตา: สร้าง `create_ui(UiContext(...))` ด้วย `QT_QPA_PLATFORM=windows` แล้วใช้ `QScreen.grabWindow(window.winId())` (เชื่อถือได้กว่า `grabToImage` ที่ทำสีเพี้ยน)

## อัปเดตรอบหลัง (ผู้ใช้ส่งภาพ Apple Music + ขอโหมดเต็มจอ/แอนิเมชันปรับแต่งได้/อ่าน UX UI ซ้ำ)
- **โหมดเต็มแบบ Apple Music = `FullWindow.qml` (หน้าต่างแยก)** ไม่ใช่โหมด full ของหน้าต่างลอยอีกแล้ว (ค่าเก่าแปลงเป็น focus) · ปุ่ม "เต็มจอ" ที่แถบควบคุม/tray/คีย์ลัด `Ctrl+Alt+F` · พื้นหลัง fluid shader สีจากปก (`artwork.dominant_colors` → `player.palette`)
- **ปกบีบ (บั๊กที่ผมสร้างเอง) แก้แล้ว:** ShaderEffect ไม่ครอปตาม fillMode → ครอปใน `rounded_image.frag` (`imgSize`) · ตัดปกจัตุรัสออกจาก thumbnail แบบ Topic (`find_art_square`)
- **แอนิเมชันเนื้อเพลงปรับแต่งได้:** `anim_presets.py` ชุดสำเร็จรูป 5 + ตัวปรับละเอียด (ความเร็ว, ความแรง, สปริง, คลื่น, เบลอ, ความจาง, ขนาดบรรทัดอื่น, การลอยของคำ, น้ำหนัก) · ค่าเริ่มต้น = นุ่มนวลแบบ Apple
- **ปิดช่องว่างเทียบ UX UI:** ดู DECISIONS "อ่าน UX UI.txt ซ้ำละเอียด" · มีเบลอฉากหลังจริง (`winfx.py`)
- **ไฟล์ใหม่รอบนี้:** `app/ui/{anim_presets,winfx}.py`, `app/ui/qml/FullWindow.qml`, `app/ui/shaders/fluid.frag(.qsb)` · แก้ใหญ่: `LyricLine/LyricsView/FullPanel/Overlay/SettingsWindow/Main/Tray.qml`, `rounded_image.frag`, `artwork.py`, `config.py` (`OverlaySettings` +ตัวแอนิเมชัน, `FullWindowSettings`), `settings_store.py` (ชุดแอนิเมชัน), `controller.py` (`search_lyrics`, ถ่ายทอดสด=ไม่รองรับ)
- test เพิ่ม: ตรวจปกจัตุรัส/สีเด่น (รวมปกขาวดำ), ชุดแอนิเมชัน, FullWindow/fullscreen/palette ใน UI smoke, winfx · ทั้งชุด 306 ผ่าน
- กับดักใหม่: `ShaderEffect` ใช้ texture ทั้งรูปของ Image เสมอ (ไม่สน fillMode) · QML `onVisibilityChanged` อ้าง `visibility` ตรงๆ ในรุ่นใหม่ถูกเตือน (ใช้ `win.visibility`) · `SetWindowRgn` อย่างเดียวไม่ตัดส่วนที่เบลอบน Windows 11 (ใช้ DWM corner preference) · `Behavior` + `SequentialAnimation{PauseAnimation}` ใช้ทำคลื่นหน่วงได้ · จับภาพหน้าต่างด้วย `QScreen.grabWindow` จะติดหน้าต่างอื่นของผู้ใช้ (แอปที่เปิดอยู่) — เรนเดอร์เนื้อหาด้วย `saveShot` (grabToImage) แล้วตรวจสีกับ grabWindow เป็นรอบสอง

## อัปเดตรอบ UI ครั้งที่ 3 (หลังผู้ใช้ทดสอบจริงบางส่วน)
- โหมดเต็ม: เวทีกึ่งกลาง · ปุ่มไอคอนเวกเตอร์ · วอลลุ่ม (สั่งผ่านตัวเล่น YouTube ด้วย `extension/page.js` world MAIN) · ซ่อนเนื้อเพลงดูแต่ปก · แถบบนแยก · ซ่อนปุ่ม/ป้ายเมื่อเมาส์นิ่ง · ขอบบน/ล่างจาง+เบลอรายบรรทัด · ความจาง/เบลอบรรทัดที่ไม่ได้ร้อง (แยกจากหน้าต่างลอย) · เปิดมาโหมดเต็ม+ขยายเต็มจอ (maximize)
- หน้าตั้งค่าเขียนใหม่ 9 หมวด (ค้นหา, ตัวอย่างสดตรึงบนสุด, โหมดละเอียด, คืนค่าต่อหมวด `settingsBridge.resetPage`) · แอนิเมชันคำ 6 แบบ+จังหวะ+ค้าง/คืนช้า+สีแสง+คำเน้น · จับท่อนเดียวกัน (`group_rows`, ท่อนละ ≤3 บรรทัด) · จัดท่อนให้อยู่กลางจอ · palette ไม่หมุนเฉดสี
- ผู้ใช้ยืนยัน: กรอ/เล่น-หยุดใช้ได้จริง · วอลลุ่มเดิมใช้ไม่ได้ (แก้แล้ว รอยืนยัน)
- ดูใบสั่งงานเฟส 4: `docs/handoff/PHASE-4-START.md`

## ผล test
- pytest 296 ผ่าน 0 ไม่ผ่าน (รวม UI smoke ทุกโหมด/ธีม/ไฮไลต์/แอนิเมชันไม่มีคำเตือน QML, Node test ของ background.js 12 ข้อ, host/pipe ด้วย os.pipe, คีย์ลัดจริงผ่าน RegisterHotKey, registry ด้วย key ทดสอบ)
- **e2e กับ Chrome ตัวจริง (โปรไฟล์ไม่ใช่ Premium มีโฆษณา):** ผ่าน: โหลดส่วนขยายจริง (`Extensions.loadUnpacked`), service worker ทำงาน, เปิดเพลง → แอปได้ videoId+ชื่อถูกต้อง ~5.6 วิ, **เปลี่ยนเพลงใน YouTube (SPA) → แอปเปลี่ยนตามพร้อมชื่อใหม่ ~3.9 วิ ตรงกับ URL**, ระหว่างโฆษณาแอปรายงานว่าหยุด, หยุด/เล่นตามกัน, `command play_pause` จากแอปสั่งวิดีโอได้ · **ยืนยันกับ Chrome จริงไม่ได้:** กรอเวลา และ `command seek` (โฆษณาต่อกัน 2 ตัวในโปรไฟล์ทดสอบ) — ตรวจด้วย test หน่วยแล้ว (service seek, RemoteClock) · **ยังไม่ได้ทดสอบ:** Chrome ที่ล็อกอิน Premium (ไม่มีโฆษณา) ซึ่งเป็นกรณีจริงของผู้ใช้
- ไม่มี test อัตโนมัติ: `content.js` แยกเดี่ยว (ทดสอบผ่าน e2e), แอนิเมชันจริงบนจอ, หลายจอ/DPI, hotkey ชนกับโปรแกรมอื่น

## สิ่งที่ผู้ใช้ทดสอบแล้วและผลที่ได้
- รอบแรก (รุ่นก่อนเปลี่ยนทิศทาง): ติดตั้งส่วนขยายสำเร็จ (จุดเขียว "เชื่อมแล้ว") · พบ: ปุ่ม "เปิดในแอป" ไม่ขึ้น · ชื่อ/ปก/เนื้อเพลงไม่ตรงกับเพลงที่เล่นใน YouTube (แก้แล้ว) · วิธีใช้แปลก (ควรกดแล้วขึ้นเลย ไม่ต้องมีโหมดแอป) · ไม่ต้องมีปุ่มเล่นเลย/เข้าคิว (ตามคิว YouTube) · เนื้อเพลง MV เวลาไม่ตรง (เฟส 4) · ปกขอบดำ (แก้แล้ว) · คำแปลจีน (ซ่อน/ปุ่ม)
- **รุ่นนี้ผู้ใช้ยังไม่ได้ทดสอบ — ต้องเติมตรงนี้ก่อนปิดเฟส**

## บั๊ก/ข้อจำกัดที่รู้แต่ยังไม่แก้
1. **เวลาเนื้อเพลงของ MV/คลิปที่ไม่ใช่ official ไม่ตรงเสียงจริง + ไฮไลต์ทีละคำไม่ตรง** — เฟส 4 (เคส `kRRrsIUxPpM`, `rPzC1o8E4t0`) ผู้ใช้สั่งซ้ำ 2 ครั้ง
2. กรอเวลา/seek ยังไม่ยืนยันกับ Chrome จริง (ดูผล e2e)
3. แอปที่ผู้ใช้เปิดค้างอยู่เป็นรุ่นเก่า (ไม่มี tray) — ต้องปิดก่อนเปิดรุ่นใหม่ (เปิดซ้ำแล้วแค่ส่ง focus ให้ตัวเก่า) และส่วนขยายใน Chrome ต้องกดรีโหลดหลังคัดลอกไฟล์ใหม่ (คัดลอกให้แล้ว)
4. `app/ui/demo.py` และ `build_look` ยังอ้าง UI เก่า (ไม่ได้ใช้แล้ว) — ลบ/ปรับในเฟส 3
5. กระจกฝ้าไม่ใช่ blur จริง · ไม่มี snap ขอบจอ · ยังไม่ทดสอบ DPI/หลายจอ
6. yt-dlp ลอง cookies จาก Chrome ช้า ~1.5 วิ (แก้ให้ลอง cookies.txt ก่อนถ้ามีไฟล์) · cookies จาก Chrome ใช้ไม่ได้บนเครื่องนี้
7. โฆษณา: ส่วนขยายรายงานหยุดระหว่างโฆษณา (ตรวจจาก `#movie_player.ad-showing`) — selector นี้เป็นของ YouTube อาจเปลี่ยน (ถ้าเปลี่ยน เนื้อเพลงจะเดินตามเวลาโฆษณา)

## การตัดสินใจและเหตุผล
ดู DECISIONS.md (2026-10-20): **เปลี่ยนทิศทางเป็นแอปไม่เล่นเสียง** · ไม่เชื่อชื่อเพลงจากหน้าเว็บ · host ไม่เปิดแอปเอง (ต่างจาก PROMPT 10.1) · UI ไม่มีหน้าต่างหลัก (หน้าต่างลอย+ตั้งค่า+tray, ผ่าน `cfg`) · เสียง 137k เท่ากัน · มุมปก ShaderEffect · คำบรรยายคำแปล

## สิ่งที่ผู้ใช้บอกหรือขอระหว่างแชต (สำคัญ — อ่านก่อนเริ่มเฟสถัดไป)
- **แอปไม่เล่นเสียง เล่นใน YouTube อย่างเดียว; ไม่ต้องมีโหมดแอป; โหมดคู่หูเป็นหลัก; ตามคิวของ YouTube (ไม่มีเล่นเลย/เข้าคิว); ซิงก์เรียลไทม์; ทำตาม UX UI เหมือน Apple Music เป็นหลัก; "ไม่ใช่แสดงเนื้อเพลงอย่างเดียวแบบเรียบๆ ทำให้เหมือนในไฟล์"**
- **เนื้อเพลงที่ไม่ตรงเสียง (MV/คลิปที่ไม่ใช่ official): ให้ใช้ระบบฟังเสียง (โมเดลฟรีตัวไหนก็ได้) แทนการคัดลอกเนื้อสำเร็จรูป — สั่งซ้ำ 2 ครั้ง** · คาราโอเกะทีละคำต้องตรงคำร้อง
- **คำแปลภาษาไทย ใช้โมเดลที่แปลสวย บริบทดี** (อ่านจีนไม่ออก) · ปุ่มปิดคำแปลได้
- ปกต้อง crop เต็มช่อง ไม่บีบ/ไม่มีขอบดำ
- **กฎการจัดการปัญหา** (PROMPT 0.3.1 + memory): เฟสนี้ = แก้เลย · เฟสถัดไป = ยัดไว้ใน PROGRESS · เฟสก่อนหน้า = ทำงานเฟสตัวเองให้เสร็จก่อน
- ใช้ cookies.txt ที่ export เอง · ฟอนต์ SF Thonburi · คุยภาษาไทย · ระบบก่อนความสวย (แต่รอบนี้สั่งให้ทำ UX UI ตามไฟล์เป็นหลัก)

## สภาพแวดล้อม
Windows 11 · RTX 4060 · Python 3.12.10 `.venv` · PySide6 6.12.0 · yt-dlp 2026.8.19 + yt-dlp-ejs · Node 24.18 · ffmpeg 8.1.2 · Pillow 13.0.0 · Chrome 155.0.8059.40 (ผู้ใช้ล็อกอิน Premium) · ฟอนต์ SF Thonburi · torch ยังไม่ติดตั้ง (เฟส 4)
extension ID `jjafolpgjdghgjadopngdolglpllbhod` · `extension/key.pem` (ไม่ commit — **สำรองไว้ที่อื่น**)

## กับดักที่เจอ
- จุดเข้าแอปคือ `python -m app` ไม่ใช่ `-m app.main`
- host ที่เปิดแอปเองทุกครั้งที่ต่อไม่ได้ทำให้ผู้ใช้ปิดแอปไม่ได้ → เปิดเฉพาะเมื่อ `launch_app`
- named pipe ของ Windows แบบ synchronous: อ่านค้าง = เขียนไม่ได้ → PeekNamedPipe
- **Qt 6 `quit()` ให้หน้าต่างปฏิเสธการปิดได้ → หน้าต่างที่ซ่อนลงถาด (onClosing ปฏิเสธ) ทำให้ออกจากโปรแกรมค้าง** → `settingsBridge.quitting`
- **YouTube เปลี่ยน URL (videoId) ก่อนที่ชื่อบนหน้าจะเปลี่ยน** → ห้ามเชื่อชื่อจาก DOM; แคชตาม videoId จึงเสียถาวรถ้าเชื่อผิด
- Chrome 137+ ไม่รับ `--load-extension` → ใช้ `--remote-debugging-pipe --enable-unsafe-extension-debugging` + CDP `Extensions.loadUnpacked`
- `grabToImage` ทำสี/สไลเดอร์เพี้ยน (เช่น `#fff` ย่อ) → ใช้ `QScreen.grabWindow` ถ่ายหน้าต่างจริง · ใช้ `#RRGGBB` เต็มเสมอ
- `QQmlPropertyMap`: QML เขียนแล้ว emit `valueChanged`, Python `insert` ไม่ emit (ต้องกันวนซ้ำด้วยธง `_pushing`)
- **bash tool ในเซสชันนี้: heredoc ที่มี `'`/ภาษาไทยพัง และ `\\n` ในสคริปต์ที่เขียนผ่าน heredoc ถูกแปลงเป็นขึ้นบรรทัดใหม่ → เขียนสคริปต์ด้วย Write tool แล้วรัน** · อย่าสั่ง `Stop-Process` ด้วย regex ที่ตรงกับ command line ของ shell ตัวเอง (ฆ่า shell ตัวเองไปด้วย)
- ห้ามเรียก `chrome.exe` ตรงๆ ในเครื่องที่ผู้ใช้เปิด Chrome อยู่ (เปิดหน้าต่างใน session เดิม) — ใช้ `--user-data-dir` แยกเสมอ
- test ของ controller ยิงเครือข่ายจริง (ปก/oEmbed) → code path นั้นห้าม import PySide6 (ใช้ Pillow)
- `Write` ทับไฟล์ stub เดิมได้โดยไม่เตือน → ดู `git show HEAD:<ไฟล์>` ก่อนทับ

## interface ที่เฟสถัดไปต้องใช้
- `PlayerController` (โหมด companion): `companion_track(TrackRef)`, `companion_state(dict)`, `get_clock()` (= `remote_clock`), `track`, `duration`, `lyrics_offset`, `adjust_offset`, `reset_offset`, `refresh_lyrics`, `next_lyrics_candidate`, `skip_next/skip_prev/toggle_pause/seek` (→ `tab_control`), `_resolve_companion_track(hint)` → `(TrackRef, VideoInfo|None)` · EventBus: `track.changed` (deck=-1 ในโหมด companion), `track.meta_ready`, `lyrics.loading`, `lyrics.ready`, `lyrics.timing` (เฟส 4 ใช้อัปเกรดเวลาทีละช่วง), `bridge.status`, `health.report`
- เฟส 4 เสียบที่: `LyricsService.find` (ผล + `TimingLevel`), `WordTimingSource.ALIGNED`, `LYRICS_TIMING_UPDATED {video_id,start,end,words}` → `LyricsModel.update_words` (UI รองรับอยู่แล้ว), `AiClient` (stub) · **เสียงสำหรับ AI: โหลดด้วย `YouTubeClient.fetch_and_download` เบื้องหลังเฉพาะเพื่อวิเคราะห์** (ตัวเล่นไม่ใช้แล้ว)
- UI: `cfg` (`ov_*`, `look_*`, `hk_*`, `st_*`) · `SettingsStore.set/flat/reset_group` · `settingsBridge` (`resetGroup/resetAll/resetSize/quit/quitting/dataDir`) · `player.*` (`bridgeConnected, lyricsLoading, hasTranslation, showTranslation, lyricsOffset, adjustOffset, resetOffset, refreshLyrics, nextCandidate, skipNext/skipPrev, togglePause, seek, installExtension`)
- โปรโตคอล: ARCHITECTURE §13 · `app/core/messages.py`

## สิ่งที่เฟสถัดไปต้องรู้ก่อนเริ่ม และควรเริ่มจากตรงไหน
- **อ่าน "งานที่ยัดไว้ให้เฟสถัดไป" ใน PROGRESS.md แล้วสรุปให้ผู้ใช้ก่อนเริ่ม (กฎ PROMPT 0.3.1)**
- **เฟส 4 (Sonnet 5.5 high):** เป้าหมายหลัก = จัดเวลาเนื้อเพลงจากเสียงจริงของคลิป (MV/รีมิกซ์) · ติดตั้ง `requirements-ai.txt` (torch 2.11+cu128) · เคสทดสอบ `kRRrsIUxPpM`, `rPzC1o8E4t0` · AI โหลดเสียงเอง (แอปไม่เล่นเสียง) แล้วส่งผลทยอยเข้า UI · คำแปลไทยด้วยโมเดลแปลคุณภาพดี (ผู้ใช้สั่ง)
- เฟส 3 ที่เหลือ: P2 ของ UX UI (ดู PROGRESS)
- เฟส 5-6 พัก · เฟส 7 = ดาวความตรงของเนื้อเพลง (ต้องหลังเฟส 4)

## คำถามที่ยังไม่ได้คำตอบจากผู้ใช้
1. ผลทดสอบรุ่นนี้ (เช็กลิสต์ในแชต)
2. ~~เฟส 5-7~~ **ตอบแล้ว (2026-10-20):** 5-6 พักไว้ · 7 เก็บไว้แต่เปลี่ยนเป็นดาวความตรงของเนื้อเพลงให้ AI เรียนรู้
3. ส่วน "ระบบของ Apple Music/QQ Music" ที่บอกว่าอยู่ในไฟล์ UX UI.txt อยู่ตรงไหน (ในไฟล์ที่อ่านเจอไม่มี)
4. ลำดับเฟส: ทำเฟส 4 (AI จัดเวลา) ต่อทันทีหลังปิดเฟส 2 ใช่ไหม (เฟส 3 ส่วนใหญ่ทำไปแล้ว)

## ข้อความสำหรับวางในแชตใหม่ (copy ได้ทันที)
```
อ่าน PROMPT.md, ARCHITECTURE.md, docs/PROGRESS.md, docs/DECISIONS.md
docs/handoff/PHASE-2.md และ docs/handoff/PHASE-4-START.md ให้ครบ แล้วเริ่มเฟส 4
(ลำดับเฟส: 2 → 4 → 3 → 5 → 6 → 7 → 8 · ทิศทางล่าสุด: แอปไม่เล่นเสียง ดู DECISIONS)
```
