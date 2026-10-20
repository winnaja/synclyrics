#version 440
// ไฮไลต์คำแบบ Apple Music: เติมสีจากซ้ายไปขวาด้วย "ขอบนุ่ม" (gradient) ไม่ใช่ตัดแข็ง
// source = ข้อความสีเต็ม (ที่เติมแล้ว) · prog 0..1 = ความคืบหน้าของคำ · soft = ความกว้างขอบนุ่มเป็นสัดส่วนความกว้างคำ
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float prog;
    float soft;
};
layout(binding = 1) uniform sampler2D source;

void main() {
    // ขอบเลื่อนจาก -soft ถึง 1+soft: prog=0 ไม่เห็นอะไร · prog=1 เต็มทั้งคำ (ไม่มีรอยตัดค้าง)
    float edge = mix(-soft, 1.0 + soft, prog);
    float a = clamp((edge - qt_TexCoord0.x) / max(soft, 0.001), 0.0, 1.0);
    a = a * a * (3.0 - 2.0 * a);   // smoothstep ให้ขอบนุ่มทั้งหัวและท้าย
    fragColor = texture(source, qt_TexCoord0) * (a * qt_Opacity);
}
