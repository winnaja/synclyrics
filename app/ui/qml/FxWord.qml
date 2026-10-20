import QtQuick
import QtQuick.Effects

// คำเดียวของเนื้อเพลง: ข้อความจาง + ส่วนที่เติมสีแล้ว + เอฟเฟกต์ลอย/ขยาย/เรืองแสง
// cfg.ov_word_anim:
//   none = เติมสีอย่างเดียว
//   word = ทั้งคำลอย/ขยาย/เรืองแสงทันทีที่ถึงคำนั้น (ไม่รอร้องจบ)
//   char = ทีละตัวอักษร: ตัวที่ขอบการเติมสีผ่านจะลอย/ขยาย/เรืองแสงตามไปเรื่อยๆ
// ปริมาณของลอย (ov_lift_px) / ขยาย (ov_word_scale) / แสง (ov_glow_strength) เป็นอิสระต่อกัน ใช้ร่วมกันได้
// แสงเรืองเฉพาะส่วนที่เติมสีแล้ว (เงาตามรูปของข้อความสว่าง) ไม่ใช่ทั้งคำ
Item {
    id: fx

    property string text: ""
    property real prog: 0           // ความคืบหน้าการเติมสีของคำ 0..1
    property real sinceEnd: -1      // วินาทีนับจากร้องคำนี้จบ (ลบ = ยังไม่จบ)
    property bool current: false    // อยู่ในบรรทัดที่กำลังร้อง
    property bool still: false      // ลดการเคลื่อนไหว
    property bool emphasis: false   // คำเน้น (ลากเสียงยาว) — เรืองแสง+ขยายแยกจากโหมดคำ
    property real pixelSize: 34
    property int weight: 700
    property real letterSpacing: 0
    property string family: ""
    property real shadow: 0
    property color colText: "white"
    property color colInactive: "gray"
    property color colAccent: "white"
    property string hl: "fill"
    property real speed: 1.0
    property real k: 1.0            // ตัวคูณความแรงของแอนิเมชัน

    implicitWidth: dim.implicitWidth
    implicitHeight: dim.implicitHeight

    // เติมสีด้วยขอบนุ่ม (Apple Music) เฉพาะไฮไลต์แบบเติมสี/เรืองแสง
    readonly property bool softWipe: (hl === "fill" || hl === "glow") && !still
    readonly property bool singing: current && prog > 0 && prog < 1
    // "ทำงานอยู่": เริ่มร้องแล้ว และ (ยังร้องอยู่ | ค้างไว้จนจบบรรทัด | อยู่ในช่วงค้างหลังร้องจบ)
    readonly property bool act: current && prog > 0
        && (prog < 1 || cfg.ov_word_stay || sinceEnd < cfg.ov_word_hold_ms / 1000)
    readonly property bool emphNow: emphasis && act

    readonly property string mode: still ? "none" : cfg.ov_word_anim
    readonly property int easeType: cfg.ov_word_ease === "spring" ? Easing.OutBack
        : (cfg.ov_word_ease === "gentle" ? Easing.InOutSine
           : (cfg.ov_word_ease === "linear" ? Easing.Linear : Easing.OutCubic))
    readonly property int upMs: Math.max(40, cfg.ov_word_anim_ms / speed)
    readonly property int downMs: Math.max(0, cfg.ov_word_release_ms / speed)

    // ---------- โหมดทั้งคำ ----------
    readonly property bool wordFx: mode === "word" && act
    readonly property real glowTarget: emphNow ? cfg.ov_emph_glow : (wordFx ? cfg.ov_glow_strength : 0)
    property real glowAmt: glowTarget
    Behavior on glowAmt { NumberAnimation { duration: fx.glowTarget > fx.glowAmt ? fx.upMs : fx.downMs; easing.type: Easing.OutCubic } }

    // ---------- โหมดทีละตัวอักษร ----------
    // วาดทีละตัวเฉพาะบรรทัดปัจจุบัน (+ช่วงคืนตัวหลังออกจากบรรทัด) ไม่งั้นใช้ข้อความทั้งคำตามปกติ
    property bool lingering: false
    Timer { id: lingerT; interval: fx.downMs + 80; onTriggered: fx.lingering = false }
    onCurrentChanged: {
        if (current) { lingering = false; lingerT.stop() }
        else if (mode === "char") { lingering = true; lingerT.restart() }
    }
    readonly property bool charMode: mode === "char" && (current || lingering)
    // ขึ้นทันทีที่เริ่มร้อง (ไม่หน่วง) แต่คืนช้าๆ ตาม word_release_ms
    readonly property real charTarget: mode === "char" && act ? 1 : 0
    property real charAmt: charTarget
    Behavior on charAmt { NumberAnimation { duration: fx.charTarget > fx.charAmt ? 0 : fx.downMs; easing.type: Easing.OutCubic } }

    // แยกข้อความเป็นกลุ่มตัวอักษร (ตัวฐาน + สระ/วรรณยุกต์ที่ซ้อน) ไม่ให้ตัวอักษรไทยแตก
    function clusters(s) {
        var re = /[̀-ͯัิ-ฺ็-๎‍️ཱ-ཾ]/
        var out = []
        var pre = ""
        var i = 0
        while (i < s.length) {
            var j = i + 1
            var c = s.charCodeAt(i)
            if (c >= 0xD800 && c <= 0xDBFF && j < s.length) j++            // คู่ surrogate (อีโมจิ ฯลฯ)
            while (j < s.length && re.test(s.charAt(j))) j++
            var t = s.substring(i, j)
            out.push({ pre: pre, t: t })
            pre += t
            i = j
        }
        return out
    }

    Item {
        id: lift
        width: fx.implicitWidth
        height: fx.implicitHeight
        // ห้ามผูก y ของ FxWord เอง: Flow เป็นคนกำหนดตำแหน่ง
        y: fx.wordFx ? -cfg.ov_lift_px * fx.k : 0
        Behavior on y { NumberAnimation { duration: fx.wordFx ? fx.upMs : fx.downMs; easing.type: fx.easeType } }
        scale: fx.emphNow ? cfg.ov_emph_scale : (fx.wordFx ? cfg.ov_word_scale : 1.0)
        transformOrigin: Item.Bottom
        Behavior on scale { NumberAnimation { duration: (fx.wordFx || fx.emphNow) ? fx.upMs : fx.downMs; easing.type: fx.easeType } }

        Text {
            id: dim
            visible: !fx.charMode
            text: fx.text
            color: fx.colInactive
            font.pixelSize: fx.pixelSize
            font.weight: fx.weight
            font.letterSpacing: fx.letterSpacing
            font.family: fx.family
            style: fx.shadow > 0.02 ? Text.Raised : Text.Normal
            styleColor: Qt.rgba(0, 0, 0, 0.55 * fx.shadow)
        }

        // ---- ส่วนที่เติมสีแล้ว (ทั้งคำ) พร้อมแสงเรืองเฉพาะส่วนนี้ ----
        Item {
            id: filledHost
            visible: !fx.charMode
            width: fx.implicitWidth
            height: fx.implicitHeight
            layer.enabled: fx.glowAmt > 0.01 && !fx.charMode
            layer.effect: MultiEffect {
                autoPaddingEnabled: true
                shadowEnabled: true
                shadowColor: cfg.ov_glow_color
                shadowBlur: 1.0
                shadowOpacity: fx.glowAmt
                shadowScale: 1.0
            }
            // ร้องจบแล้ว = แสดงตรงๆ · กำลังร้อง = ผ่าน shader เติมสีด้วยขอบนุ่ม (Loader สร้างเฉพาะคำที่กำลังเติม)
            Text {
                visible: fx.prog >= 1 || (fx.prog > 0 && !fx.softWipe)
                width: fx.softWipe || fx.prog >= 1 ? implicitWidth : dim.implicitWidth * fx.prog
                clip: !(fx.softWipe || fx.prog >= 1)
                text: fx.text
                color: (fx.singing && (fx.hl === "glow" || fx.hl === "word")) ? fx.colAccent : fx.colText
                font: dim.font
                style: dim.style
                styleColor: fx.hl === "glow" && fx.singing ? fx.colAccent : dim.styleColor
            }
            Loader {
                active: fx.softWipe && fx.prog > 0 && fx.prog < 1 && !fx.charMode
                width: dim.implicitWidth
                height: dim.implicitHeight
                sourceComponent: Item {
                    width: dim.implicitWidth
                    height: dim.implicitHeight
                    Text {
                        id: wipeSrc
                        visible: false
                        text: fx.text
                        color: fx.colText
                        font: dim.font
                        style: dim.style
                        styleColor: dim.styleColor
                    }
                    ShaderEffect {
                        anchors.fill: parent
                        property variant source: ShaderEffectSource { sourceItem: wipeSrc; hideSource: true; live: true; smooth: true }
                        property real prog: fx.prog
                        // ขอบนุ่มกว้าง ~0.6 em (ไม่เกิน 70% ของคำสั้นๆ)
                        property real soft: Math.max(0.12, Math.min(0.7, fx.pixelSize * 0.6 / Math.max(1, dim.implicitWidth)))
                        fragmentShader: Qt.resolvedUrl("../shaders/word_wipe.frag.qsb")
                    }
                }
            }
        }

        // ---- โหมดทีละตัวอักษร ----
        Loader {
            active: fx.charMode
            width: fx.implicitWidth
            height: fx.implicitHeight
            sourceComponent: Item {
                id: ch
                width: dim.implicitWidth
                height: dim.implicitHeight
                readonly property var parts: fx.clusters(fx.text)
                readonly property var dimParts: parts.map(function (p) { return { pre: p.pre, t: p.t, filled: false } })
                readonly property var fillParts: parts.map(function (p) { return { pre: p.pre, t: p.t, filled: true } })
                readonly property real soft: Math.max(0.12, Math.min(0.7, fx.pixelSize * 0.6 / Math.max(1, dim.implicitWidth)))

                // ความคืบหน้าของตัวอักษรที่อยู่ตำแหน่ง c (0..1 ของความกว้างคำ): ขอบนุ่มเดียวกับ shader เติมสี
                function charProg(c) {
                    if (!fx.softWipe) return fx.prog >= 1 ? 1 : 0
                    return Math.max(0, Math.min(1, (fx.prog * (1 + soft) - c) / soft))
                }

                Component {
                    id: cellComp
                    Item {
                        id: cell
                        required property int index
                        required property var modelData
                        TextMetrics { id: m0; font: dim.font; text: cell.modelData.pre }
                        TextMetrics { id: m1; font: dim.font; text: cell.modelData.pre + cell.modelData.t }
                        x: m0.advanceWidth
                        width: Math.max(1, m1.advanceWidth - m0.advanceWidth)
                        height: dim.implicitHeight
                        readonly property real cp: ch.charProg((x + width / 2) / Math.max(1, dim.implicitWidth))
                        readonly property real amt: cp * fx.charAmt
                        Item {
                            width: cell.width
                            height: cell.height
                            y: -cfg.ov_lift_px * fx.k * cell.amt
                            scale: 1 + (cfg.ov_word_scale - 1) * cell.amt
                            transformOrigin: Item.Bottom
                            Text {
                                text: cell.modelData.t
                                color: !cell.modelData.filled ? fx.colInactive
                                    : ((fx.singing && (fx.hl === "glow" || fx.hl === "word")) ? fx.colAccent : fx.colText)
                                opacity: cell.modelData.filled ? cell.cp : 1.0
                                font: dim.font
                                style: dim.style
                                styleColor: dim.styleColor
                            }
                        }
                    }
                }

                Item {
                    width: ch.width
                    height: ch.height
                    Repeater { model: ch.dimParts; delegate: cellComp }
                }
                // ชั้นสีเต็ม: เงาเรืองเกิดจากตัวอักษรสว่างที่ผ่านไปแล้วเท่านั้น (ความโปร่งใสของตัวอักษรกำหนดความแรงแสง)
                Item {
                    id: filledLayer
                    width: ch.width
                    height: ch.height
                    layer.enabled: cfg.ov_glow_strength * fx.charAmt > 0.01
                    layer.effect: MultiEffect {
                        autoPaddingEnabled: true
                        shadowEnabled: true
                        shadowColor: cfg.ov_glow_color
                        shadowBlur: 1.0
                        shadowOpacity: cfg.ov_glow_strength * fx.charAmt
                        shadowScale: 1.0
                    }
                    Repeater { model: ch.fillParts; delegate: cellComp }
                }
            }
        }
    }
}
