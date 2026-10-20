// หนึ่งบรรทัดเนื้อเพลง — สร้างครั้งเดียวต่อบรรทัด (คำเป็น Item ถาวร)
// ต่อเฟรมมีเฉพาะบรรทัดปัจจุบันที่คำนวณ progress ของแต่ละคำ (lyricPos ถูกผูกเฉพาะบรรทัดนั้น)
// คำ = Text จาง + Text สีเต็มที่ถูกตัดด้วย Item(clip) ความกว้างตาม progress (เติมซ้ายไปขวา)
// ไม่แยกอักษรไทย: ใช้ Text ต่อคำ ให้ Qt จัดสระ/วรรณยุกต์เอง
// ค่าหน้าตา/แอนิเมชันทั้งหมดอ่านจาก cfg (หน้าตั้งค่า: เปลี่ยนแล้วเห็นผลทันที) ไม่มีค่าสี/ขนาดฝังในไฟล์นี้
// ใช้ซ้ำได้หลายหน้าต่าง: หน้าต่างที่ต้องการสี/ขนาด/การจัดวางของตัวเอง (เช่นหน้าต่างเต็มจอ) ส่งทับผ่าน property ด้านล่าง
import QtQuick
import QtQuick.Effects

Item {
    id: root

    // role จาก LyricsModel
    required property int index
    required property real start
    required property real end
    required property string voice
    required property var words
    required property string translation
    required property string romanization
    required property string text
    required property real gapAfter
    required property real gapStart

    // ส่งเข้ามาจาก LyricsView
    property int currentLine: -1
    property real lyricPos: 0
    // ส่งทับค่าจาก cfg ได้ (หน้าต่างเต็มจอใช้สีขาวบนพื้นหลังสี/ตัวใหญ่ตามหน้าต่าง/ชิดซ้าย)
    property real sizeScale: 1.0
    property string forceAlign: ""
    property bool minimalMode: cfg.ov_mode === "minimal"
    property color colText: cfg.ov_text_color
    property color colInactive: cfg.ov_inactive_color
    property color colAccent: cfg.ov_accent_color
    property color colSecondary: cfg.ov_secondary_color
    property real textOpacity: cfg.ov_text_opacity
    property real inactiveOpacity: cfg.ov_inactive_opacity
    property bool showTranslation: cfg.ov_show_translation && player.showTranslation
    property real falloff: cfg.ov_falloff
    property int groupFirst: -1
    property int groupLast: -1
    // ขอบบน/ล่างของพื้นที่เนื้อเพลง: บรรทัดที่เข้าใกล้ขอบจะจางและเบลอเพิ่มทีละน้อย (ไม่ให้เห็นรอยตัดแข็ง)
    property real viewY: 0          // contentY ของ ListView
    property real viewH: 0          // ความสูงของ ListView
    property real edgeFrac: 0       // ความหนาของแถบขอบ (สัดส่วนความสูง) 0 = ปิด
    property real edgeBlurAmt: 0    // เบลอสูงสุดที่ขอบ 0-1
    property real blurAmount: cfg.ov_blur   // เบลอบรรทัดที่ไม่ได้ร้อง (0-1) ยิ่งไกลยิ่งเบลอ
    property bool pastFilled: true   // false = บรรทัดที่ร้องไปแล้วจางเหมือนบรรทัดที่ยังไม่ร้อง (แบบ Apple Music)

    signal clicked()

    readonly property bool isCurrent: index === currentLine
    readonly property bool isPast: index < currentLine
    // ท่อนเดียวกับบรรทัดที่ร้องอยู่: บรรทัดก่อนหน้าในท่อนค้างความสว่าง (เต็มสี) ไว้ แล้วจางพร้อมกันตอนจบท่อน
    readonly property bool inGroup: currentLine >= 0 && index >= groupFirst && index <= groupLast
    readonly property bool heldInGroup: inGroup && index < currentLine
    readonly property int distance: currentLine < 0 ? index + 1
        : (inGroup ? (isCurrent ? 0 : 1) : (index < groupFirst ? groupFirst - index : index - groupLast))

    readonly property bool isSecond: voice === "second"
    readonly property bool isBackground: voice === "background"
    readonly property string alignMode: isSecond ? "right" : (forceAlign.length > 0 ? forceAlign : cfg.ov_align)
    readonly property real baseSize: cfg.ov_font_size * sizeScale * (isBackground ? 0.62 : 1.0)
    readonly property bool still: cfg.ov_reduced_motion
    readonly property real k: cfg.ov_animation_intensity          // ความแรงแอนิเมชัน
    readonly property real speed: Math.max(0.2, cfg.ov_anim_speed) // ตัวคูณความเร็ว (มาก = เร็ว)
    readonly property string anim: cfg.ov_animation
    readonly property string hl: cfg.ov_highlight
    readonly property real pad: 8

    // บรรทัดที่ไม่ใช่ปัจจุบันย่อลงเล็กน้อย (ไม่ทำให้ข้อความ reflow) — ปรับได้ที่ cfg.ov_idle_scale
    readonly property real idleScale: isBackground ? 1.0
        : (anim === "scale" ? Math.max(0.5, 1.0 - 0.2 * k)
           : (anim === "fade_move" ? Math.max(0.5, 1.0 - (1.0 - cfg.ov_idle_scale) * k) : 1.0))
    // ช่วงดนตรีหลังบรรทัดนี้ (>4 วิ) จองที่ไว้ล่วงหน้า กันภาพกระโดดตอนจุดโผล่
    readonly property real gapHeight: gapAfter > 0 ? 46 : 0
    // คลื่น: บรรทัดไกลจากบรรทัดปัจจุบันเริ่มเปลี่ยนช้ากว่าเล็กน้อย (ms ต่อบรรทัด สูงสุด 4 บรรทัด)
    readonly property int waveDelay: still ? 0 : Math.round(cfg.ov_wave_ms * Math.min(distance, 4))

    implicitHeight: body.implicitHeight * cfg.ov_line_spacing + 2 * pad + gapHeight
    height: implicitHeight

    // โหมด minimal เห็นแค่บรรทัดปัจจุบัน · ที่เหลือจางลงตามระยะห่าง (ปรับความไวที่ cfg.ov_falloff)
    opacity: (isCurrent || heldInGroup) ? textOpacity
        : (minimalMode ? 0 : Math.max(Math.min(0.06, inactiveOpacity * 0.25), inactiveOpacity * textOpacity - root.falloff * (distance - 1)))
    Behavior on opacity {
        enabled: !root.still && root.anim !== "move"
        SequentialAnimation {
            PauseAnimation { duration: root.waveDelay }
            NumberAnimation { duration: 260 / root.speed; easing.type: Easing.OutCubic }
        }
    }

    scale: isCurrent ? 1.0 : idleScale
    Behavior on scale {
        enabled: !root.still
        SequentialAnimation {
            PauseAnimation { duration: root.waveDelay }
            NumberAnimation { duration: 260 / root.speed; easing.type: Easing.OutCubic }
        }
    }
    transformOrigin: alignMode === "right" ? Item.TopRight
        : (alignMode === "center" ? Item.Top : Item.TopLeft)

    // การเลื่อนแบบ Apple Music (วัดจากคลิปจริง): ตอนเปลี่ยนบรรทัด รายการกระโดดไปตำแหน่งใหม่ทันที แล้วแต่ละบรรทัด "ไหล" จากตำแหน่งเดิมมาที่ใหม่เอง
    // เริ่มไม่พร้อมกัน (บรรทัดล่างช้ากว่าบรรทัดบน ~0.3 ms ต่อพิกเซล) โค้งแบบ critically damped (ไม่เด้ง) เสร็จใน ~0.4 วิ
    property real slide: 0
    transform: Translate { y: root.slide }
    function startSlide(from, delayMs, ms, bounce) {
        slideAnim.stop()
        root.slide = root.slide + from            // ต่อจากระยะที่ยังค้างจากการเลื่อนก่อนหน้า (ไม่กระตุกเมื่อเปลี่ยนบรรทัดถี่ๆ)
        slidePause.duration = Math.max(0, delayMs)
        slideNum.duration = Math.max(1, ms)
        slideNum.easing.overshoot = bounce
        slideNum.easing.type = bounce > 0.01 ? Easing.OutBack : Easing.BezierSpline
        slideAnim.start()
    }
    SequentialAnimation {
        id: slideAnim
        PauseAnimation { id: slidePause }
        NumberAnimation { id: slideNum; target: root; property: "slide"; to: 0; easing.type: Easing.BezierSpline
            easing.bezierCurve: [0.1, 0.3, 0.4, 1.0, 1, 1] }
    }

    // ความใกล้ขอบ 0 (ห่างขอบ) .. 1 (ติดขอบ) แบบ smoothstep
    readonly property real edgeNear: {
        if (edgeFrac < 0.005 || viewH <= 0) return 0
        var c = y + height / 2 - viewY
        var band = viewH * edgeFrac
        var d = Math.min(c, viewH - c)
        if (d >= band) return 0
        var u = Math.max(0, Math.min(1, 1 - d / band))
        return u * u * (3 - 2 * u)
    }
    readonly property real edgeBlurVal: edgeNear * edgeBlurAmt
    readonly property bool distBlur: blurAmount > 0.01 && !isCurrent && !heldInGroup && distance <= 8 && !still && !minimalMode

    // เบลอตามระยะห่าง (Apple Music): เฉพาะบรรทัดใกล้บรรทัดปัจจุบัน 8 บรรทัด + เบลอเพิ่มที่ขอบบน/ล่าง (ไม่สร้าง layer ให้ทุกบรรทัด)
    layer.enabled: distBlur || edgeBlurVal > 0.01
    layer.effect: MultiEffect {
        blurEnabled: true
        blurMax: 32
        blur: Math.min(1.0, (root.distBlur ? root.blurAmount * (0.5 + 0.5 * (root.distance - 1)) : 0) + root.edgeBlurVal)   // วัดจากคลิป Apple Music: บรรทัดถัดไปเบลอปานกลาง ถัดไปอีกเบลอแรงจนอ่านไม่ออก
    }

    Item {
        id: body
        opacity: 1.0 - root.edgeNear   // จางเข้าหาขอบ (ไม่ผ่าน Behavior ของบรรทัด จึงตามการเลื่อนทัน)
        x: pad
        y: pad + (parent.height - 2 * pad - gapHeight - implicitHeight) / 2
        width: (root.width - 2 * pad) * (root.alignMode === "center" ? 1.0 : 1.0) * cfg.ov_text_width
        implicitHeight: flow.implicitHeight + (sub.visible ? sub.implicitHeight + 2 : 0)

        Flow {
            id: flow
            // จัดซ้าย/กลาง/ขวา: ถ้าทั้งบรรทัดสั้นกว่ากรอบจะขยับทั้งก้อน
            width: body.width
            x: {
                var free = body.width - childrenRect.width
                if (free <= 0) return 0
                return root.alignMode === "right" ? free : (root.alignMode === "center" ? free / 2 : 0)
            }

            Repeater {
                model: root.words
                delegate: Item {
                    id: w
                    required property var modelData

                    readonly property real spaceW: modelData.trailingSpace ? root.baseSize * 0.3 : 0
                    // progress 0..1 ของคำนี้ (เฉพาะบรรทัดปัจจุบันที่คำนวณตามเวลา)
                    readonly property real prog: {
                        if (!root.isCurrent)
                            return root.isPast && (root.pastFilled || root.heldInGroup) ? 1 : 0
                        if (root.hl === "line")
                            return 1
                        var d = modelData.end - modelData.start
                        if (d <= 0.001 || root.hl === "word")
                            return root.lyricPos >= modelData.start ? 1 : 0
                        return Math.max(0, Math.min(1, (root.lyricPos - modelData.start) / d))
                    }
                    // คำเน้น: ลากเสียงยาว หรือถูกระบุ emphasis มา (เฟส 4: ตัวตรวจจับ/AI) — เรืองแสงตอนร้อง
                    readonly property bool emph: cfg.ov_emph_on && !root.still
                        && (modelData.emphasis === true || (!modelData.estimated && (modelData.end - modelData.start) >= cfg.ov_emph_min_s))

                    // spacer = ตัวดันให้คำเสียงประสาน (background) ขึ้นแถวใหม่ใต้บรรทัดหลัก · เสียงประสานตัวเล็ก/จางกว่า (แบบ Apple Music)
                    readonly property bool bgWord: modelData.background === true
                    width: modelData.spacer === true ? flow.width : fxw.implicitWidth + spaceW
                    height: modelData.spacer === true ? 1 : fxw.implicitHeight
                    opacity: bgWord ? 0.72 : 1.0

                    // ลอย/ขยาย/เรืองแสงทั้งคำหรือทีละตัวอักษร (cfg.ov_word_anim) อยู่ใน FxWord
                    FxWord {
                        id: fxw
                        visible: w.modelData.spacer !== true
                        text: w.modelData.text
                        prog: w.prog
                        sinceEnd: root.lyricPos - w.modelData.end
                        current: root.isCurrent
                        still: root.still
                        emphasis: w.emph
                        pixelSize: root.baseSize * (w.bgWord ? 0.62 : 1.0)
                        // น้ำหนักตัวอักษรของบรรทัดปัจจุบันหนาขึ้นได้ (Weight highlight, UX UI ข้อ 4.3)
                        weight: Math.min(900, cfg.ov_font_weight + (root.isCurrent ? cfg.ov_weight_boost : 0))
                        letterSpacing: cfg.ov_letter_spacing
                        family: cfg.look_font_family
                        shadow: cfg.ov_text_shadow
                        colText: root.colText
                        colInactive: root.colInactive
                        colAccent: root.colAccent
                        hl: root.hl
                        speed: root.speed
                        k: root.k
                    }
                }
            }
        }

        // เผื่อบรรทัดที่ไม่มีคำ (ไม่มีเวลาทีละคำเลย) แสดงข้อความเต็มแทน
        Text {
            visible: root.words.length === 0
            width: body.width
            text: root.text
            wrapMode: Text.Wrap
            horizontalAlignment: root.alignMode === "right" ? Text.AlignRight
                : (root.alignMode === "center" ? Text.AlignHCenter : Text.AlignLeft)
            color: root.isCurrent ? root.colText : root.colInactive
            font.pixelSize: root.baseSize
            font.weight: cfg.ov_font_weight
            font.family: cfg.look_font_family
        }

        // คำแปล / romanization ใต้บรรทัด (เฉพาะที่เปิดไว้ และต้องเป็นของบรรทัดนี้จริง — ไม่ยืมของบรรทัดอื่น)
        Column {
            id: sub
            y: flow.implicitHeight + 2
            width: body.width
            visible: (root.showTranslation && root.translation.length > 0)
                || (cfg.look_show_romanization && root.romanization.length > 0)
            Text {
                width: parent.width
                visible: cfg.look_show_romanization && root.romanization.length > 0
                text: root.romanization
                wrapMode: Text.Wrap
                horizontalAlignment: root.alignMode === "right" ? Text.AlignRight
                    : (root.alignMode === "center" ? Text.AlignHCenter : Text.AlignLeft)
                color: root.colSecondary
                font.pixelSize: root.baseSize * cfg.look_romanization_scale
                font.family: cfg.look_font_family
            }
            Text {
                width: parent.width
                visible: root.showTranslation && root.translation.length > 0
                text: root.translation
                wrapMode: Text.Wrap
                horizontalAlignment: root.alignMode === "right" ? Text.AlignRight
                    : (root.alignMode === "center" ? Text.AlignHCenter : Text.AlignLeft)
                color: root.colSecondary
                font.pixelSize: root.baseSize * cfg.ov_translation_size
                font.family: cfg.look_font_family
            }
        }
    }

    // ช่วงดนตรี: จุด 3 จุดค่อยๆ เติมตามเวลาที่ผ่านไปในช่องว่าง (เฉพาะตอนเป็นบรรทัดปัจจุบันและร้องจบแล้ว)
    Row {
        id: dots
        spacing: 10
        x: root.alignMode === "center" ? (root.width - width) / 2 : pad
        y: root.height - root.gapHeight + 8
        visible: root.isCurrent && root.gapAfter > 0 && root.lyricPos > root.gapStart
        readonly property real frac: root.gapAfter > 0
            ? Math.max(0, Math.min(1, (root.lyricPos - root.gapStart) / root.gapAfter)) : 0
        Repeater {
            model: 3
            delegate: Rectangle {
                required property int index
                width: 14 * Math.max(0.7, root.sizeScale)
                height: width
                radius: width / 2
                color: root.colInactive
                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    color: root.colText
                    opacity: Math.max(0, Math.min(1, dots.frac * 3 - parent.index))
                }
            }
        }
    }

    TapHandler {
        onTapped: root.clicked()
    }
}
