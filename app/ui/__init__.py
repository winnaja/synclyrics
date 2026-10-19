"""UI: PySide6 + Qt Quick (QML) วาดด้วย GPU ผ่าน scene graph (ข้อ 1.1, ส่วนที่ 3, 8, 9)

app/ui/*.py    ฝั่ง Python ที่ expose ข้อมูลให้ QML (QObject, model) — อยู่ใน UI thread เท่านั้น
app/ui/qml/    หน้าตาทั้งหมด
app/ui/shaders/ GLSL (.frag/.vert) + .qsb ที่คอมไพล์แล้วด้วย pyside6-qsb (scripts/build_shaders.py)

กฎประสิทธิภาพ (ข้อ 12.1):
  - เวลาไฮไลต์อ่านจาก Clock ทุกเฟรม (FrameAnimation/onBeforeRendering) ไม่ใช้ Timer
  - node ของข้อความสร้างครั้งเดียวต่อบรรทัด วาดเฉพาะบรรทัดใกล้จอ
  - วัด FPS ตลอด ต่ำกว่า 50 -> ลด blur/อนุภาคอัตโนมัติ, ย่อหน้าต่าง -> หยุดวาด (เสียงเล่นต่อ)
"""
