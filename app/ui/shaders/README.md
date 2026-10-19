# shaders

GLSL 440 สำหรับ Qt Quick `ShaderEffect` (Qt 6 ต้องคอมไพล์เป็น `.qsb` ก่อนใช้)

- คอมไพล์: `py -3.12 scripts/build_shaders.py` (เรียก `pyside6-qsb --glsl "100es,120,150" --hlsl 50 --msl 12`)
- `.qsb` ที่คอมไพล์แล้ว commit ไว้ด้วย โปรแกรมจึงรันได้โดยไม่ต้องมีเครื่องมือคอมไพล์
- ไฟล์ที่จะมี (เฟส 3): `fluid.frag` (mesh gradient), `blur_cover.frag`, `word_wipe.frag` (mask ไฮไลต์ทีละคำ), `glow.frag`, ทรานซิชั่น (`morph`, `dissolve`, `zoom_through`, `blur_through`)
