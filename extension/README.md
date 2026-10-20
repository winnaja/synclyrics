# ส่วนขยาย Chrome (Manifest V3) — SyncLyrics

หน้าที่เดียว: **รายงานให้โปรแกรมรู้ว่าเพลงไหน (videoId) เล่นอยู่ที่วินาทีเท่าไร** แบบเรียลไทม์ แล้วโปรแกรมแสดงเนื้อเพลงบนหน้าต่างลอย — และส่งคำสั่งจากโปรแกรม (เล่น/หยุด/กรอ/ถัดไป/ก่อนหน้า) ไปสั่งวิดีโอ
**เบาที่สุด ห้ามทำให้ YouTube ช้า** · ไม่หยุดวิดีโอ ไม่ใส่ปุ่ม ไม่แก้หน้าเว็บ · YouTube เป็นคนเล่นเสียงเสมอ

## ไฟล์

| ไฟล์ | หน้าที่ |
| --- | --- |
| `manifest.json` | MV3 + `"key"` (ทำให้ extension ID คงที่ `jjafolpgjdghgjadopngdolglpllbhod`) · permissions: `nativeMessaging`, `contextMenus`, `storage`, `alarms` · host: youtube.com, music.youtube.com เท่านั้น |
| `background.js` | service worker: `connectNative("com.synclyrics.host")` ต่อใหม่ทุก 2 วิ, ไอคอนสถานะ (ปกติ/เทา/จุดแดง), เลือกแท็บต้นทางที่กำลังเล่น (หลายแท็บไม่สลับไปมา), กดไอคอน = เปิด/ดึงหน้าต่างเนื้อเพลง, เมนูคลิกขวาที่ไอคอน |
| `content.js` | ฟังเหตุการณ์ของ `<video>` (play/pause/seeked/ratechange/…) + ส่งเวลาทุก 250ms ตอนเล่น · ส่งแค่ `video_id` ไม่ส่งชื่อเพลงจากหน้าเว็บ (ตอนเปลี่ยนเพลง URL เปลี่ยนก่อนชื่อบนหน้า จะได้ชื่อเพลงเก่า) · รับ `tab_control` |
| `icons/` | ไอคอนของเราเอง 3 สถานะ (`scripts/gen_extension_icons.py`) |

## กติกา

- `extension/key.pem` (private key) **ห้าม commit** และควรสำรองไว้ที่อื่น — หายแล้ว ID เปลี่ยน
- รูปแบบข้อความ: `app/core/messages.py` · ข้อความที่ใช้: ส่วนขยาย → แอป `hello, companion_track, companion_state, command, launch_app (ให้ host เปิดแอป), log`; แอป → ส่วนขยาย `hello_ack, status, tab_control, reload_extension, error`
- ติดตั้ง: ปุ่ม "ติดตั้งส่วนขยาย" ในโปรแกรม (หรือ `scripts\install_extension.bat`) คัดลอกโฟลเดอร์นี้ไป `%LOCALAPPDATA%\SyncLyrics\extension` แล้วให้ผู้ใช้ Load unpacked ครั้งเดียว · อัปเดต: กดปุ่มเดิมซ้ำ (โปรแกรมสั่ง reload ส่วนขยายให้เอง)
- test: `tests/js/background.test.js` (Node) · end-to-end กับ Chrome ตัวจริง: ดูหัวข้อ "ทดสอบกับ Chrome จริง" ใน `docs/handoff/PHASE-2.md`
