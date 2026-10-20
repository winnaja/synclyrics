#version 440
// ปกเพลง: ครอปเต็มช่อง (แบบ PreserveAspectCrop) + มุมโค้งขอบเนียน
// ต้องครอปที่นี่ ไม่ใช่ใน QML: ShaderEffect ใช้ texture ทั้งรูปของ Image เสมอ (ไม่สนใจ fillMode) ถ้าไม่ครอปเอง รูป 16:9 จะถูกบีบลงช่องจัตุรัส
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float radius;   // พิกเซล
    vec2 size;      // ขนาดของ item เป็นพิกเซล
    vec2 imgSize;   // ขนาดจริงของรูป (พิกเซล) — 0 = ไม่ครอป
};
layout(binding = 1) uniform sampler2D source;

void main() {
    vec2 p = qt_TexCoord0 * size;
    vec2 q = abs(p - size * 0.5) - (size * 0.5 - vec2(radius));
    float d = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - radius;
    float a = 1.0 - smoothstep(-1.0, 0.5, d);
    vec2 uv = qt_TexCoord0;
    if (imgSize.x > 1.0 && imgSize.y > 1.0) {
        float s = max(size.x / imgSize.x, size.y / imgSize.y);   // ขยายให้เต็มช่อง (ด้านที่สั้นกว่าพอดี อีกด้านล้นแล้วตัด)
        uv = (p - size * 0.5) / (imgSize * s) + 0.5;
    }
    vec4 c = texture(source, uv);
    fragColor = c * (a * qt_Opacity);
}
