#version 440
// พื้นหลังไหลลื่นสีจากปกเพลง (แบบ Apple Music) — 4 สีผสมกันด้วยน้ำหนักตามระยะจากจุดที่เคลื่อนช้าๆ + บิดพื้นที่เล็กน้อยให้ดูเป็นของเหลว
// ทำงานบน GPU ผ่านเดียว (1 pass) เบามาก เวลาส่งเข้ามาจาก FrameAnimation เดียวของหน้าต่าง
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;        // วินาที
    float brightness;  // 0.3-1.3
    float speed;       // ตัวคูณความเร็วการไหล (0 = นิ่ง)
    vec2 aspect;       // (กว้าง/สูง, 1)
    vec4 c0;
    vec4 c1;
    vec4 c2;
    vec4 c3;
};

void main() {
    vec2 uv = qt_TexCoord0;
    vec2 p = (uv - 0.5) * vec2(aspect.x, 1.0);
    float t = time * 0.10 * speed;
    // บิดพื้นที่ให้ขอบสีไหลเป็นคลื่น
    p += 0.10 * vec2(sin(p.y * 2.6 + t * 1.9), cos(p.x * 2.2 - t * 1.6));
    vec2 q0 = vec2(sin(t * 1.0 + 0.0), cos(t * 0.8 + 1.0)) * vec2(0.55 * aspect.x, 0.40);
    vec2 q1 = vec2(sin(t * 0.7 + 2.1), cos(t * 1.1 + 0.4)) * vec2(0.60 * aspect.x, 0.38);
    vec2 q2 = vec2(sin(t * 0.9 + 4.0), cos(t * 0.6 + 2.5)) * vec2(0.50 * aspect.x, 0.42);
    vec2 q3 = vec2(sin(t * 1.2 + 5.3), cos(t * 0.5 + 3.7)) * vec2(0.58 * aspect.x, 0.36);
    float w0 = 1.0 / (0.04 + dot(p - q0, p - q0));
    float w1 = 1.0 / (0.04 + dot(p - q1, p - q1));
    float w2 = 1.0 / (0.04 + dot(p - q2, p - q2));
    float w3 = 1.0 / (0.04 + dot(p - q3, p - q3));
    w0 *= w0; w1 *= w1; w2 *= w2; w3 *= w3;
    vec3 col = (c0.rgb * w0 + c1.rgb * w1 + c2.rgb * w2 + c3.rgb * w3) / (w0 + w1 + w2 + w3);
    // ขอบมืดนิดๆ ให้ตัวอักษรขาวอ่านง่าย
    float vig = 1.0 - 0.35 * smoothstep(0.35, 1.1, length(uv - 0.5) * 1.6);
    fragColor = vec4(col * brightness * vig, 1.0) * qt_Opacity;
}
