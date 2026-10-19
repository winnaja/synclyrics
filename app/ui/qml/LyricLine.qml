// หนึ่งบรรทัดเนื้อเพลง — สร้างครั้งเดียวต่อบรรทัด (คำเป็น Item ถาวร)
// ต่อเฟรมมีเฉพาะบรรทัดปัจจุบันที่คำนวณ progress ของแต่ละคำ (lyricPos ถูกผูกเฉพาะบรรทัดนั้น)
// คำ = Text จาง + Text สีเต็มที่ถูกตัดด้วย Item(clip) ความกว้างตาม progress (เติมซ้ายไปขวา)
// ไม่แยกอักษรไทย: ใช้ Text ต่อคำ ให้ Qt จัดสระ/วรรณยุกต์เอง
import QtQuick

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

    // ส่งเข้ามาจาก LyricsView
    property int currentLine: -1
    property real lyricPos: 0

    signal clicked()

    readonly property bool isCurrent: index === currentLine
    readonly property bool isPast: index < currentLine
    readonly property int distance: currentLine < 0 ? index + 1 : Math.abs(index - currentLine)

    readonly property bool isSecond: voice === "second"
    readonly property bool isBackground: voice === "background"
    readonly property string alignMode: isSecond ? "right" : look.align
    readonly property real baseSize: look.font_size * (isBackground ? 0.62 : 1.0)
    readonly property real activeScale: 1.0
    readonly property real idleScale: isBackground ? 1.0 : 0.82
    readonly property real pad: 10

    // ช่วงดนตรีหลังบรรทัดนี้ (>4 วิ) จองที่ไว้ล่วงหน้า กันภาพกระโดดตอนจุดโผล่
    readonly property real gapHeight: gapAfter > 0 ? 46 : 0

    implicitHeight: body.implicitHeight + 2 * pad + gapHeight
    height: implicitHeight

    opacity: isCurrent ? 1.0 : Math.max(0.16, 0.6 - 0.11 * (distance - 1))
    Behavior on opacity { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

    // ย่อบรรทัดที่ไม่ใช่ปัจจุบัน (ไม่ทำให้ข้อความ reflow)
    scale: isCurrent ? activeScale : idleScale
    Behavior on scale { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    transformOrigin: alignMode === "right" ? Item.TopRight
        : (alignMode === "center" ? Item.Top : Item.TopLeft)

    Item {
        id: body
        x: pad
        y: pad
        width: root.width - 2 * pad
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
                            return root.isPast ? 1 : 0
                        var d = modelData.end - modelData.start
                        if (d <= 0.001)
                            return root.lyricPos >= modelData.start ? 1 : 0
                        return Math.max(0, Math.min(1, (root.lyricPos - modelData.start) / d))
                    }

                    width: dim.implicitWidth + spaceW
                    height: dim.implicitHeight
                    // คำที่กำลังร้องลอยขึ้น 2px — ห้ามผูก y ของ w เอง: Flow เป็นคนกำหนดตำแหน่ง (เคยทำให้คำกระโดดไปทับแถวแรก)
                    Item {
                        id: lift
                        width: w.width
                        height: w.height
                        y: root.isCurrent && w.prog > 0 && w.prog < 1 ? -2 : 0
                        Behavior on y { NumberAnimation { duration: 140 } }

                        Text {
                            id: dim
                            text: w.modelData.text
                            color: look.color_unsung
                            font.pixelSize: root.baseSize
                            font.weight: look.font_weight
                            font.letterSpacing: look.letter_spacing
                            font.family: look.font_family
                        }
                        Item {
                            width: dim.implicitWidth * w.prog
                            height: dim.implicitHeight
                            clip: true
                            visible: w.prog > 0
                            Text {
                                text: w.modelData.text
                                color: root.isCurrent ? look.color_active : look.color_sung
                                font: dim.font
                            }
                        }
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
            color: root.isCurrent ? look.color_active : look.color_unsung
            font.pixelSize: root.baseSize
            font.weight: look.font_weight
            font.family: look.font_family
        }

        // คำแปล / romanization ใต้บรรทัด
        Column {
            id: sub
            y: flow.implicitHeight + 2
            width: body.width
            visible: (look.show_translation && root.translation.length > 0)
                || (look.show_romanization && root.romanization.length > 0)
            Text {
                width: parent.width
                visible: look.show_romanization && root.romanization.length > 0
                text: root.romanization
                wrapMode: Text.Wrap
                horizontalAlignment: root.alignMode === "right" ? Text.AlignRight
                    : (root.alignMode === "center" ? Text.AlignHCenter : Text.AlignLeft)
                color: look.color_unsung
                font.pixelSize: root.baseSize * look.romanization_scale
                font.family: look.font_family
            }
            Text {
                width: parent.width
                visible: look.show_translation && root.translation.length > 0
                text: root.translation
                wrapMode: Text.Wrap
                horizontalAlignment: root.alignMode === "right" ? Text.AlignRight
                    : (root.alignMode === "center" ? Text.AlignHCenter : Text.AlignLeft)
                color: look.color_unsung
                font.pixelSize: root.baseSize * look.translation_scale
                font.family: look.font_family
            }
        }
    }

    // ช่วงดนตรี: จุด 3 จุดค่อยๆ เติมตามเวลาที่ผ่านไปในช่องว่าง (เฉพาะตอนเป็นบรรทัดปัจจุบันและร้องจบแล้ว)
    Row {
        id: dots
        spacing: 10
        x: pad
        y: root.height - root.gapHeight + 8
        visible: root.isCurrent && root.gapAfter > 0 && root.lyricPos > root.end
        readonly property real frac: root.gapAfter > 0
            ? Math.max(0, Math.min(1, (root.lyricPos - root.end) / root.gapAfter)) : 0
        Repeater {
            model: 3
            delegate: Rectangle {
                required property int index
                width: 14
                height: 14
                radius: 7
                color: look.color_unsung
                Rectangle {
                    anchors.fill: parent
                    radius: 7
                    color: look.color_active
                    opacity: Math.max(0, Math.min(1, dots.frac * 3 - parent.index))
                }
            }
        }
    }

    TapHandler {
        onTapped: root.clicked()
    }
}
