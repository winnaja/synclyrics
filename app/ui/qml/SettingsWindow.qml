// หน้าตั้งค่า (UX UI หมวด 10) — แถบหมวดซ้าย · การ์ดแถวบางๆ ขวา (ชื่อ+คำอธิบายซ้าย ตัวควบคุมขวา) · ค้นหาได้ · ตัวอย่างสด
// ทุกการเปลี่ยนมีผลทันที (cfg เดียวกับหน้าต่างเนื้อเพลง) และบันทึกเอง · ตัวเลือกขั้นสูงซ่อนหลังสวิตช์ · ใช้คีย์บอร์ดได้
// หมวด: ทั่วไป · โหมดเต็ม · หน้าต่างลอย · ตัวอักษร · พื้นหลังและธีม · เนื้อเพลง · แอนิเมชัน · การซิงก์ · คีย์ลัด
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import QtQuick.Effects

Window {
    id: win
    objectName: "settingsWindow"

    signal placeRequested(string name)
    signal installRequested()
    signal quitRequested()
    signal hiddenToTray()

    width: 1000
    height: 720
    minimumWidth: 720
    minimumHeight: 480
    visible: false
    title: "SyncLyrics — ตั้งค่า"
    color: "#15161d"

    // ปิดหน้าต่าง = ซ่อน (ไม่ปิดโปรแกรม) และบอกผู้ใช้ว่ายังทำงานอยู่ที่ถาดระบบ (UX UI ข้อ 11)
    // (โปรแกรมกำลังออกจริง = ต้องยอมปิด ไม่งั้น quit() จะค้าง เพราะ Qt 6 ให้หน้าต่างคัดค้านการ quit ได้)
    onClosing: (close) => {
        if (settingsBridge.quitting) return
        if (!cfg.st_close_to_tray) { settingsBridge.quit(); return }   // ผู้ใช้เลือกให้ปุ่มปิด = ปิดโปรแกรม
        close.accepted = false
        win.visible = false
        win.hiddenToTray()
    }

    readonly property color fg: "#F2F2F5"
    readonly property color fg2: "#9A9BA8"
    readonly property color panel: "#1b1c25"
    readonly property color card: "#20212c"
    readonly property color field: "#2b2d3b"
    readonly property color line: "#2c2e3d"
    readonly property color accent: "#A5B4FC"
    property bool advanced: false     // แสดงตัวเลือกขั้นสูง
    // ตัวอย่างสดย่อเหลือแถบเตี้ยๆ เมื่อเลื่อนลง (ไม่กินที่อ่านการตั้งค่า) · hysteresis กันสลับไปมาตอนความสูงของรายการเปลี่ยน
    property bool previewPinned: false          // true = ผู้ใช้กดขยายค้างไว้
    property bool previewCompact: false
    Connections {
        target: scroller
        function onContentYChanged() {
            if (win.previewPinned) win.previewCompact = false
            else if (scroller.contentY > 90) win.previewCompact = true
            else if (scroller.contentY < 4) win.previewCompact = false
        }
    }
    onPageChanged: { previewCompact = false; previewPinned = false }
    property string query: ""         // ค้นหา: ไม่ว่าง = แสดงทุกหมวดที่มีแถวตรงกับคำค้น
    readonly property string q: query.trim().toLowerCase()
    // ค้นหาหลายคำ (คั่นด้วยเว้นวรรค): ต้องเจอครบทุกคำในข้อความรวมของแถว (ชื่อ คำอธิบาย คีย์ หมวด)
    function hit(text) {
        if (q.length === 0) return true
        var t = text.toLowerCase(), terms = q.split(/\s+/)
        for (var i = 0; i < terms.length; ++i)
            if (terms[i].length > 0 && t.indexOf(terms[i]) < 0) return false
        return true
    }
    function pageOf(item) {                       // index ของหมวด (pages) ที่ item อยู่ · -1 = ไม่พบ
        for (var p = item ? item.parent : null; p; p = p.parent)
            if (p.pgIdx !== undefined) return p.pgIdx
        return -1
    }
    function cardOf(item) {
        for (var p = item ? item.parent : null; p; p = p.parent)
            if (p.isCard === true) return p
        return null
    }
    function gotoPage(idx) { query = ""; searchBox.text = ""; page = idx; scroller.contentY = 0 }

    // ================= ตัวควบคุมพื้นฐาน =================
    // การ์ด: หัวข้อ + แถวบางๆ คั่นด้วยเส้นจาง ซ่อนตัวเองเมื่อไม่มีแถวที่มองเห็น (ตอนค้นหา/ปิดขั้นสูง)
    component Card: Item {
        id: cd
        property string title: ""
        property string note: ""
        default property alias rows: col.data
        readonly property bool isCard: true
        readonly property int pageIdx: win.pageOf(cd)
        width: parent ? parent.width : 400
        clip: true
        // ไม่ใช้ visible ของการ์ดเอง: visible ของลูกเป็นค่าที่ขึ้นกับพ่อ จะวนค้างอยู่ที่ false ตลอด
        readonly property bool any: {
            var kids = col.children
            for (var i = 0; i < kids.length; ++i)
                if (kids[i].want === true) return true
            return false
        }
        height: any ? head.height + body.height + 22 : 0
        Text {
            id: head
            readonly property bool crumb: win.q.length > 0 && cd.pageIdx >= 0
            visible: cd.title.length > 0 || crumb
            text: crumb ? win.pages[cd.pageIdx].t + (cd.title.length > 0 ? "  ›  " + cd.title : "") : cd.title
            color: crumb ? win.accent : win.fg2
            font.pixelSize: 12; font.weight: Font.DemiBold; font.family: cfg.look_font_family
            font.letterSpacing: 0.6
            leftPadding: 4
            height: visible ? 26 : 0
            verticalAlignment: Text.AlignTop
            TapHandler { enabled: head.crumb; onTapped: win.gotoPage(cd.pageIdx) }   // กดหัวข้อผลค้นหา = ไปหมวดนั้น
            HoverHandler { enabled: head.crumb; cursorShape: Qt.PointingHandCursor }
        }
        Rectangle {
            id: body
            y: head.height
            width: parent.width
            height: col.height + 2
            radius: 14
            color: win.card
            border.width: 1
            border.color: win.line
            clip: true
            Column { id: col; y: 1; width: parent.width }
        }
        Text {
            visible: cd.note.length > 0
            y: head.height + body.height + 4
            width: parent.width
            text: cd.note
            wrapMode: Text.Wrap
            color: win.fg2; font.pixelSize: 11; font.family: cfg.look_font_family
            leftPadding: 4
        }
    }

    // คำอธิบายสั้นๆ บนสุดของหมวด: หมวดนี้ทำอะไร
    component Intro: Text {
        width: parent ? parent.width : 400
        wrapMode: Text.Wrap
        color: win.fg2
        font.pixelSize: 13
        font.family: cfg.look_font_family
        bottomPadding: 4
        visible: win.q.length === 0
    }

    component Row2: Item {                       // แถว: ป้ายซ้าย ตัวควบคุมขวา (adv = ซ่อนจนกว่าจะเปิดตัวเลือกขั้นสูง)
        id: r2
        property string label: ""
        property string hint: ""
        property bool adv: false
        property bool wide: false                // true = ตัวควบคุมกว้างเต็มแถวใต้ป้าย (สี/ตัวอย่าง)
        property string resetKey: ""             // คีย์ที่ปุ่ม ↺ จะคืนค่า (ว่าง = หาเองจากตัวควบคุมตัวแรกที่มี key)
        default property alias content: slot.data
        readonly property var cardItem: win.cardOf(r2)
        readonly property bool matches: win.q.length === 0
            || win.hit(label + " " + hint + " " + rkey + " " + (cardItem ? cardItem.title : "")
                       + " " + (cardItem && cardItem.pageIdx >= 0 ? win.pages[cardItem.pageIdx].t : ""))
        readonly property bool want: (!adv || win.advanced || win.q.length > 0) && matches
        readonly property string ctlKey: {
            var kids = slot.children
            for (var i = 0; i < kids.length; ++i) {
                var k = kids[i].key
                if (typeof k === "string" && k.length > 0) return k
            }
            return ""
        }
        readonly property string rkey: resetKey.length > 0 ? resetKey : ctlKey
        // ส่ง cfg[rkey] เข้าไปด้วยเพื่อให้ binding คำนวณใหม่ทุกครั้งที่ผู้ใช้ปรับ (ปุ่มโผล่เมื่อต่างจากค่าเริ่มต้น หายเมื่อกดคืนค่า)
        readonly property bool modified: rkey.length > 0 && !settingsBridge.isDefault(rkey, cfg[rkey])
        readonly property real resetW: rkey.length > 0 ? 34 : 0   // กันที่ไว้เสมอเมื่อมีปุ่ม เพื่อไม่ให้ตัวควบคุมขยับตอนปุ่มโผล่
        visible: want
        width: parent ? parent.width : 400
        height: want ? (wide ? labels.height + slot.childrenRect.height + 30 : Math.max(54, Math.max(labels.height, slot.childrenRect.height) + 24)) : 0
        Rectangle { visible: r2.want; anchors.bottom: parent.bottom; x: 16; width: parent.width - 32; height: 1; color: win.line; opacity: 0.7 }
        Rectangle { visible: r2.want && win.q.length > 0 && r2.label.length > 0; x: 0; y: 10; width: 3; height: parent.height - 20; radius: 1.5; color: win.accent }   // ไฮไลต์แถวที่ตรงกับคำค้น
        Rectangle {                              // ปุ่มคืนค่าเริ่มต้นของตัวเลือกนี้
            id: rb
            objectName: "resetKeyButton"
            visible: r2.want && r2.modified
            activeFocusOnTab: visible
            x: r2.width - 18 - width
            y: r2.wide ? 10 : (r2.height - height) / 2
            width: 26; height: 26; radius: 13
            color: rm.pressed ? "#40435a" : (rh.hovered ? "#353850" : win.field)
            border.width: activeFocus ? 2 : 0
            border.color: "#FFFFFF"
            Text { anchors.centerIn: parent; text: "↺"; color: win.accent; font.pixelSize: 16; font.family: cfg.look_font_family }
            HoverHandler { id: rh }
            TapHandler { id: rm; onTapped: { rb.forceActiveFocus(); settingsBridge.resetKey(r2.rkey) } }
            Keys.onSpacePressed: settingsBridge.resetKey(r2.rkey)
            Keys.onReturnPressed: settingsBridge.resetKey(r2.rkey)
            ToolTip.visible: rh.hovered
            ToolTip.delay: 350
            ToolTip.text: "คืนค่าเริ่มต้นของข้อนี้"
        }
        Column {
            id: labels
            x: 18
            y: wide ? 12 : (parent.height - height) / 2
            width: wide ? parent.width - 36 - r2.resetW : parent.width * 0.42 - 18
            spacing: 2
            Text { text: r2.label; color: win.fg; font.pixelSize: 14; font.family: cfg.look_font_family; width: parent.width; wrapMode: Text.Wrap
                visible: r2.label.length > 0 }
            Text { visible: r2.hint.length > 0; text: r2.hint; color: win.fg2; font.pixelSize: 12; font.family: cfg.look_font_family; width: parent.width; wrapMode: Text.Wrap }
        }
        Item {
            id: slot
            x: wide ? 18 : parent.width * 0.44
            y: wide ? labels.y + labels.height + 8 : (parent.height - height) / 2
            width: wide ? parent.width - 36 : parent.width * 0.56 - 18 - r2.resetW
            height: childrenRect.height
        }
    }

    component SSwitch: Rectangle {
        id: sw
        property string key: ""
        readonly property bool on: cfg[key] === true
        activeFocusOnTab: true
        anchors.right: parent ? parent.right : undefined
        width: 44; height: 26; radius: 13
        color: on ? win.accent : "#3a3c4d"
        border.width: activeFocus ? 2 : 0
        border.color: "#FFFFFF"
        Behavior on color { ColorAnimation { duration: 120 } }
        Rectangle {
            width: 20; height: 20; radius: 10; y: 3
            x: sw.on ? sw.width - width - 3 : 3
            color: "#FFFFFF"
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
        TapHandler { onTapped: { sw.forceActiveFocus(); cfg[sw.key] = !sw.on } }
        Keys.onSpacePressed: cfg[sw.key] = !sw.on
        Keys.onReturnPressed: cfg[sw.key] = !sw.on
    }

    component SSlider: Item {
        id: sl
        property string key: ""
        property real from: 0
        property real to: 1
        property real step: 0.01
        property int decimals: 2
        property string unit: ""
        readonly property real value: Number(cfg[key])
        activeFocusOnTab: true
        height: 28
        width: parent ? parent.width : 200
        function setValue(v) {
            v = Math.max(from, Math.min(to, Math.round(v / step) * step))
            cfg[key] = Number(v.toFixed(4))
        }
        Keys.onLeftPressed: setValue(value - step)
        Keys.onDownPressed: setValue(value - step)
        Keys.onRightPressed: setValue(value + step)
        Keys.onUpPressed: setValue(value + step)
        readonly property real frac: Math.max(0, Math.min(1, (sl.value - sl.from) / (sl.to - sl.from)))
        Rectangle { id: trk; y: 12; x: 0; width: sl.width - 66; height: 4; radius: 2; color: "#3a3c4d"
            Rectangle { width: parent.width * sl.frac; height: 4; radius: 2; color: win.accent } }
        Rectangle { x: trk.width * sl.frac - 8; y: 6; width: 16; height: 16; radius: 8; color: "#FFFFFF"
            border.width: sl.activeFocus ? 3 : 0; border.color: win.accent }
        Text { x: sl.width - 60; width: 60; y: 5; horizontalAlignment: Text.AlignRight; color: win.fg2; font.pixelSize: 12; font.family: cfg.look_font_family
            text: sl.value.toFixed(sl.decimals) + sl.unit }
        MouseArea {
            x: 0; width: trk.width; height: parent.height
            function setFrom(mx) { sl.forceActiveFocus(); sl.setValue(sl.from + Math.max(0, Math.min(1, mx / width)) * (sl.to - sl.from)) }
            onPressed: (m) => setFrom(m.x)
            onPositionChanged: (m) => { if (pressed) setFrom(m.x) }
        }
    }

    component Pill: Rectangle {
        id: pl
        property string label: ""
        property bool active: false
        signal clicked()
        activeFocusOnTab: true
        implicitWidth: pt.implicitWidth + 26
        implicitHeight: 32
        radius: 16
        border.width: activeFocus ? 2 : 0
        border.color: "#FFFFFF"
        color: active ? win.accent : (pm.pressed ? "#40435a" : (ph.hovered ? "#353850" : win.field))
        Behavior on color { ColorAnimation { duration: 100 } }
        Text { id: pt; anchors.centerIn: parent; text: pl.label; color: pl.active ? "#14151c" : win.fg; font.pixelSize: 13; font.family: cfg.look_font_family }
        HoverHandler { id: ph }
        TapHandler { id: pm; onTapped: { pl.forceActiveFocus(); pl.clicked() } }
        Keys.onSpacePressed: pl.clicked()
        Keys.onReturnPressed: pl.clicked()
    }

    component Segment: Flow {                   // เลือกค่าเดียวจากชุดตัวเลือก (ค่า/ป้าย)
        id: seg
        property string key: ""
        property var options: []                // [{v: "focus", t: "โฟกัส"}, ...]
        spacing: 6
        width: parent ? parent.width : 300
        Repeater {
            model: seg.options
            Pill {
                required property var modelData
                label: modelData.t
                active: cfg[seg.key] === modelData.v
                onClicked: cfg[seg.key] = modelData.v
            }
        }
    }

    component SColor: Item {
        id: sc
        property string key: ""
        readonly property var swatches: ["#FFFFFF", "#F5F5F7", "#A5B4FC", "#C4B5FD", "#F9A8D4", "#FCD34D", "#86EFAC", "#7DD3FC", "#000000", "#0B0B10", "#1B1F3B", "#777780"]
        width: parent ? parent.width : 300
        height: 66
        Rectangle { id: chip; width: 30; height: 30; radius: 8; color: cfg[sc.key]; border.width: 1; border.color: "#555" }
        TextField {
            x: 40; width: 100; height: 30
            text: cfg[sc.key]
            color: win.fg; font.pixelSize: 13
            selectByMouse: true
            validator: RegularExpressionValidator { regularExpression: /^#[0-9A-Fa-f]{6}$/ }
            background: Rectangle { radius: 8; color: win.field; border.width: parent.activeFocus ? 1 : 0; border.color: win.accent }
            onEditingFinished: if (acceptableInput) cfg[sc.key] = text.toUpperCase()
        }
        Flow {
            y: 38; width: parent.width; spacing: 5
            Repeater {
                model: sc.swatches
                Rectangle {
                    required property string modelData
                    width: 20; height: 20; radius: 6; color: modelData; border.width: 1; border.color: "#555"
                    TapHandler { onTapped: cfg[sc.key] = parent.modelData }
                }
            }
        }
    }

    component SText: TextField {
        id: st
        property string key: ""
        width: parent ? parent.width : 200
        height: 32
        text: cfg[key]
        color: win.fg; font.pixelSize: 13; selectByMouse: true
        background: Rectangle { radius: 8; color: win.field; border.width: st.activeFocus ? 1 : 0; border.color: win.accent }
        onEditingFinished: cfg[key] = text.trim()
    }

    // ตัวอย่างสด: เนื้อเพลง 3 บรรทัด บรรทัดกลางเติมสีวนซ้ำ — เห็นผลของสี/ตัวอักษร/แอนิเมชันคำทันทีโดยไม่ต้องรอเพลง
    component Preview: Rectangle {
        id: pv
        property bool compact: false
        width: parent ? parent.width : 400
        height: 170
        radius: 14
        clip: true
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#6B3E5E" }
            GradientStop { position: 0.55; color: "#8A5A6E" }
            GradientStop { position: 1.0; color: "#3F4E78" }
        }
        property real t: 0
        readonly property var words: ["Girl,", "let's", "put", "some", "miles", "on it"]
        Timer { interval: 33; repeat: true; running: pv.visible && win.visible; onTriggered: pv.t = (pv.t + 0.033) % 5.4 }
        readonly property real sz: Math.min(compact ? 26 : 34, cfg.ov_font_size * 0.8)
        readonly property real sampleScale: 1.0
        Column {
            anchors.centerIn: parent
            width: parent.width - 40
            spacing: 6
            Text { visible: !pv.compact; width: parent.width; text: "Jump in the Cadillac"; color: cfg.ov_inactive_color; opacity: 0.55
                font.pixelSize: pv.sz * 0.86; font.weight: cfg.ov_font_weight; font.family: cfg.look_font_family
                horizontalAlignment: cfg.ov_align === "center" ? Text.AlignHCenter : (cfg.ov_align === "right" ? Text.AlignRight : Text.AlignLeft) }
            Item {
                width: parent.width
                height: pv.sz * 1.5
                Row {
                    id: wordRow
                    x: cfg.ov_align === "center" ? (parent.width - width) / 2 : (cfg.ov_align === "right" ? parent.width - width : 0)
                    Repeater {
                        model: pv.words
                        delegate: Item {
                            id: pw
                            required property int index
                            required property string modelData
                            readonly property real prog: cfg.ov_highlight === "line" ? 1
                                : (cfg.ov_highlight === "word" ? (pv.t >= index * 0.8 ? 1 : 0)
                                   : Math.max(0, Math.min(1, (pv.t - index * 0.8) / 0.8)))
                            width: fxp.implicitWidth + pv.sz * 0.3
                            height: fxp.implicitHeight
                            FxWord {
                                id: fxp
                                text: pw.modelData
                                prog: pw.prog
                                sinceEnd: pv.t - (pw.index + 1) * 0.8
                                current: true
                                still: cfg.ov_reduced_motion
                                pixelSize: pv.sz
                                weight: Math.min(900, cfg.ov_font_weight + cfg.ov_weight_boost)
                                letterSpacing: cfg.ov_letter_spacing
                                family: cfg.look_font_family
                                colText: cfg.ov_text_color
                                colInactive: cfg.ov_inactive_color
                                colAccent: cfg.ov_accent_color
                                hl: cfg.ov_highlight
                                speed: Math.max(0.2, cfg.ov_anim_speed)
                                k: cfg.ov_animation_intensity
                            }
                        }
                    }
                }
            }
            Text { visible: !pv.compact; width: parent.width; text: "Our love is still spinning"; color: cfg.ov_inactive_color; opacity: 0.4
                font.pixelSize: pv.sz * 0.86; font.weight: cfg.ov_font_weight; font.family: cfg.look_font_family
                horizontalAlignment: cfg.ov_align === "center" ? Text.AlignHCenter : (cfg.ov_align === "right" ? Text.AlignRight : Text.AlignLeft) }
        }
        Text { anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 8; text: "ตัวอย่างสด"; color: "#FFFFFF"; opacity: 0.5; font.pixelSize: 10; font.family: cfg.look_font_family }
    }

    // ขนาดสำเร็จรูปของโหมดปัจจุบัน (UX UI ข้อ 3.3)
    function setSize(w, h) {
        cfg["ov_w_" + cfg.ov_mode] = w
        cfg["ov_h_" + cfg.ov_mode] = h
    }

    // ================= โครงหน้าต่าง =================
    property int page: 9
    // title / คำที่ใช้ค้น / กลุ่มที่ปุ่ม "คืนค่า" จะรีเซ็ต
    readonly property var pages: [
        { t: "โปรแกรมและชุดค่า", g: "general", n: "การเริ่มต้น ปุ่มปิด ข้อมูล" },
        { t: "หน้าต่างเต็ม", g: "full", n: "หน้าต่างเต็ม ปก วอลลุ่ม พื้นหลัง" },
        { t: "หน้าต่างลอย", g: "float", n: "ตำแหน่ง ขนาด จอ" },
        { t: "ตัวอักษรและสี", g: "font", n: "ฟอนต์ สี ขนาด" },
        { t: "ธีมและพื้นหลัง", g: "theme", n: "ธีม ความโปร่งใส" },
        { t: "การอ่านเนื้อเพลง", g: "lyrics", n: "ไฮไลต์ เลื่อน คำแปล" },
        { t: "การเคลื่อนไหว", g: "anim", n: "ชุด คาราโอเกะ" },
        { t: "เวลาและ AI", g: "ai", n: "YouTube เวลา ค้นหา AI ฟังเสียง คำแปล" },
        { t: "คีย์ลัด", g: "hotkeys", n: "ทั้งระบบ" },
        { t: "ตั้งค่าด่วน", g: "", n: "ใช้บ่อย เริ่มที่นี่ ธีม ขนาด แอนิเมชัน AI" },
        { t: "แหล่งเนื้อเพลง", g: "sources", n: "เว็บ LRCLIB NetEase QQ คำบรรยาย ตัดบรรทัด รวมหลายแหล่ง" }
    ]
    // ลำดับในแถบซ้าย (ค่าคือ index ของ pages) — เริ่มที่ "ตั้งค่าด่วน" แล้วค่อยลงรายละเอียด
    // จัดกลุ่มตามสิ่งที่อยากทำ: h = หัวข้อกลุ่ม · pg = index ของ pages (ทุกหมวดเดิมยังอยู่ครบ)
    readonly property var navItems: [
        { h: "เริ่มที่นี่" }, { pg: 9 },
        { h: "หน้าตา" }, { pg: 3 }, { pg: 4 }, { pg: 6 },
        { h: "เนื้อเพลง" }, { pg: 5 }, { pg: 10 }, { pg: 7 },
        { h: "หน้าต่าง" }, { pg: 1 }, { pg: 2 },
        { h: "โปรแกรม" }, { pg: 0 }, { pg: 8 }
    ]
    function show(p) { return win.q.length > 0 || win.page === p }

    Rectangle {
        id: nav
        width: 214
        height: parent.height
        color: win.panel
        Text { id: navTitle; x: 20; y: 20; text: "ตั้งค่า"; color: win.fg; font.pixelSize: 22; font.weight: Font.Bold; font.family: cfg.look_font_family }
        Flickable {
            x: 10; y: 64; width: parent.width - 20; height: parent.height - 72
            contentWidth: width; contentHeight: navCol.implicitHeight + 8
            clip: true
            boundsBehavior: Flickable.StopAtBounds
        Column {
            id: navCol
            width: parent.width; spacing: 2
            Repeater {
                model: win.navItems
                Item {
                    id: ni
                    required property int index
                    required property var modelData
                    readonly property bool isHead: modelData.h !== undefined
                    readonly property int pg: isHead ? -1 : modelData.pg
                    width: parent.width
                    height: isHead ? 30 : 38
                    Text { visible: ni.isHead; x: 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 4
                        text: ni.isHead ? ni.modelData.h : ""; color: win.fg2; opacity: 0.75
                        font.pixelSize: 11; font.weight: Font.DemiBold; font.family: cfg.look_font_family; font.letterSpacing: 0.6 }
                Rectangle {
                    visible: !ni.isHead
                    readonly property int pg: ni.pg
                    activeFocusOnTab: !ni.isHead
                    width: parent.width; height: 38; radius: 10
                    border.width: activeFocus ? 2 : 0
                    border.color: "#FFFFFF"
                    color: win.page === pg && win.q.length === 0 ? "#2d3044" : (nh.hovered ? "#252736" : "transparent")
                    Text { anchors.verticalCenter: parent.verticalCenter; x: 14; text: parent.pg >= 0 ? win.pages[parent.pg].t : ""
                        color: win.page === parent.pg && win.q.length === 0 ? win.fg : win.fg2
                        font.pixelSize: 14; font.family: cfg.look_font_family; font.weight: parent.pg === 9 ? Font.DemiBold : Font.Normal }
                    HoverHandler { id: nh }
                    TapHandler { onTapped: { win.query = ""; win.page = parent.pg } }
                    Keys.onSpacePressed: { win.query = ""; win.page = pg }
                    Keys.onReturnPressed: { win.query = ""; win.page = pg }
                }
                }
            }
        }
        }
    }

    // แถบบนของเนื้อหา: ชื่อหมวด + ค้นหา + คืนค่า
    Item {
        id: top
        x: nav.width + 28
        y: 14
        width: parent.width - nav.width - 56
        height: 56
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: win.q.length > 0 ? "ผลการค้นหา" : win.pages[win.page].t
            color: win.fg; font.pixelSize: 24; font.weight: Font.Bold; font.family: cfg.look_font_family
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 10
            Pill {
                label: win.advanced ? "โหมดละเอียด: เปิด" : "โหมดละเอียด: ปิด"
                active: win.advanced
                onClicked: win.advanced = !win.advanced
            }
            Pill {
                visible: win.q.length === 0 && win.pages[win.page].g.length > 0
                label: "คืนค่าหมวดนี้"
                onClicked: settingsBridge.resetPage(win.pages[win.page].g)
            }
            TextField {
                id: searchBox
                width: 180; height: 34
                placeholderText: "ค้นหาการตั้งค่า"
                placeholderTextColor: win.fg2
                color: win.fg; font.pixelSize: 13; font.family: cfg.look_font_family
                leftPadding: 14; selectByMouse: true
                text: win.query
                onTextChanged: win.query = text
                rightPadding: 30
                background: Rectangle { radius: 17; color: win.field; border.width: searchBox.activeFocus ? 1 : 0; border.color: win.accent }
                Text {
                    visible: searchBox.text.length > 0
                    anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                    text: "✕"; color: win.fg2; font.pixelSize: 13
                    TapHandler { onTapped: { searchBox.text = ""; searchBox.forceActiveFocus() } }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                }
                Keys.onEscapePressed: text = ""
            }
        }
    }

    // ตัวอย่างสดตรึงไว้บนสุด (ไม่เลื่อนหนีไป) เห็นผลทันทีขณะลากแถบด้านล่าง
    Preview {
        id: stickyPreview
        x: nav.width + 28
        y: top.y + top.height + 6
        width: parent.width - nav.width - 56
        compact: win.previewCompact
        height: visible ? (compact ? 76 : 150) : 0
        Behavior on height { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        visible: win.q.length === 0 && (win.page === 3 || win.page === 6 || win.page === 9)
        TapHandler { onTapped: win.previewPinned = !win.previewPinned }   // กดตัวอย่างเพื่อขยาย/ย่อเอง
    }

    Flickable {
        id: scroller
        x: nav.width + 28
        y: stickyPreview.y + (stickyPreview.visible ? stickyPreview.height + 10 : 0)
        width: parent.width - nav.width - 56
        height: parent.height - y - 14
        contentWidth: width
        contentHeight: pageCol.implicitHeight + 24
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { }

        Column {
            id: pageCol
            width: scroller.width - 14
            spacing: 6

            Text {
                visible: win.q.length > 0 && pageCol.height < 60
                text: "ไม่พบการตั้งค่าที่ตรงกับ \"" + win.query + "\" — ลองคำอื่น (ค้นได้จากชื่อ คำอธิบาย ชื่อหมวด หรือชื่อคีย์ เช่น font, blur)"
                color: win.fg2; font.pixelSize: 13; font.family: cfg.look_font_family
            }

            // ---------------- ตั้งค่าด่วน ----------------
            Column {
                property int pgIdx: 9; visible: win.show(9); width: parent.width; spacing: 6
                Intro { text: "ตัวเลือกที่ใช้บ่อยรวมไว้ที่เดียว เห็นผลที่ตัวอย่างด้านบนทันที · อยากปรับละเอียดกว่านี้ไปที่หมวดอื่นทางซ้าย (เปิด \"โหมดละเอียด\" ที่มุมขวาบนเพื่อดูตัวเลือกทั้งหมด)" }
                Card { title: "หน้าตา"
                    Row2 { label: "ธีม"; hint: "สีพื้นหลังและความโปร่งใสโดยรวม"; wide: true
                        Segment { key: "ov_theme"; options: [{v:"soft_dark",t:"Soft Dark"},{v:"pure_black",t:"Pure Black"},{v:"frosted",t:"Frosted Glass"},{v:"minimal_transparent",t:"โปร่งใส"},{v:"light",t:"Light"}] } }
                    Row2 { label: "ขนาดตัวอักษร (หน้าต่างลอย)"; SSlider { key: "ov_font_size"; from: 12; to: 120; step: 1; decimals: 0; unit: " px" } }
                    Row2 { label: "ขนาดตัวอักษร (โหมดเต็ม)"; hint: "เป็นเท่าของขนาดมาตรฐาน"; SSlider { key: "fw_font_scale"; from: 0.5; to: 2.0; step: 0.05 } }
                    Row2 { label: "การจัดวางข้อความ"; wide: true
                        Segment { key: "ov_align"; options: [{v:"left",t:"ซ้าย"},{v:"center",t:"กลาง"},{v:"right",t:"ขวา"}] } }
                    Row2 { label: "สีข้อความที่ร้องแล้ว"; wide: true; SColor { key: "ov_text_color" } }
                }
                Card { title: "การเคลื่อนไหว"
                    Row2 { label: "ชุดแอนิเมชัน"; hint: "ชุดสำเร็จรูป · \"นุ่มนวล\" ใกล้ Apple Music ที่สุด"; wide: true
                        Segment { key: "ov_anim_preset"; options: [{v:"smooth",t:"นุ่มนวล (แบบ Apple)"},{v:"balanced",t:"สมดุล"},{v:"bouncy",t:"เด้งนิดๆ"},{v:"snappy",t:"ฉับไว"},{v:"none",t:"ไม่เคลื่อนไหว"}] } }
                    Row2 { label: "ไฮไลต์คำที่ร้อง"; hint: "เติมสีไล่ตามเสียง / ทีละคำ / เรืองแสง / ทั้งบรรทัด"; wide: true
                        Segment { key: "ov_highlight"; options: [{v:"fill",t:"เติมสี"},{v:"word",t:"ทีละคำ"},{v:"glow",t:"เรืองแสง"},{v:"line",t:"ทั้งบรรทัด"}] } }
                    Row2 { label: "ลอย / ขยาย / เรืองแสง"; hint: "ทั้งคำ = ทันทีที่ถึงคำ · ทีละตัวอักษร = ไล่ตามเสียง (ปรับปริมาณที่หมวดแอนิเมชัน)"; wide: true
                        Segment { key: "ov_word_anim"; options: [{v:"none",t:"ไม่มี"},{v:"word",t:"ทั้งคำ"},{v:"char",t:"ทีละตัวอักษร"}] } }
                    Row2 { label: "ชดเชยความหน่วง"; hint: "เสียงร้องไปแล้วเนื้อพึ่งขึ้น = เพิ่มค่านี้ · เวลาที่ YouTube บอกคือเวลาถอดรหัส ไม่ใช่เวลาที่เสียงออกหูฟังจริง"; SSlider { key: "ov_latency_ms"; from: -500; to: 800; step: 10; decimals: 0; unit: " ms" } }
                    Row2 { label: "เลื่อนบรรทัดล่วงหน้า"; hint: "ถ้ารู้สึกว่าบรรทัดเลื่อนช้ากว่าเสียง เพิ่มค่านี้"; SSlider { key: "ov_scroll_lead_s"; from: 0; to: 1; step: 0.05; decimals: 2; unit: " วิ" } }
                    Row2 { label: "ลดการเคลื่อนไหว"; hint: "ปิดการเลื่อน/ย่อ/ลอย ใช้การเปลี่ยนทันที"; SSwitch { key: "ov_reduced_motion" } }
                }
                Card { title: "เนื้อเพลงและ AI"
                    Row2 { label: "ให้ AI จัดเวลาจากเสียงจริง"; hint: "เนื้อเพลงยึดตามเว็บ AI ฟังเสียงเพื่อทำให้เวลาตรง (ใช้การ์ดจอ NVIDIA)"; SSwitch { key: "ai_enabled" } }
                    Row2 { label: "แปลเป็นภาษาไทย"; hint: "เพลงที่ไม่ใช่ภาษาไทยแปลด้วยโมเดลในเครื่อง · คำแปลแสดงเมื่อกดปุ่มแปล"; SSwitch { key: "ai_translate" } }
                    Row2 { label: "ตัดบรรทัดที่ยาวเกินให้สั้นลง"; hint: "แบบ Apple Music — ตัดที่วรรคตอน/คำเชื่อม (มีผลตอนโหลดเพลงครั้งถัดไป)"; SSwitch { key: "ls_split_long_lines" } }
                    Row2 { label: "ปรับเวลาเนื้อเพลงของเพลงนี้"; hint: "บวก = เนื้อเพลงช้าลง · จำแยกตามเพลง"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "−0.1"; onClicked: player.adjustOffset(-0.1) }
                            Text { anchors.verticalCenter: parent.verticalCenter; width: 64; horizontalAlignment: Text.AlignHCenter
                                text: (player.lyricsOffset >= 0 ? "+" : "") + player.lyricsOffset.toFixed(1) + " วิ"; color: win.fg; font.pixelSize: 14 }
                            Pill { label: "+0.1"; onClicked: player.adjustOffset(0.1) }
                            Pill { label: "รีเซ็ต"; onClicked: player.resetOffset() }
                        } }
                }
                Card { title: "โปรแกรม"
                    Row2 { label: "ปุ่มปิด (กากบาท) = ซ่อนลงถาดระบบ"; hint: "ปิดตัวเลือกนี้ = ปุ่มปิดจะปิดโปรแกรมเลย"; SSwitch { key: "st_close_to_tray" } }
                    Row2 { label: "เปิดพร้อม Windows"; hint: "เปิดแล้วอยู่ที่ถาดระบบ ไม่เด้งหน้าต่างตั้งค่า"; SSwitch { key: "st_launch_with_windows" } }
                }
            }

            // ---------------- แหล่งเนื้อเพลง ----------------
            Column {
                property int pgIdx: 10; visible: win.show(10); width: parent.width; spacing: 6
                Intro { text: "แอปค้นเนื้อเพลงจากหลายแหล่งพร้อมกัน แล้วเทียบกันเอง — ฉบับที่ตรงกับแหล่งอื่นมากที่สุดจะถูกเลือกก่อน (ถ้าไม่ถูกใจกด \"ตัวอื่น\" ได้) · AI ใช้จัดเวลาให้ตรงกับเสียงเท่านั้น ไม่แก้ข้อความ" }
                Card { title: "แหล่งที่ใช้ค้น"
                    note: "ปิดทุกแหล่ง = ไม่ค้นเว็บเลย (ใช้ AI ถอดเสียงเป็นเนื้อเพลงอย่างเดียว) · แหล่งที่มีเวลาทีละคำ (NetEase/QQ) ให้ไฮไลต์ละเอียดกว่า"
                    Row2 { label: "LRCLIB"; hint: "เนื้อเพลงซิงก์ทีละบรรทัดแบบเปิด ครอบคลุมเพลงสากลดี"; SSwitch { key: "ls_src_lrclib" } }
                    Row2 { label: "NetEase"; hint: "มีเวลาทีละคำ เพลงจีน/เกาหลี/สากล"; SSwitch { key: "ls_src_netease" } }
                    Row2 { label: "QQ Music"; hint: "มีเวลาทีละคำ เพลงจีน/เกาหลี/สากล"; SSwitch { key: "ls_src_qqmusic" } }
                    Row2 { label: "คำบรรยาย YouTube"; hint: "คำบรรยายของวิดีโอนั้นเอง เวลาตรงกับวิดีโอแน่นอน (เหมาะกับ MV/คลิปที่ตัดต่อ)"; SSwitch { key: "ls_src_youtube_subs" } }
                    Row2 { label: "Lyrics.ovh"; hint: "ข้อความล้วนไม่มีเวลา ใช้เป็นตัวช่วยเทียบความถูกต้อง"; SSwitch { key: "ls_src_lyrics_ovh" } }
                    Row2 { label: "ถอดเสียงเองเมื่อไม่พบเนื้อเพลง"; hint: "AI ฟังเสียงแล้วเขียนเนื้อเพลงให้ (อาจมีคำผิด)"; SSwitch { key: "ls_allow_ai_transcribe" } }
                }
                Card { title: "การแบ่งบรรทัด"
                    Row2 { label: "ตัดบรรทัดที่ยาวเกินให้สั้นลง"; hint: "ตัดที่เครื่องหมายวรรคตอน/คำเชื่อม (and, but, และ, แต่ ...) · บรรทัดที่มีคำแปลไม่ตัด"; SSwitch { key: "ls_split_long_lines" } }
                    Row2 { label: "ความกว้างสูงสุดของบรรทัด"; hint: "น้อย = บรรทัดสั้น ตัดบ่อย · ตัวอักษร CJK นับเป็น 2"; adv: true; SSlider { key: "ls_max_line_width"; from: 20; to: 120; step: 2; decimals: 0 } }
                }
                Card { title: "เพลงตอนนี้"
                    Row2 { label: "เพลงตอนนี้"; hint: player.title.length > 0 ? player.title + " — " + player.artist : "ยังไม่มี" }
                    Row2 { label: "แหล่งที่ใช้อยู่"; hint: player.sourceLabel.length > 0 ? player.sourceLabel : "-" }
                    Row2 { label: "เปลี่ยน/โหลดใหม่"; hint: "ตัวอื่น = ฉบับอันดับถัดไป · โหลดใหม่ = ค้นทุกแหล่งอีกรอบ"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "ตัวอื่น"; onClicked: player.nextCandidate() }
                            Pill { label: "โหลดใหม่"; onClicked: player.refreshLyrics() }
                        } }
                }
            }

            // ---------------- ทั่วไป ----------------
                Intro { text: "" }
            Column {
                property int pgIdx: 0; visible: win.show(0); width: parent.width; spacing: 6
                Intro { text: "ตั้งค่าพื้นฐานของโปรแกรม: การเปิดตอนเริ่มเครื่อง และปุ่มปิดหน้าต่าง · ทุกตัวเลือกที่ปรับแล้วจะมีปุ่ม ↺ ข้างๆ กดเพื่อคืนค่าเริ่มต้นเฉพาะข้อนั้น" }
                Card { title: "ชุดการตั้งค่าที่บันทึกไว้"
                    note: "บันทึกหน้าตาและพฤติกรรมของเนื้อเพลงทั้งหมด (โหมดเต็ม หน้าต่างลอย ตัวอักษร ธีม เนื้อเพลง แอนิเมชัน) เป็นชื่อๆ แล้วสลับกลับมาใช้ได้ทันที · ไม่รวมคีย์ลัด การเริ่มต้นระบบ และตำแหน่งหน้าต่าง"
                    Row2 { label: "บันทึกการตั้งค่าตอนนี้เป็นชุดใหม่"; hint: "ชื่อซ้ำ = เขียนทับชุดเดิม"; wide: true
                        Item {
                            width: parent.width; height: 34
                            TextField {
                                id: presetName
                                objectName: "presetNameField"
                                x: 0; width: parent.width - saveBtn.width - 10; height: 34
                                placeholderText: "ตั้งชื่อชุด เช่น ดูตอนกลางคืน"
                                placeholderTextColor: win.fg2
                                color: win.fg; font.pixelSize: 13; font.family: cfg.look_font_family; selectByMouse: true
                                maximumLength: 40
                                background: Rectangle { radius: 8; color: win.field; border.width: presetName.activeFocus ? 1 : 0; border.color: win.accent }
                                onAccepted: saveBtn.save()
                            }
                            Pill {
                                id: saveBtn
                                objectName: "presetSaveButton"
                                anchors.right: parent.right
                                label: "บันทึก"
                                function save() {
                                    var err = settingsBridge.savePreset(presetName.text)
                                    presetMsg.text = err.length > 0 ? err : "บันทึกชุด \"" + presetName.text.trim() + "\" แล้ว"
                                    presetMsg.isError = err.length > 0
                                    if (err.length === 0) presetName.text = ""
                                }
                                onClicked: save()
                            }
                        } }
                    Row2 { label: ""; visible: presetMsg.text.length > 0 && want
                        Text { id: presetMsg; property bool isError: false; width: parent.width; wrapMode: Text.Wrap
                            color: isError ? "#FCA5A5" : win.accent; font.pixelSize: 12; font.family: cfg.look_font_family } }
                    Row2 { label: "ยังไม่มีชุดที่บันทึกไว้"; visible: settingsBridge.presetNames.length === 0 && want }
                    Repeater {
                        model: settingsBridge.presetNames
                        Row2 {
                            id: pr
                            required property string modelData
                            property bool confirmDelete: false
                            label: modelData
                            Timer { id: confirmTimer; interval: 3000; onTriggered: pr.confirmDelete = false }
                            Row { anchors.right: parent.right; spacing: 6
                                Pill { label: "ใช้ชุดนี้"; onClicked: settingsBridge.loadPreset(pr.modelData) }
                                Pill { label: "บันทึกทับ"; onClicked: { settingsBridge.savePreset(pr.modelData); presetMsg.isError = false; presetMsg.text = "บันทึกทับชุด \"" + pr.modelData + "\" แล้ว" } }
                                Pill { label: pr.confirmDelete ? "ยืนยันลบ?" : "ลบ"; active: pr.confirmDelete
                                    onClicked: { if (pr.confirmDelete) settingsBridge.deletePreset(pr.modelData); else { pr.confirmDelete = true; confirmTimer.restart() } } }
                            }
                        }
                    }
                }
                Card { title: "การเริ่มต้น"
                    Row2 { label: "เปิดพร้อม Windows"; hint: "เปิดแล้วอยู่ที่ถาดระบบ ไม่เด้งหน้าต่างตั้งค่า"; SSwitch { key: "st_launch_with_windows" } }
                    Row2 { label: "เปิดโปรแกรมแล้วเข้าโหมดเต็มก่อน"; hint: "ปิด = จำสถานะครั้งก่อน (หน้าต่างลอยหรือโหมดเต็ม)"; SSwitch { key: "fw_start_full" } }
                    Row2 { label: "ปุ่มปิด = ซ่อนลงถาดระบบ"; hint: "ปิดตัวเลือกนี้ = ปุ่มปิดของหน้าตั้งค่า/โหมดเต็มจะปิดโปรแกรมเลย"; SSwitch { key: "st_close_to_tray" } }
                    Row2 { label: "ส่งเพลงจาก YouTube อัตโนมัติ"; hint: "ส่วนขยายรายงานเพลงที่เล่นอยู่ให้โปรแกรมเอง"; SSwitch { key: "st_extension_sends_current_video" } }
                }
                Card { title: "ข้อมูลและโปรแกรม"
                    Row2 { label: "โฟลเดอร์ข้อมูล"; hint: settingsBridge.dataDir
                        Pill { anchors.right: parent.right; label: "เปิดโฟลเดอร์"; onClicked: Qt.openUrlExternally("file:///" + settingsBridge.dataDir) } }
                    Row2 { label: "คืนค่าเริ่มต้นทั้งหมด"; hint: "ไม่ลบแคชเนื้อเพลง"
                        Pill { anchors.right: parent.right; label: "รีเซ็ตการตั้งค่า"; onClicked: settingsBridge.resetAll() } }
                    Row2 { label: "ออกจากโปรแกรม"
                        Pill { anchors.right: parent.right; label: "ปิดโปรแกรม"; onClicked: win.quitRequested() } }
                    Row2 { label: "เกี่ยวกับ"; hint: "SyncLyrics — เนื้อเพลงตามเพลงใน YouTube (โปรแกรมไม่เล่นเสียงเอง เล่น/หยุด/ข้าม/ปรับเสียงสั่งไปที่แท็บ YouTube)" }
                }
            }

            // ---------------- โหมดเต็ม ----------------
            Column {
                property int pgIdx: 1; visible: win.show(1); width: parent.width; spacing: 6
                Intro { text: "หน้าต่างเต็มแบบ Apple Music: ปรับการจัดวาง ขนาดปก เสียง และการซ่อนปุ่มเมื่อเมาส์นิ่ง" }
                Card { title: "หน้าต่าง"
                    Row2 { label: "เปิดโหมดเต็ม"; hint: "หน้าต่างปกติ ย่อ/ขยาย/ปิดได้ · กด F หรือ F11 เพื่อเต็มจอ · Esc ออก"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: cfg.fw_open ? "ปิดโหมดเต็ม" : "เปิดโหมดเต็ม"; onClicked: cfg.fw_open = !cfg.fw_open }
                            Pill { label: "เต็มจอ"; active: cfg.fw_fullscreen; onClicked: { cfg.fw_open = true; cfg.fw_fullscreen = !cfg.fw_fullscreen } }
                        } }
                    Row2 { label: "เข้าโหมดเต็มทุกครั้งที่เปิดโปรแกรม"; SSwitch { key: "fw_start_full" } }
                    Row2 { label: "เปิดมาแบบขยายเต็มจอ"; hint: "ขยายเต็มหน้าจอแต่ยังมีแถบชื่อและแถบงาน (ไม่ใช่ fullscreen) · ปิด = เปิดเป็นหน้าต่างขนาดปกติ"; SSwitch { key: "fw_maximized" } }
                    Row2 { label: "ซ่อนปุ่มบนและป้ายแหล่งเนื้อเพลงเมื่อเมาส์นิ่ง"; hint: "ขยับเมาส์แล้วกลับมาเอง (เต็มจอซ่อนตัวเมาส์ด้วย)"; SSwitch { key: "fw_idle_hide" } }
                    Row2 { label: "นิ่งนานกี่วินาทีถึงซ่อน"; SSlider { key: "fw_idle_hide_s"; from: 1; to: 30; step: 1; decimals: 0; unit: " วิ" } }
                }
                Card { title: "เนื้อเพลงและปก"
                    Row2 { label: "แสดงเนื้อเพลง"; hint: "ปิด = เห็นแต่ปกใหญ่กลางหน้าต่าง (ปุ่มเนื้อเพลงที่แถบบนหรือกด L)"; SSwitch { key: "fw_lyrics_visible" } }
                    Row2 { label: "การจัดวางเนื้อเพลง"; hint: "Apple Music = ชิดซ้าย"
                        Segment { key: "fw_align"; options: [{v:"left",t:"ชิดซ้าย"},{v:"center",t:"กึ่งกลาง"}] } }
                    Row2 { label: "ขนาดเนื้อเพลง"; hint: "คูณกับขนาดอัตโนมัติตามความสูงหน้าต่าง (ปุ่ม + / − ก็ได้)"; SSlider { key: "fw_font_scale"; from: 0.5; to: 2.0; step: 0.05 } }
                    Row2 { label: "ขนาดปก"; SSlider { key: "fw_cover_scale"; from: 0.6; to: 1.0; step: 0.05 } }
                    Row2 { label: "แสดงคำแปล"; SSwitch { key: "fw_show_translation" } }
                    Row2 { label: "ความจางของบรรทัดที่ไม่ได้ร้อง"; hint: "ต่ำ = บรรทัดอื่นจางมาก · 0 = เห็นเฉพาะบรรทัดที่กำลังร้อง"; SSlider { key: "fw_inactive_opacity"; from: 0; to: 1; step: 0.05 } }
                    Row2 { label: "เบลอบรรทัดที่ไม่ได้ร้อง"; hint: "ยิ่งไกลจากบรรทัดที่ร้องยิ่งเบลอ (แบบ Apple Music) · 0 = ไม่เบลอ"; SSlider { key: "fw_blur"; from: 0; to: 1; step: 0.05 } }
                    Row2 { label: "จางเพิ่มตามระยะห่าง"; hint: "บรรทัดที่ไกลจากบรรทัดที่ร้องจางลงอีก"; SSlider { key: "fw_falloff"; from: 0; to: 0.3; step: 0.01 } }
                    Row2 { label: "ขอบบน/ล่างจางหาย"; hint: "ความกว้างของแถบที่เนื้อเพลงค่อยๆ จางก่อนถึงขอบ (แบบ Apple Music) 0 = ตัดแข็ง"; SSlider { key: "fw_edge_fade"; from: 0; to: 0.4; step: 0.01 } }
                    Row2 { label: "ขอบบน/ล่างเบลอ"; hint: "เบลอเพิ่มตอนเข้าใกล้ขอบ ช่วยให้ไม่เห็นรอยตัด"; SSlider { key: "fw_edge_blur"; from: 0; to: 1; step: 0.05 } }
                    Row2 { label: "แถบวอลลุ่ม"; hint: "ปรับเสียงของแท็บ YouTube (ปุ่ม ↑ ↓ M ก็ได้)"; SSwitch { key: "fw_show_volume" } }
                }
                Card { title: "สีเนื้อเพลง เฉพาะโหมดเต็ม (ปกติตามหมวดตัวอักษร)"
                    Row2 { label: "สีบรรทัดที่ร้อง"; adv: true; hint: "สีของคำที่ร้องแล้วและบรรทัดที่กำลังร้อง"; wide: true; SColor { key: "fw_text_color" } }
                    Row2 { label: "สีไฮไลต์"; adv: true; hint: "ใช้กับไฮไลต์แบบทีละคำ/เรืองแสง (สีแสงเรืองตั้งที่หมวดแอนิเมชัน)"; wide: true; SColor { key: "fw_accent_color" } }
                    Row2 { label: "สีบรรทัดที่ยังไม่ร้อง"; adv: true; hint: "ความจางตั้งที่ \"ความจางของบรรทัดที่ไม่ได้ร้อง\""; wide: true; SColor { key: "fw_inactive_color" } }
                    Row2 { label: "สีคำแปล"; adv: true; wide: true; SColor { key: "fw_secondary_color" } }
                }
                Card { title: "พื้นหลัง"
                    Row2 { label: "รูปแบบ"; hint: "ไหลลื่นสีจากปกเพลง หรือสีเรียบ"
                        Segment { key: "fw_background"; options: [{v:"fluid",t:"ไหลลื่นตามสีปก"},{v:"solid",t:"สีเรียบ"}] } }
                    Row2 { label: "ความสว่าง"; SSlider { key: "fw_brightness"; from: 0.3; to: 1.3 } }
                }
            }

            // ---------------- หน้าต่างลอย ----------------
            Column {
                property int pgIdx: 2; visible: win.show(2); width: parent.width; spacing: 6
                Intro { text: "หน้าต่างเนื้อเพลงเล็กที่ลอยอยู่บนจอ (ใช้ตอนไม่ได้เปิดโหมดเต็ม): ตำแหน่ง ขนาด และการล็อก" }
                Card { title: "การแสดงผล"
                    Row2 { label: "แสดงหน้าต่างเนื้อเพลงลอย"; hint: "เห็นเมื่อไม่ได้เปิดโหมดเต็ม"; SSwitch { key: "ov_visible" } }
                    Row2 { label: "โหมดการแสดง"; hint: "เล็ก = บรรทัดเดียว (พื้นโปร่งมาก) · โฟกัส = หลายบรรทัด"
                        Segment { key: "ov_mode"; options: [{v:"minimal",t:"เล็ก"},{v:"focus",t:"โฟกัส"}] } }
                    Row2 { label: "จำนวนบรรทัด (โหมดโฟกัส)"; SSlider { key: "ov_visible_lines"; from: 1; to: 9; step: 1; decimals: 0 } }
                    Row2 { label: "การจัดวาง"
                        Segment { key: "ov_align"; options: [{v:"left",t:"ซ้าย"},{v:"center",t:"กลาง"},{v:"right",t:"ขวา"}] } }
                    Row2 { label: "แถบควบคุมตอนชี้เมาส์"; SSwitch { key: "ov_hover_controls" } }
                }
                Card { title: "พฤติกรรม"
                    Row2 { label: "อยู่บนสุดเสมอ"; SSwitch { key: "ov_always_on_top" } }
                    Row2 { label: "ล็อกตำแหน่งและขนาด"; hint: "กันลาก/ปรับขนาดพลาดตอนอ่าน"; SSwitch { key: "ov_locked" } }
                    Row2 { label: "คลิกทะลุหน้าต่าง"; hint: "เมาส์ผ่านไปที่โปรแกรมด้านหลัง ปิดได้จากถาดระบบหรือคีย์ลัด"; SSwitch { key: "ov_click_through" } }
                    Row2 { label: "จำตำแหน่งและขนาดล่าสุด"; SSwitch { key: "ov_remember_position" } }
                }
                Card { title: "ตำแหน่งและขนาด"
                    Row2 { label: "ย้ายไปที่"; wide: true
                        Flow { width: parent.width; spacing: 6
                            Pill { label: "กลางจอ"; onClicked: win.placeRequested("center") }
                            Pill { label: "กึ่งกลางแนวนอน"; onClicked: win.placeRequested("center_h") }
                            Pill { label: "บนกลาง"; onClicked: win.placeRequested("top_center") }
                            Pill { label: "ล่างกลาง"; onClicked: win.placeRequested("bottom_center") }
                            Pill { label: "บนซ้าย"; onClicked: win.placeRequested("top_left") }
                            Pill { label: "บนขวา"; onClicked: win.placeRequested("top_right") }
                            Pill { label: "ล่างซ้าย"; onClicked: win.placeRequested("bottom_left") }
                            Pill { label: "ล่างขวา"; onClicked: win.placeRequested("bottom_right") }
                        } }
                    Row2 { label: "ตำแหน่งเริ่มต้น"; hint: "ใช้เมื่อยังไม่เคยจำตำแหน่ง หรือปิดการจำตำแหน่ง"; adv: true; wide: true
                        Segment { key: "ov_start_position"; options: [{v:"bottom_center",t:"ล่างกลาง"},{v:"top_center",t:"บนกลาง"},{v:"center",t:"กลางจอ"},{v:"top_left",t:"บนซ้าย"},{v:"top_right",t:"บนขวา"},{v:"bottom_left",t:"ล่างซ้าย"},{v:"bottom_right",t:"ล่างขวา"}] } }
                    Row2 { label: "จอที่แสดง"; hint: "เลือกแล้วหน้าต่างย้ายไปจอนั้นทันที"; wide: true
                        Flow { width: parent.width; spacing: 6
                            Repeater {
                                model: Qt.application.screens
                                Pill {
                                    required property int index
                                    required property var modelData
                                    label: "จอ " + (index + 1) + " (" + modelData.width + "×" + modelData.height + ")"
                                    active: cfg.ov_monitor === index
                                    onClicked: cfg.ov_monitor = index
                                }
                            }
                        } }
                    Row2 { label: "ขนาดสำเร็จรูป (โหมดปัจจุบัน)"
                        Row { anchors.right: parent.right; spacing: 6
                            Pill { label: "เล็ก"; onClicked: cfg.ov_mode === "minimal" ? win.setSize(560, 90) : win.setSize(560, 190) }
                            Pill { label: "กลาง"; onClicked: cfg.ov_mode === "minimal" ? win.setSize(760, 110) : win.setSize(760, 230) }
                            Pill { label: "ใหญ่"; onClicked: cfg.ov_mode === "minimal" ? win.setSize(1000, 140) : win.setSize(1000, 300) }
                        } }
                    Row2 { label: "ความกว้าง"; adv: true; SSlider { key: "ov_w_" + cfg.ov_mode; from: 240; to: 2400; step: 10; decimals: 0; unit: " px" } }
                    Row2 { label: "ความสูง"; adv: true; SSlider { key: "ov_h_" + cfg.ov_mode; from: 60; to: 1600; step: 10; decimals: 0; unit: " px" } }
                    Row2 { label: "คืนขนาดเริ่มต้น"; Pill { anchors.right: parent.right; label: "คืนขนาด"; onClicked: settingsBridge.resetSize() } }
                }
            }

            // ---------------- ตัวอักษร ----------------
            Column {
                property int pgIdx: 3; visible: win.show(3); width: parent.width; spacing: 6
                Intro { text: "หน้าตาตัวอักษรของเนื้อเพลง: ดูผลที่ตัวอย่างด้านบนได้ทันที" }
                Card { title: "ฟอนต์และขนาด"
                    Row2 { label: "ฟอนต์"; hint: "ฟอนต์หลัก SF Thonburi (ไม่มี = ใช้ตัวสำรองให้เอง)"; resetKey: "look_font_family"
                        ComboBox {
                            id: fontBox
                            width: parent.width
                            model: Qt.fontFamilies()
                            currentIndex: Math.max(0, model.indexOf(cfg.look_font_family))
                            onActivated: cfg.look_font_family = model[currentIndex]
                            background: Rectangle { radius: 8; color: win.field; border.width: fontBox.activeFocus ? 2 : 0; border.color: "#FFFFFF" }
                            contentItem: Text { leftPadding: 10; text: cfg.look_font_family; color: win.fg; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                        } }
                    Row2 { label: "ขนาดตัวอักษร (หน้าต่างลอย)"; SSlider { key: "ov_font_size"; from: 12; to: 120; step: 1; decimals: 0; unit: " px" } }
                    Row2 { label: "น้ำหนักตัวอักษร"; SSlider { key: "ov_font_weight"; from: 100; to: 900; step: 100; decimals: 0 } }
                    Row2 { label: "น้ำหนักบรรทัดปัจจุบัน"; hint: "หนาขึ้นกี่หน่วยจากปกติ"; adv: true; SSlider { key: "ov_weight_boost"; from: 0; to: 300; step: 50; decimals: 0 } }
                    Row2 { label: "ระยะห่างบรรทัด"; SSlider { key: "ov_line_spacing"; from: 0.8; to: 2.5; step: 0.05 } }
                    Row2 { label: "ระยะห่างตัวอักษร"; adv: true; SSlider { key: "ov_letter_spacing"; from: -3; to: 12; step: 0.5; decimals: 1 } }
                    Row2 { label: "ความกว้างข้อความ"; hint: "สัดส่วนของความกว้างหน้าต่าง"; SSlider { key: "ov_text_width"; from: 0.4; to: 1.0; step: 0.05 } }
                    Row2 { label: "เงาตัวอักษร"; adv: true; SSlider { key: "ov_text_shadow"; from: 0; to: 1 } }
                }
                Card { title: "สี"
                    note: "สีที่ตั้งตรงนี้ใช้ทั้งหน้าต่างลอยและโหมดเต็ม · อยากให้โหมดเต็มสีต่างออกไป เปิดโหมดละเอียดแล้วตั้งที่หมวด \"โหมดเต็ม\""
                    Row2 { label: "สีข้อความ"; wide: true; SColor { key: "ov_text_color" } }
                    Row2 { label: "สีไฮไลต์"; wide: true; SColor { key: "ov_accent_color" } }
                    Row2 { label: "สีบรรทัดที่ยังไม่ร้อง"; wide: true; SColor { key: "ov_inactive_color" } }
                    Row2 { label: "สีคำแปล"; adv: true; wide: true; SColor { key: "ov_secondary_color" } }
                    Row2 { label: "ความโปร่งใสตัวอักษร"; adv: true; SSlider { key: "ov_text_opacity"; from: 0.2; to: 1 } }
                    Row2 { label: "ความจางบรรทัดอื่น"; adv: true; SSlider { key: "ov_inactive_opacity"; from: 0.05; to: 1 } }
                }
            }

            // ---------------- พื้นหลังและธีม ----------------
            Column {
                property int pgIdx: 4; visible: win.show(4); width: parent.width; spacing: 6
                Intro { text: "สีและความโปร่งใสของหน้าต่างเนื้อเพลงลอย (โหมดเต็มใช้สีจากปกเพลงอัตโนมัติ)" }
                Card { title: "ธีม"
                    Row2 { label: "ธีมสำเร็จรูป"; hint: "แก้สีเองเมื่อไหร่จะกลายเป็น \"กำหนดเอง\""; wide: true
                        Segment { key: "ov_theme"; options: [{v:"soft_dark",t:"Soft Dark"},{v:"pure_black",t:"Pure Black"},{v:"frosted",t:"Frosted Glass"},{v:"minimal_transparent",t:"Minimal Transparent"},{v:"light",t:"Light"},{v:"custom",t:"กำหนดเอง"}] } }
                }
                Card { title: "พื้นหลังหน้าต่างลอย"
                    Row2 { label: "รูปแบบพื้นหลัง"; wide: true
                        Segment { key: "ov_bg_style"; options: [{v:"transparent",t:"โปร่งใส"},{v:"frosted",t:"กระจกฝ้า"},{v:"soft_dark",t:"ดำนุ่ม"},{v:"solid",t:"ทึบ"},{v:"gradient",t:"Gradient"},{v:"custom",t:"สีกำหนดเอง"}] } }
                    Row2 { label: "เบลอฉากหลังจริง"; hint: "ใช้กับพื้นหลัง \"กระจกฝ้า\" (Windows acrylic) — ปิดหรือระบบไม่รองรับ = พื้นโปร่งแสงธรรมดา"; SSwitch { key: "ov_blur_behind" } }
                    Row2 { label: "สีพื้นหลัง"; wide: true; SColor { key: "ov_bg_color" } }
                    Row2 { label: "สีที่สอง (Gradient)"; adv: true; wide: true; SColor { key: "ov_bg_color2" } }
                    Row2 { label: "ความโปร่งใสพื้นหลัง"; hint: "แยกจากตัวอักษร — ตัวอักษรยังอ่านง่ายแม้พื้นหลังโปร่งมาก"; SSlider { key: "ov_bg_opacity"; from: 0; to: 1 } }
                    Row2 { label: "ความโปร่งใสทั้งหน้าต่าง"; adv: true; SSlider { key: "ov_window_opacity"; from: 0.3; to: 1 } }
                    Row2 { label: "ความโปร่งใสขอบ"; adv: true; SSlider { key: "ov_border_opacity"; from: 0; to: 0.6 } }
                    Row2 { label: "เงาหน้าต่าง"; adv: true; SSlider { key: "ov_shadow"; from: 0; to: 1 } }
                    Row2 { label: "มุมโค้ง"; SSlider { key: "ov_corner_radius"; from: 0; to: 60; step: 1; decimals: 0; unit: " px" } }
                }
            }

            // ---------------- เนื้อเพลง ----------------
            Column {
                property int pgIdx: 5; visible: win.show(5); width: parent.width; spacing: 6
                Intro { text: "วิธีอ่านเนื้อเพลง: ไฮไลต์ การเลื่อน การคลิกกรอ และคำแปล" }
                Card { title: "การอ่าน"
                    Row2 { label: "รูปแบบไฮไลต์"; hint: "ถ้าเพลงมีเวลาแค่ระดับบรรทัด ระบบจะประมาณเวลาทีละคำ (ยังไม่ใช่เวลาจริง)"; wide: true
                        Segment { key: "ov_highlight"; options: [{v:"fill",t:"เติมสี"},{v:"word",t:"ทีละคำ"},{v:"glow",t:"เรืองแสง"},{v:"line",t:"ทั้งบรรทัด"}] } }
                    Row2 { label: "จับบรรทัดที่ร้องต่อกันเป็นท่อนเดียว"; hint: "บรรทัดที่ร้องต่อเนื่องกัน (เช่น ประโยคเดียวที่ขึ้นบรรทัดใหม่) จะค้างความสว่างไว้ ไม่เลื่อนจอ แล้วจางพร้อมกันเมื่อจบท่อน"; SSwitch { key: "ov_group_lines" } }
                    Row2 { label: "ห่างกันได้ไม่เกินกี่วินาทีถึงนับเป็นท่อนเดียวกัน"; adv: true; SSlider { key: "ov_group_gap_s"; from: 0.1; to: 2.0; step: 0.1; decimals: 1; unit: " วิ" } }
                    Row2 { label: "เลื่อนอัตโนมัติ"; hint: "เลื่อนอ่านเองได้ แล้วจะกลับมาตามเพลง"; SSwitch { key: "ov_auto_scroll" } }
                    Row2 { label: "กลับมาตามเพลงหลังเลื่อนเอง"; SSlider { key: "ov_resume_s"; from: 1; to: 15; step: 1; decimals: 0; unit: " วิ" } }
                    Row2 { label: "คลิกบรรทัดเพื่อกรอ"; hint: "กรอวิดีโอ YouTube ไปที่บรรทัดนั้น"; SSwitch { key: "ov_click_seek" } }
                    Row2 { label: "แสดงที่มาของเนื้อเพลง"; hint: "ป้ายเล็กมุมขวาล่าง (ซ่อนเองเมื่อเมาส์นิ่งในโหมดเต็ม)"; SSwitch { key: "ov_show_source" } }
                }
                Card { title: "คำแปล"
                    Row2 { label: "แสดงคำแปล"; hint: "แสดงเมื่อมีคำแปลภาษาไทย (ภาษาอื่นกดปุ่มแปลที่แถบควบคุม)"; SSwitch { key: "ov_show_translation" } }
                    Row2 { label: "ขนาดคำแปล"; SSlider { key: "ov_translation_size"; from: 0.3; to: 1.2 } }
                    Row2 { label: "แสดงคำอ่าน (romanization)"; adv: true; SSwitch { key: "look_show_romanization" } }
                }
            }

            // ---------------- แอนิเมชัน ----------------
            Column {
                property int pgIdx: 6; visible: win.show(6); width: parent.width; spacing: 6
                Intro { text: "การเคลื่อนไหวของเนื้อเพลง: เริ่มจากเลือกชุดสำเร็จรูป แล้วค่อยปรับต่อ · เปิดโหมดละเอียดที่มุมขวาบนเพื่อดูตัวเลือกเพิ่ม · ผลเห็นที่ตัวอย่างด้านบน" }
                Card { title: "ชุดสำเร็จรูป"
                    Row2 { label: "ชุดแอนิเมชัน"; hint: "เลือกชุดแล้วปรับต่อเองได้ (ปรับเมื่อไหร่ชุดจะเป็น \"กำหนดเอง\")"; wide: true
                        Segment { key: "ov_anim_preset"; options: [{v:"smooth",t:"นุ่มนวล (แบบ Apple)"},{v:"balanced",t:"สมดุล"},{v:"bouncy",t:"เด้งนิดๆ"},{v:"snappy",t:"ฉับไว"},{v:"none",t:"ไม่เคลื่อนไหว"},{v:"custom",t:"กำหนดเอง"}] } }
                    Row2 { label: "ลดการเคลื่อนไหว"; hint: "ปิดการเลื่อน/ย่อ/ลอย ใช้การเปลี่ยนทันที"; SSwitch { key: "ov_reduced_motion" } }
                }
                Card { title: "คำที่กำลังร้อง (คาราโอเกะ)"
                    Row2 { label: "ลอย / ขยาย / เรืองแสง"; wide: true
                        hint: ({ none: "คำอยู่นิ่ง มีแค่การเติมสี",
                                 word: "ทั้งคำลอย/ขยาย/เรืองแสงทันทีที่ร้องถึงคำนั้น (ไม่ต้องรอร้องจบคำ)",
                                 char: "ทีละตัวอักษร: ตัวที่การเติมสีไล่ผ่านจะลอย/ขยาย/เรืองแสงตามไปเรื่อยๆ" })[cfg.ov_word_anim]
                        Segment { key: "ov_word_anim"; options: [{v:"none",t:"ไม่มี"},{v:"word",t:"ทั้งคำ"},{v:"char",t:"ทีละตัวอักษร"}] } }
                    Row2 { label: "ระยะลอย"; hint: "ลอยสูงกี่พิกเซล · 0 = ไม่ลอย (ใช้ร่วมกับขยาย/เรืองแสงได้)"; SSlider { key: "ov_lift_px"; from: 0; to: 14; step: 0.5; decimals: 1; unit: " px" } }
                    Row2 { label: "ขนาดที่ขยาย"; hint: "1.00 = ไม่ขยาย · ค่ามากๆ ตัวอักษรข้างเคียงจะซ้อนกัน"; SSlider { key: "ov_word_scale"; from: 1.0; to: 1.35; step: 0.01 } }
                    Row2 { label: "ความแรงของแสง"; hint: "0 = ไม่มีแสง · เรืองเฉพาะส่วนที่เติมสีแล้ว"; SSlider { key: "ov_glow_strength"; from: 0; to: 1 } }
                    Row2 { label: "สีของแสงเรืองรอบคำ"; hint: "ใช้กับแสงของคำ และคำเน้น"; wide: true; SColor { key: "ov_glow_color" } }
                    Row2 { label: "ค้างไว้จนจบบรรทัด"; hint: "คำที่ร้องแล้วยังลอย/ขยาย/เรืองแสงค้างอยู่จนบรรทัดจบ (ปิด = คืนกลับหลังหน่วงเวลาด้านล่าง)"; SSwitch { key: "ov_word_stay" } }
                    Row2 { label: "ค้างไว้หลังร้องจบ"; hint: "ใช้เมื่อปิด \"ค้างไว้จนจบบรรทัด\" — ร้องคำนั้นจบแล้วค้างอีกเท่านี้ก่อนเริ่มคืน"; SSlider { key: "ov_word_hold_ms"; from: 0; to: 2000; step: 50; decimals: 0; unit: " ms" } }
                    Row2 { label: "เวลาที่ค่อยๆ กลับ"; hint: "ลอยลงและแสงจางลงช้าแค่ไหน (มาก = นุ่ม ค่อยๆ คืน, 0 = หายทันที)"; SSlider { key: "ov_word_release_ms"; from: 0; to: 3000; step: 50; decimals: 0; unit: " ms" } }
                    Row2 { label: "เวลาที่ค่อยๆ ขึ้น"; hint: "โหมดทั้งคำ: ลอยขึ้น/แสงสว่างขึ้นเร็วแค่ไหน"; adv: true; SSlider { key: "ov_word_anim_ms"; from: 60; to: 1200; step: 20; decimals: 0; unit: " ms" } }
                    Row2 { label: "จังหวะการเคลื่อนไหว"; wide: true; adv: true
                        hint: ({ smooth: "เริ่มเร็วแล้วค่อยๆ ช้าลงจนหยุดนุ่มๆ (แนะนำ)", gentle: "เริ่มช้า เร็วกลางทาง จบช้า",
                                 spring: "เลยจุดหมายนิดแล้วดีดกลับ (มีเด้ง)", linear: "ความเร็วเท่ากันตลอด" })[cfg.ov_word_ease]
                        Segment { key: "ov_word_ease"; options: [{v:"smooth",t:"นุ่ม"},{v:"gentle",t:"อ่อนโยน"},{v:"spring",t:"เด้ง"},{v:"linear",t:"เส้นตรง"}] } }
                }
                Card { title: "คำเน้น (ลากเสียงยาว)"
                    note: "แบบ Apple Music: คำที่ลากเสียงยาวจะเรืองแสงและขยายตอนร้อง · ตอนนี้ตัดสินจากความยาวของคำ — ถ้าเพลงมีเวลาทีละคำจริง · การเลือกคำสำคัญด้วย AI อยู่ในเฟส 4"
                    Row2 { label: "เปิดคำเน้น"; SSwitch { key: "ov_emph_on" } }
                    Row2 { label: "คำยาวตั้งแต่กี่วินาทีถือเป็นคำเน้น"; SSlider { key: "ov_emph_min_s"; from: 0.4; to: 4.0; step: 0.1; decimals: 1; unit: " วิ" } }
                    Row2 { label: "ความแรงของแสง"; SSlider { key: "ov_emph_glow"; from: 0; to: 1 } }
                    Row2 { label: "ขนาดที่ขยาย"; adv: true; SSlider { key: "ov_emph_scale"; from: 1.0; to: 1.3; step: 0.01 } }
                }
                Card { title: "การเปลี่ยนบรรทัด"
                    Row2 { label: "รูปแบบ"; wide: true
                        hint: ({ fade_move: "บรรทัดเลื่อนมาตรงกลางอย่างนุ่มนวล พร้อมความสว่างที่ค่อยๆ เปลี่ยน (แนะนำ)",
                                 fade: "เลื่อนเร็วกว่าและเน้นการเปลี่ยนความสว่างของบรรทัด",
                                 move: "เลื่อนอย่างเดียว ความสว่างของบรรทัดไม่ค่อยๆ เปลี่ยน (จะเปลี่ยนทันที)",
                                 scale: "บรรทัดปัจจุบันขยายใหญ่ บรรทัดอื่นย่อเล็ก" })[cfg.ov_animation]
                        Segment { key: "ov_animation"; options: [{v:"fade_move",t:"จาง + เลื่อน"},{v:"fade",t:"จาง"},{v:"move",t:"เลื่อน"},{v:"scale",t:"ย่อ/ขยาย"}] } }
                    Row2 { label: "เลื่อนบรรทัดล่วงหน้า"; hint: "เริ่มเลื่อนก่อนบรรทัดถัดไปเริ่มร้องเท่านี้ ให้ไปถึงกลางจอพอดีตอนเริ่มร้อง (0 = เริ่มเลื่อนตอนเริ่มร้อง ซึ่งรู้สึกหน่วง)"; SSlider { key: "ov_scroll_lead_s"; from: 0; to: 1; step: 0.05; decimals: 2; unit: " วิ" } }
                    Row2 { label: "ความเร็ว"; hint: "มาก = เปลี่ยนเร็วขึ้น"; adv: true; SSlider { key: "ov_anim_speed"; from: 0.3; to: 3.0; step: 0.05 } }
                    Row2 { label: "ความแรง"; adv: true; SSlider { key: "ov_animation_intensity"; from: 0; to: 2 } }
                    Row2 { label: "เบลอบรรทัดที่ไม่ได้ร้อง — โหมดเต็ม"; hint: "ยิ่งไกลจากบรรทัดที่ร้องยิ่งเบลอ (แบบ Apple Music) · 0 = ไม่เบลอ"; SSlider { key: "fw_blur"; from: 0; to: 1; step: 0.05 } }
                    Row2 { label: "เบลอบรรทัดที่ไม่ได้ร้อง — หน้าต่างลอย"; hint: "ใช้กับหน้าต่างเนื้อเพลงลอยเท่านั้น"; SSlider { key: "ov_blur"; from: 0; to: 1 } }
                    Row2 { label: "ความจางตามระยะห่าง"; adv: true; SSlider { key: "ov_falloff"; from: 0.03; to: 0.3 } }
                    Row2 { label: "ขนาดบรรทัดอื่น"; hint: "ย่อบรรทัดที่ไม่ใช่ปัจจุบัน"; adv: true; SSlider { key: "ov_idle_scale"; from: 0.6; to: 1.0 } }
                    Row2 { label: "คลื่นหน่วงต่อบรรทัด"; hint: "บรรทัดไกลเริ่มเคลื่อนช้ากว่าเล็กน้อยให้เป็นคลื่น"; adv: true; SSlider { key: "ov_wave_ms"; from: 0; to: 150; step: 5; decimals: 0; unit: " ms" } }
                    Row2 { label: "ความหนืดของการเลื่อน"; hint: "สปริง: ต่ำ = นุ่มช้า · สูง = กระชับเร็ว"; adv: true; SSlider { key: "look_spring_stiffness"; from: 40; to: 600; step: 10; decimals: 0 } }
                    Row2 { label: "การหน่วง (ลดการเด้ง)"; hint: "สูง = ไม่เด้ง · ต่ำ = เด้งนิดๆ"; adv: true; SSlider { key: "look_spring_damping"; from: 8; to: 60; step: 1; decimals: 0 } }
                }
            }

            // ---------------- การซิงก์ ----------------
            Column {
                property int pgIdx: 7; visible: win.show(7); width: parent.width; spacing: 6
                Intro { text: "สถานะการเชื่อมต่อ YouTube และการปรับเวลา/ค้นหาเนื้อเพลงของเพลงที่เล่นอยู่" }
                Card { title: "สถานะ"
                    Row2 { label: "การเชื่อมต่อ YouTube"
                        hint: player.bridgeConnected ? "● เชื่อมต่อกับส่วนขยายแล้ว" : (player.everConnected ? "● การเชื่อมต่อหลุด (กำลังเชื่อมต่อใหม่)" : "● ยังไม่เชื่อมต่อ (เปิด Chrome ที่ติดตั้งส่วนขยายไว้)")
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "เชื่อมต่อใหม่"; onClicked: player.reconnectYouTube() }
                            Pill { label: "ติดตั้งส่วนขยาย"; onClicked: win.installRequested() }
                        } }
                    Row2 { label: "เพลงตอนนี้"; hint: player.title.length > 0 ? player.title + " — " + player.artist : "ยังไม่มี" }
                    Row2 { label: "แหล่งเนื้อเพลง"; hint: player.sourceLabel.length > 0 ? player.sourceLabel + (player.timingApprox ? " · เวลาทีละคำเป็นการประมาณ" : "") : "-" }
                }
                Card { title: "AI ฟังเสียง"
                    note: "AI โหลดเสียงของเพลงมาฟังเบื้องหลัง (แอปไม่เล่นเสียงเอง) เพื่อจัดเวลาเนื้อเพลงให้ตรงคำร้องจริง — ใช้การ์ดจอ NVIDIA ของเครื่อง ไม่ทำให้ YouTube ช้าลง"
                    Row2 { label: "จัดเวลาเนื้อเพลงจากเสียงจริง"; hint: "ปิด = ใช้เวลาจากแหล่งเนื้อเพลง/ประมาณล้วน (ไม่ใช้การ์ดจอ)"; SSwitch { key: "ai_enabled" } }
                    Row2 { label: "เก็บข้อมูลสอนจากเพลงที่ฟัง"; hint: "เก็บเสียงร้อง เนื้อเพลงทุกฉบับ ผลของ AI และการกระทำของคุณ (กด ตัวอื่น/ปรับเวลา) ไว้ในเครื่องเท่านั้น เพื่อเทรนโมเดลของเราเอง · กินดิสก์ ~6 MB ต่อเพลง"; SSwitch { key: "ai_collect_data" } }
                    Row2 { label: "แปลเนื้อเพลงเป็นภาษาไทย"; hint: "เพลงที่ไม่ใช่ภาษาไทยแปลทั้งเพลงด้วยโมเดลในเครื่อง (ครั้งแรกอาจรอสักครู่)"; SSwitch { key: "ai_translate" } }
                }
                Card { title: "เวลาเนื้อเพลง"
                    Row2 { label: "ปรับเวลาเนื้อเพลง"; hint: "บวก = เนื้อเพลงช้าลง · จำแยกตามเพลง"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "−0.1"; onClicked: player.adjustOffset(-0.1) }
                            Text { anchors.verticalCenter: parent.verticalCenter; width: 64; horizontalAlignment: Text.AlignHCenter
                                text: (player.lyricsOffset >= 0 ? "+" : "") + player.lyricsOffset.toFixed(1) + " วิ"; color: win.fg; font.pixelSize: 14 }
                            Pill { label: "+0.1"; onClicked: player.adjustOffset(0.1) }
                            Pill { label: "รีเซ็ต"; onClicked: player.resetOffset() }
                        } }
                }
                Card { title: "ค้นหาเนื้อเพลง"
                    Row2 { label: "เปลี่ยน/โหลดใหม่"; hint: "ตัวอื่น = เนื้อเพลงอันดับถัดไป · โหลดใหม่ = ค้นทุกแหล่งอีกรอบ"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "ตัวอื่น"; onClicked: player.nextCandidate() }
                            Pill { label: "โหลดใหม่"; onClicked: player.refreshLyrics() }
                        } }
                    Row2 { label: "ค้นหาเนื้อเพลงเอง"; hint: "พิมพ์ \"ศิลปิน - ชื่อเพลง\" แล้วกด Enter (ใช้เมื่อได้เนื้อเพลงผิดเพลง)"; wide: true
                        TextField {
                            id: manualQ
                            width: parent.width
                            height: 34
                            placeholderText: "เช่น NewJeans - OMG"
                            placeholderTextColor: win.fg2
                            color: win.fg; font.pixelSize: 13; selectByMouse: true
                            background: Rectangle { radius: 8; color: win.field; border.width: manualQ.activeFocus ? 1 : 0; border.color: win.accent }
                            onAccepted: { player.searchLyrics(text); text = "" }
                        } }
                }
            }

            // ---------------- คีย์ลัด ----------------
            Column {
                property int pgIdx: 8; visible: win.show(8); width: parent.width; spacing: 6
                Text { width: parent.width; wrapMode: Text.Wrap; color: win.fg2; font.pixelSize: 12; font.family: cfg.look_font_family
                    visible: win.q.length === 0
                    text: "รูปแบบ Ctrl+Alt+L (ใช้ Ctrl, Alt, Shift, Win + ตัวอักษร/ตัวเลข/F1-F12/ลูกศร) · ว่าง = ปิดคีย์ลัดนั้น · ใช้ได้แม้ไม่ได้โฟกัสโปรแกรม" }
                Text { width: parent.width; wrapMode: Text.Wrap; visible: cfg.hk_status.length > 0; color: "#FCA5A5"; font.pixelSize: 12; text: cfg.hk_status }
                Card { title: "คีย์ลัดทั้งระบบ"
                    Row2 { label: "แสดง/ซ่อนเนื้อเพลง"; SText { key: "hk_show_hide" } }
                    Row2 { label: "คลิกทะลุ เปิด/ปิด"; SText { key: "hk_click_through" } }
                    Row2 { label: "ล็อกตำแหน่ง เปิด/ปิด"; SText { key: "hk_lock" } }
                    Row2 { label: "เปิด/ปิดโหมดเต็ม"; SText { key: "hk_full_toggle" } }
                    Row2 { label: "คำแปล เปิด/ปิด"; SText { key: "hk_translation" } }
                    Row2 { label: "ขนาดตัวอักษร +"; adv: true; SText { key: "hk_font_up" } }
                    Row2 { label: "ขนาดตัวอักษร −"; adv: true; SText { key: "hk_font_down" } }
                    Row2 { label: "เนื้อเพลงช้าลง 0.1 วิ"; adv: true; SText { key: "hk_offset_later" } }
                    Row2 { label: "เนื้อเพลงเร็วขึ้น 0.1 วิ"; adv: true; SText { key: "hk_offset_earlier" } }
                    Row2 { label: "รีเซ็ตเวลา"; adv: true; SText { key: "hk_offset_reset" } }
                }
                Card { title: "คีย์ลัดในหน้าต่างโหมดเต็ม"
                    Row2 { label: "F / F11 เต็มจอ · Esc ออก · Space เล่น/หยุด · ← → กรอ 5 วิ · N / P เพลงถัดไป/ก่อนหน้า · ↑ ↓ วอลลุ่ม · M ปิดเสียง · L ซ่อน/แสดงเนื้อเพลง · T คำแปล · + − ขนาดเนื้อเพลง · [ ] ปรับเวลา" }
                }
            }
        }
    }
}
