# ทดสอบ end-to-end กับ Chrome ตัวจริง (ไม่อยู่ในชุด pytest — ใช้อินเทอร์เน็ตและเปิด Chrome)

`node tests/e2e/chrome_e2e.js` (ต้องมี Node, Chrome, `.venv`, อินเทอร์เน็ต) ทำสิ่งนี้ทั้งหมดอัตโนมัติ:
1. เปิดแอปจริง (`python -m app`, offscreen, `SYNCLYRICS_HOME` ชั่วคราว, pipe แยก `SYNCLYRICS_PIPE=synclyrics-e2e` — **ไม่ชนกับแอป/Chrome ที่ผู้ใช้เปิดอยู่**)
2. เปิด Chrome headless โปรไฟล์ชั่วคราว (`--remote-debugging-pipe --enable-unsafe-extension-debugging`) แล้วโหลดส่วนขยายจริงด้วย CDP `Extensions.loadUnpacked`
   (Chrome 137+ ไม่รับ `--load-extension` แล้ว) — native host จริงถูก Chrome เปิดผ่านค่าใน registry (ต้องเคยลงทะเบียน host แล้ว: ปุ่ม "ติดตั้งส่วนขยาย" หรือ `scripts\install_extension.bat`)
3. เล่นวิดีโอ → ตรวจว่าแอปได้ videoId/ชื่อที่ถูกต้อง · เปลี่ยนเพลงแบบ SPA → แอปตามทัน · โฆษณา (โปรไฟล์ทดสอบไม่ใช่ Premium) → แอปไม่เดินตาม · กรอ/หยุด/เล่น · คำสั่ง play_pause/seek/volume/mute จากแอปไปสั่งวิดีโอ (วอลลุ่มผ่านตัวเล่น YouTube ด้วย page.js) · ผู้ใช้ปรับเสียงใน YouTube → แอปรับค่าตาม
แอปถูกสังเกตผ่าน pipe เหมือนส่วนขยาย (อ่าน `status`) + `state.json`
