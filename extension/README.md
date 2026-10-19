# ส่วนขยาย Chrome (Manifest V3) — สร้างจริงในเฟส 2

หน้าที่: ส่งเพลง/คิว/playlist ไปโปรแกรม, เป็นรีโมต, และส่งเวลาเล่นในโหมดคู่หู — **เบาที่สุด ห้ามทำให้ YouTube ช้า**

## ไฟล์ที่จะมี

| ไฟล์ | หน้าที่ |
| --- | --- |
| `manifest.json` | MV3 + `"key"` (public key) ทำให้ extension ID คงที่ · permissions: `nativeMessaging`, `contextMenus`, `storage` · host: youtube.com, music.youtube.com |
| `background.js` | service worker: `connectNative("com.synclyrics.host")`, ต่อใหม่ทุก 2 วิ, ไอคอนสถานะ (ปกติ/เทา/จุดแดง), `action.onClicked`, เมนูคลิกขวา |
| `content.js` | ปุ่ม "เล่นเลย"/"เข้าคิว" บน thumbnail, "ส่งทั้ง playlist", "เปิดในแอป" ข้างปุ่ม Like, ฟัง `yt-navigate-finish`, โหมดคู่หู (currentTime/play/pause/rate/seek) |
| `content.css` | สไตล์ปุ่มเล็กๆ (ไม่มีเอฟเฟกต์หนัก) |
| `selectors.json` | สำเนาจาก `config/selectors.json` (โปรแกรมส่งฉบับล่าสุดมาทับผ่านข้อความ `selectors`) |
| `icons/` | ไอคอนของเราเอง (ห้ามใช้โลโก้ YouTube/Apple/QQ) |

## กติกา

- `extension/key.pem` (private key) **ห้าม commit** — อยู่ใน `.gitignore` แล้ว
- รูปแบบข้อความ: `app/core/messages.py` (`EXT_TO_APP`, `APP_TO_EXT`)
- selector หาไม่เจอ = ไม่แสดงปุ่ม + ส่ง `log` ไปโปรแกรม ห้าม throw จนหน้าเว็บพัง
- ติดตั้ง: wizard ในโปรแกรมคัดลอกโฟลเดอร์นี้ไป `%LOCALAPPDATA%\SyncLyrics\extension` แล้วให้ผู้ใช้ Load unpacked ครั้งเดียว
