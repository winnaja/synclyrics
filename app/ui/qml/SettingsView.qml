// หน้าตั้งค่า — ออกแบบใหม่ "Ambient Stage": พื้นหลังไหลลื่นสีจากปกเพลงที่เล่นอยู่ (shader เดียวกับหน้าต่างเต็ม) ฝังด้วยม่านเข้ม
// องค์ประกอบ 3 ส่วน: แถบซ้าย (ค้นหา + หมวดมีไอคอน) · รายการตั้งค่าตรงกลาง (หัวข้อใหญ่ แถวไม่มีกล่อง คั่นเส้นบาง) · เวทีตัวอย่างสดด้านขวา
// เวที = หน้าต่างเต็มย่อส่วนที่ใช้ LyricsView ตัวจริงกับค่า fw_*/ov_* จริง (ไม่ใช่ภาพจำลอง) — จอแคบ (< ~1400px) เวทีหุบเหลือแถบตัวอย่างบรรทัดเดียวด้านบน
// ค่าดีไซน์ (tokens) อยู่ต้นหน้าต่าง: สีแบบโปร่งขาว/ดำ · dFast/dMed/dSlow · ขนาดตัวอักษร ใช้ร่วมกันทุกตัวควบคุม
// ทุกการเปลี่ยนมีผลทันที (cfg เดียวกับหน้าต่างเนื้อเพลง) และบันทึกเอง · ตัวเลือกขั้นสูงซ่อนหลังสวิตช์ "โหมดละเอียด" · ค้นหาได้ · ใช้คีย์บอร์ดได้
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Window
import QtQuick.Effects

Item {
    id: win
    objectName: "settingsView"

    signal placeRequested(string name)
    signal installRequested()
    signal quitRequested()
    signal backRequested()        // ปุ่มกลับ / Esc: กลับหน้าเล่นเพลง
    signal floatingRequested()    // สลับไปใช้หน้าต่างลอยแทนหน้าต่างหลัก

    // หน้าตั้งค่าเป็นหน้าหนึ่งในหน้าต่างหลักเดียวกับเครื่องเล่น (ซ้อนทับเครื่องเล่นที่ยังเล่นอยู่ข้างใต้) — ไม่ใช่หน้าต่างแยก
    property bool shown: false
    visible: opacity > 0.01
    opacity: shown ? 1 : 0
    scale: shown ? 1 : 0.985
    Behavior on opacity { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    // กันคลิก/ล้อเมาส์ทะลุไปโดนเนื้อเพลงของเครื่องเล่นด้านล่าง
    MouseArea { anchors.fill: parent; z: -30; hoverEnabled: true; onWheel: (w) => { w.accepted = true } }
    // Esc: ล้างคำค้นก่อน ถ้าไม่มีคำค้นแล้วกลับหน้าเล่นเพลง (เรียกจากหน้าต่างหลัก)
    function handleEscape() { if (query.length > 0) searchBox.text = ""; else backRequested() }

    // ---------- tokens ----------
    readonly property color bg: "#0C0D12"
    readonly property color fg: "#F5F5F8"
    readonly property color fg2: "#B7B9C9"
    readonly property color fg3: "#7F8196"
    readonly property color line: Qt.rgba(1, 1, 1, 0.09)
    readonly property color field: Qt.rgba(1, 1, 1, 0.08)           // ช่องกรอก/ปุ่ม/ราง
    readonly property color fieldHover: Qt.rgba(1, 1, 1, 0.14)
    readonly property color accent: "#A5B4FC"
    readonly property color inkOnAccent: "#12131A"
    readonly property color danger: "#FCA5A5"
    readonly property int dFast: 110                  // ปุ่ม/hover/สวิตช์ — ตอบสนองทันที
    readonly property int dMed: 200                   // เปิด-ปิดส่วน/ตัวชี้
    readonly property int dSlow: 320                  // เปลี่ยนหน้า/ขยายตัวอย่าง
    readonly property real navW: 236
    readonly property real areaW: width - navW
    readonly property bool wide: areaW >= 1180        // กว้างพอ = มีเวทีตัวอย่างสดด้านขวา
    readonly property real stageW: wide ? Math.max(400, Math.min(540, areaW * 0.34)) : 0
    readonly property real listAvail: areaW - (wide ? stageW + 36 : 0) - 88
    readonly property real contentW: Math.min(listAvail, 900)
    readonly property real contentX: navW + 44 + (listAvail - contentW) / 2
    readonly property real ctlW: Math.max(250, Math.min(340, contentW * 0.4))   // คอลัมน์ตัวควบคุมขวา (ตามความกว้างจริง)
    property bool advanced: false     // แสดงตัวเลือกขั้นสูง
    property string query: ""         // ค้นหา: ไม่ว่าง = แสดงทุกหมวดที่มีแถวตรงกับคำค้น
    readonly property string q: query.trim().toLowerCase()
    property bool previewOpen: false  // (จอแคบ) แถบตัวอย่างขยาย/ย่อ
    property Item navCur: null

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
    property string pendingCard: ""
    function findCard(item, title) {
        var kids = item.children
        for (var i = 0; i < kids.length; ++i) {
            if (kids[i].isCard === true && kids[i].title === title && kids[i].any) return kids[i]
            var r = findCard(kids[i], title)
            if (r) return r
        }
        return null
    }
    // ไปหมวด (และเลื่อนไปที่หัวข้อย่อยพร้อมแฟลชให้เห็นว่ามาถึงแล้ว)
    function gotoPage(idx, cardTitle) {
        query = ""; searchBox.text = ""; page = idx
        pendingCard = cardTitle || ""
        if (pendingCard.length > 0) focusTimer.restart()
    }
    Timer { id: focusTimer; interval: 140; onTriggered: {
        var c = win.findCard(pageCol, win.pendingCard)
        if (c) {
            scroller.contentY = Math.max(0, Math.min(Math.max(0, scroller.contentHeight - scroller.height), c.mapToItem(pageCol, 0, 0).y - 12))
            c.flash()
        }
        win.pendingCard = ""
    } }

    Connections {
        target: scroller
        function onContentYChanged() { if (scroller.contentY > 90) win.previewOpen = false }
    }

    // ---------- พื้นหลัง: สีไหลจากปกเพลง + ม่านเข้ม ----------
    Rectangle { anchors.fill: parent; z: -25; color: win.bg }
    property real tAmb: 0
    FrameAnimation { running: win.shown && !cfg.ov_reduced_motion; onTriggered: win.tAmb += frameTime }
    ShaderEffect {
        anchors.fill: parent
        z: -20
        property real time: win.tAmb
        property real brightness: 0.62
        property real speed: 0.5
        property vector2d aspect: Qt.vector2d(width / Math.max(1, height), 1)
        property color c0: player.palette[0]
        property color c1: player.palette[1]
        property color c2: player.palette[2]
        property color c3: player.palette[3]
        Behavior on c0 { ColorAnimation { duration: 900 } }
        Behavior on c1 { ColorAnimation { duration: 900 } }
        Behavior on c2 { ColorAnimation { duration: 900 } }
        Behavior on c3 { ColorAnimation { duration: 900 } }
        fragmentShader: "../shaders/fluid.frag.qsb"
    }
    Rectangle { anchors.fill: parent; z: -19; color: Qt.rgba(0.04, 0.045, 0.07, 0.66) }   // ม่านเข้ม: ตัวอักษรอ่านง่ายทุกสีปก

    // ================= ตัวควบคุมพื้นฐาน =================
    // หมวดย่อย: หัวข้อใหญ่ + แถวที่คั่นด้วยเส้นบาง (ไม่มีกล่อง) · ซ่อนตัวเองเมื่อไม่มีแถวที่มองเห็น (ตอนค้นหา/ปิดขั้นสูง) แบบหดนุ่ม
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
        readonly property real natural: head.height + col.height + (note.length > 0 ? noteText.height + 10 : 0) + 40
        height: any ? natural : 0
        opacity: any ? 1 : 0
        Behavior on height { NumberAnimation { duration: win.dMed; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: win.dMed } }
        property real glow: 0
        function flash() { glowAnim.restart() }
        NumberAnimation { id: glowAnim; target: cd; property: "glow"; from: 1; to: 0; duration: 1400; easing.type: Easing.OutCubic }
        Rectangle { x: -10; y: -4; width: head.contentWidth + 20; height: 36; radius: 12; color: win.accent; opacity: 0.22 * cd.glow; visible: cd.glow > 0.01 }
        Text {
            id: head
            readonly property bool crumb: win.q.length > 0 && cd.pageIdx >= 0
            visible: cd.title.length > 0 || crumb
            text: crumb ? win.pages[cd.pageIdx].t + "  ›  " + cd.title : cd.title
            color: crumb ? win.accent : win.fg
            font.pixelSize: 21; font.weight: Font.Bold; font.family: cfg.look_font_family
            height: visible ? 40 : 0
            verticalAlignment: Text.AlignTop
            TapHandler { enabled: head.crumb; onTapped: win.gotoPage(cd.pageIdx, cd.title) }   // กดหัวข้อผลค้นหา = ไปหมวดนั้น
            HoverHandler { enabled: head.crumb; cursorShape: Qt.PointingHandCursor }
        }
        Column { id: col; y: head.height; width: parent.width }
        Text {
            id: noteText
            visible: cd.note.length > 0
            y: head.height + col.height + 10
            width: parent.width
            text: cd.note
            wrapMode: Text.Wrap
            color: win.fg3; font.pixelSize: 13; font.family: cfg.look_font_family
        }
    }

    // คำอธิบายสั้นๆ ใต้หัวหน้า: หมวดนี้ทำอะไร
    component Intro: Text {
        width: parent ? parent.width : 400
        wrapMode: Text.Wrap
        color: win.fg2
        font.pixelSize: 15
        font.family: cfg.look_font_family
        lineHeight: 1.15
        bottomPadding: 20
        visible: win.q.length === 0
    }

    component Row2: Item {                       // แถว: ป้ายซ้าย ตัวควบคุมขวา (adv = ซ่อนจนกว่าจะเปิดโหมดละเอียด)
        id: r2
        property string label: ""
        property string hint: ""
        property bool adv: false
        property bool wide: false                // true = ตัวควบคุมกว้างเต็มแถวใต้ป้าย (สี/ตัวเลือกยาว)
        property string kw: ""                    // คำค้นเพิ่ม (ภาษาพูด/คำพ้อง) ที่ไม่ได้แสดงบนหน้าจอ
        property string resetKey: ""             // คีย์ที่ปุ่ม ↺ จะคืนค่า (ว่าง = หาเองจากตัวควบคุมตัวแรกที่มี key)
        default property alias content: slot.data
        readonly property var cardItem: win.cardOf(r2)
        readonly property bool matches: win.q.length === 0
            || win.hit(label + " " + hint + " " + kw + " " + rkey + " " + (cardItem ? cardItem.title : "")
                       + " " + (cardItem && cardItem.pageIdx >= 0 ? win.pages[cardItem.pageIdx].t : ""))
        readonly property bool want: (!adv || win.advanced || win.q.length > 0) && matches
            && !(win.q.length > 0 && cardItem && cardItem.pageIdx === 9)   // ตอนค้นหาไม่แสดงซ้ำจาก “ตั้งค่าด่วน” (ตัวเลือกเดียวกันอยู่ในหมวดจริงอยู่แล้ว)
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
        readonly property real resetW: rkey.length > 0 ? 40 : 0   // กันที่ไว้เสมอเมื่อมีปุ่ม เพื่อไม่ให้ตัวควบคุมขยับตอนปุ่มโผล่
        readonly property real natural: wide ? labels.height + slot.childrenRect.height + 42
                                             : Math.max(64, Math.max(labels.height, slot.childrenRect.height) + 32)
        visible: height > 0.5
        opacity: want ? 1 : 0
        clip: true
        width: parent ? parent.width : 400
        height: want ? natural : 0
        Behavior on height { NumberAnimation { duration: win.dMed; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: win.dMed } }
        Rectangle { visible: r2.want; anchors.bottom: parent.bottom; width: parent.width; height: 1; color: win.line }
        Rectangle { visible: r2.want && win.q.length > 0 && r2.label.length > 0; x: -12; y: 16; width: 3; height: parent.height - 32; radius: 1.5; color: win.accent }   // ไฮไลต์แถวที่ตรงกับคำค้น
        Rectangle {                              // ปุ่มคืนค่าเริ่มต้นของตัวเลือกนี้
            id: rb
            objectName: "resetKeyButton"
            visible: r2.want && r2.modified
            activeFocusOnTab: visible
            x: r2.width - width
            y: r2.wide ? 14 : (r2.height - height) / 2
            width: 28; height: 28; radius: 14
            color: rm.pressed ? Qt.rgba(1, 1, 1, 0.22) : (rh.hovered ? win.fieldHover : win.field)
            border.width: activeFocus ? 2 : 0
            border.color: "#FFFFFF"
            scale: rm.pressed ? 0.88 : 1
            Behavior on scale { NumberAnimation { duration: win.dFast } }
            Behavior on color { ColorAnimation { duration: win.dFast } }
            Text { anchors.centerIn: parent; text: "↺"; color: win.accent; font.pixelSize: 17; font.family: cfg.look_font_family }
            HoverHandler { id: rh; cursorShape: Qt.PointingHandCursor }
            TapHandler { id: rm; onTapped: { rb.forceActiveFocus(); settingsBridge.resetKey(r2.rkey) } }
            Keys.onSpacePressed: settingsBridge.resetKey(r2.rkey)
            Keys.onReturnPressed: settingsBridge.resetKey(r2.rkey)
            ToolTip.visible: rh.hovered
            ToolTip.delay: 350
            ToolTip.text: "คืนค่าเริ่มต้นของข้อนี้"
        }
        Column {
            id: labels
            y: wide ? 16 : (parent.height - height) / 2
            width: wide ? parent.width - r2.resetW : parent.width - win.ctlW - r2.resetW - 28
            spacing: 4
            Text { id: lt; text: r2.label; color: win.fg; font.pixelSize: 16; font.weight: Font.Medium; font.family: cfg.look_font_family; width: parent.width; wrapMode: Text.Wrap
                visible: r2.label.length > 0 }
            Text { visible: r2.hint.length > 0; text: r2.hint; color: win.fg2; font.pixelSize: 13; font.family: cfg.look_font_family; width: parent.width; wrapMode: Text.Wrap
                lineHeight: 1.12 }
        }
        Rectangle {                              // ป้าย "ขั้นสูง" (เห็นเมื่อเปิดตัวเลือกขั้นสูง) ให้รู้ว่าตัวเลือกนี้ปกติถูกซ่อน
            visible: r2.adv && win.advanced && r2.label.length > 0
            x: Math.min(lt.contentWidth + 10, labels.width - width); y: labels.y + 3
            width: advTxt.implicitWidth + 14; height: 20; radius: 10; color: Qt.rgba(1, 1, 1, 0.1)
            Text { id: advTxt; anchors.centerIn: parent; text: "ขั้นสูง"; color: win.fg2; font.pixelSize: 11; font.family: cfg.look_font_family }
        }
        Item {
            id: slot
            x: wide ? 0 : parent.width - win.ctlW - r2.resetW
            y: wide ? labels.y + labels.height + 12 : (parent.height - height) / 2
            width: wide ? parent.width - r2.resetW : win.ctlW
            height: childrenRect.height
        }
    }

    component SSwitch: Rectangle {
        id: sw
        property string key: ""
        property bool useExternal: false              // true = ไม่ผูกกับ cfg (ใช้กับสวิตช์ของหน้าต่างนี้เอง เช่น โหมดละเอียด)
        property bool externalOn: false
        signal toggled()
        readonly property bool on: useExternal ? externalOn : cfg[key] === true
        function flip() { if (useExternal) toggled(); else cfg[key] = !on }
        activeFocusOnTab: true
        anchors.right: parent ? parent.right : undefined
        width: 50; height: 30; radius: 15
        color: on ? win.accent : Qt.rgba(1, 1, 1, 0.16)
        border.width: activeFocus ? 2 : 0
        border.color: "#FFFFFF"
        Behavior on color { ColorAnimation { duration: win.dFast + 60 } }
        Rectangle {
            id: knob
            width: swTap.pressed ? 28 : 24; height: 24; radius: 12; y: 3
            x: sw.on ? sw.width - width - 3 : 3
            color: sw.on ? win.inkOnAccent : "#FFFFFF"
            Behavior on x { NumberAnimation { duration: win.dFast + 70; easing.type: Easing.OutBack; easing.overshoot: 1.2 } }
            Behavior on width { NumberAnimation { duration: win.dFast } }
            Behavior on color { ColorAnimation { duration: win.dFast + 60 } }
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { id: swTap; onTapped: { sw.forceActiveFocus(); sw.flip() } }
        Keys.onSpacePressed: sw.flip()
        Keys.onReturnPressed: sw.flip()
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
        readonly property string shown: sl.value.toFixed(sl.decimals)
        readonly property bool hot: area.containsMouse || area.pressed || sl.activeFocus
        activeFocusOnTab: true
        height: 34
        width: parent ? parent.width : 200
        function setValue(v) {
            v = Math.max(from, Math.min(to, Math.round(v / step) * step))
            cfg[key] = Number(v.toFixed(4))
        }
        Keys.onLeftPressed: setValue(value - step)
        Keys.onDownPressed: setValue(value - step)
        Keys.onRightPressed: setValue(value + step)
        Keys.onUpPressed: setValue(value + step)
        Keys.onPressed: (e) => {
            if (e.key === Qt.Key_Home) { setValue(from); e.accepted = true }
            else if (e.key === Qt.Key_End) { setValue(to); e.accepted = true }
            else if (e.key === Qt.Key_PageUp) { setValue(value + (to - from) / 10); e.accepted = true }
            else if (e.key === Qt.Key_PageDown) { setValue(value - (to - from) / 10); e.accepted = true }
        }
        readonly property real frac: Math.max(0, Math.min(1, (sl.value - sl.from) / (sl.to - sl.from)))
        readonly property real trackW: sl.width - 96
        Rectangle { id: trk; y: 17 - height / 2; x: 0; width: sl.trackW; height: sl.hot ? 8 : 6; radius: height / 2; color: Qt.rgba(1, 1, 1, 0.14)
            Behavior on height { NumberAnimation { duration: win.dFast } }
            Rectangle { width: parent.width * sl.frac; height: parent.height; radius: parent.radius; color: win.accent } }
        Rectangle {                                // ปุ่มลาก: โตขึ้นเมื่อชี้/ลาก มีเงานุ่มและวงแสงตอนลาก
            id: thumb
            property real d: area.pressed ? 24 : (sl.hot ? 22 : 18)
            width: d; height: d; radius: d / 2
            x: trk.width * sl.frac - d / 2; y: 17 - d / 2
            color: "#FFFFFF"
            border.width: sl.activeFocus ? 3 : 0; border.color: win.accent
            Behavior on d { NumberAnimation { duration: win.dFast; easing.type: Easing.OutCubic } }
            Rectangle { anchors.centerIn: parent; width: parent.width + 8; height: width; radius: width / 2; color: "#000000"; opacity: 0.18; z: -2; y: 2 }
            Rectangle { anchors.centerIn: parent; width: parent.width + 16; height: width; radius: width / 2; color: win.accent
                opacity: area.pressed ? 0.28 : 0; z: -1
                Behavior on opacity { NumberAnimation { duration: win.dFast } } }
        }
        MouseArea {
            id: area
            x: -10; width: trk.width + 20; height: parent.height
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            function setFrom(mx) { sl.forceActiveFocus(); sl.setValue(sl.from + Math.max(0, Math.min(1, (mx - 10) / trk.width)) * (sl.to - sl.from)) }
            onPressed: (m) => setFrom(m.x)
            onPositionChanged: (m) => { if (pressed) setFrom(m.x) }
        }
        // ค่าปัจจุบันเป็นช่องกรอกในแคปซูล: พิมพ์แก้ตรงๆ ได้ (ตรวจช่วง ถ้าเกินช่วงจะกะพริบแดงแล้วคืนค่าเดิม)
        Rectangle {
            id: chipBox
            x: sl.width - width; y: 2
            width: 84; height: 30; radius: 15
            color: vf.activeFocus ? Qt.rgba(1, 1, 1, 0.16) : win.field
            border.width: 1
            border.color: bad.running ? win.danger : (vf.activeFocus ? win.accent : "transparent")
            Behavior on color { ColorAnimation { duration: win.dFast } }
            SequentialAnimation { id: bad
                ColorAnimation { target: chipBox; property: "border.color"; to: win.danger; duration: 60 }
                PauseAnimation { duration: 260 }
                ColorAnimation { target: chipBox; property: "border.color"; to: "transparent"; duration: 200 } }
            TextField {
                id: vf
                x: 6; width: sl.unit.length > 0 ? 46 : 72; height: parent.height
                horizontalAlignment: TextInput.AlignRight
                verticalAlignment: TextInput.AlignVCenter
                color: win.fg; font.pixelSize: 14; font.weight: Font.Medium; font.family: cfg.look_font_family
                selectByMouse: true
                padding: 0
                validator: DoubleValidator { notation: DoubleValidator.StandardNotation; decimals: 4 }
                background: Item { }
                Component.onCompleted: text = sl.shown
                Connections { target: sl; function onShownChanged() { if (!vf.activeFocus) vf.text = sl.shown } }
                onEditingFinished: {
                    var v = parseFloat(text.replace(",", "."))
                    if (isNaN(v) || v < sl.from || v > sl.to) { bad.restart(); text = sl.shown }
                    else { sl.setValue(v); text = sl.shown }
                }
            }
            Text { x: 56; anchors.verticalCenter: parent.verticalCenter; width: 24; text: sl.unit.trim(); color: win.fg3; font.pixelSize: 12; font.family: cfg.look_font_family; elide: Text.ElideRight; visible: sl.unit.length > 0 }
        }
    }

    component Pill: Rectangle {                  // ปุ่มทั่วไป
        id: pl
        property string label: ""
        property bool active: false
        signal clicked()
        activeFocusOnTab: true
        implicitWidth: pt.implicitWidth + 30
        implicitHeight: 36
        radius: 18
        border.width: activeFocus ? 2 : 0
        border.color: "#FFFFFF"
        color: active ? "#F5F5F8" : (pm.pressed ? Qt.rgba(1, 1, 1, 0.22) : (ph.hovered ? win.fieldHover : win.field))
        scale: pm.pressed ? 0.97 : 1
        Behavior on color { ColorAnimation { duration: win.dFast } }
        Behavior on scale { NumberAnimation { duration: win.dFast } }
        Text { id: pt; anchors.centerIn: parent; text: pl.label; color: pl.active ? win.inkOnAccent : win.fg; font.pixelSize: 14; font.weight: Font.Medium; font.family: cfg.look_font_family }
        HoverHandler { id: ph; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: pm; onTapped: { pl.forceActiveFocus(); pl.clicked() } }
        Keys.onSpacePressed: pl.clicked()
        Keys.onReturnPressed: pl.clicked()
    }

    // เลือกค่าเดียวจากชุดตัวเลือก: แท่งโปร่งพร้อมแคปซูลสีขาวที่เลื่อนตามค่าที่เลือก (ตัดแถวเองเมื่อแคบ)
    component Segment: Item {
        id: seg
        property string key: ""
        property var options: []                // [{v: "focus", t: "โฟกัส"}, ...]
        width: parent ? parent.width : 300
        readonly property int activeIdx: {
            var cur = cfg[key]
            for (var i = 0; i < options.length; ++i) if (options[i].v === cur) return i
            return -1
        }
        height: box.height
        function pick(i) { if (i >= 0 && i < options.length) cfg[key] = options[i].v }
        Rectangle {
            id: box
            width: Math.min(seg.width, fl.childrenRect.width + 8)
            height: fl.childrenRect.height + 8
            radius: height / 2 > 22 ? 18 : height / 2
            color: Qt.rgba(1, 1, 1, 0.07)
            Rectangle {                                          // ตัวชี้ที่เลื่อนไปหาตัวเลือกที่เลือก
                id: indSel
                property var it: null
                function refresh() { it = seg.activeIdx >= 0 ? rep.itemAt(seg.activeIdx) : null }
                Component.onCompleted: refresh()
                Connections { target: seg; function onActiveIdxChanged() { indSel.refresh() } }
                Connections { target: rep; function onItemAdded() { indSel.refresh() } function onItemRemoved() { indSel.refresh() } }
                visible: it !== null
                radius: height / 2
                color: "#F5F5F8"
                x: it ? it.x + 4 : 4
                y: it ? it.y + 4 : 4
                width: it ? it.width : 0
                height: it ? it.height : 0
                Behavior on x { NumberAnimation { duration: win.dMed + 40; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: win.dMed + 40; easing.type: Easing.OutCubic } }
                Behavior on width { NumberAnimation { duration: win.dMed + 40; easing.type: Easing.OutCubic } }
            }
            Flow {
                id: fl
                x: 4; y: 4
                width: seg.width - 8
                spacing: 2
                Repeater {
                    id: rep
                    model: seg.options
                    Item {
                        id: opt
                        required property int index
                        required property var modelData
                        readonly property bool on: seg.activeIdx === index
                        activeFocusOnTab: true
                        width: lbl.implicitWidth + 30
                        height: 36
                        Rectangle { anchors.fill: parent; radius: height / 2; color: Qt.rgba(1, 1, 1, 0.1); opacity: !opt.on && oh.hovered ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: win.dFast } } }
                        Rectangle { anchors.fill: parent; radius: height / 2; color: "transparent"; border.width: opt.activeFocus ? 2 : 0; border.color: "#FFFFFF" }
                        Text { id: lbl; anchors.centerIn: parent; text: opt.modelData.t; font.pixelSize: 14; font.family: cfg.look_font_family
                            color: opt.on ? win.inkOnAccent : (oh.hovered ? win.fg : win.fg2); font.weight: opt.on ? Font.DemiBold : Font.Medium
                            Behavior on color { ColorAnimation { duration: win.dFast } } }
                        HoverHandler { id: oh; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: { opt.forceActiveFocus(); seg.pick(opt.index) } }
                        Keys.onSpacePressed: seg.pick(opt.index)
                        Keys.onReturnPressed: seg.pick(opt.index)
                        Keys.onLeftPressed: { seg.pick(opt.index - 1); rep.itemAt(Math.max(0, opt.index - 1)).forceActiveFocus() }
                        Keys.onRightPressed: { seg.pick(opt.index + 1); rep.itemAt(Math.min(seg.options.length - 1, opt.index + 1)).forceActiveFocus() }
                    }
                }
            }
        }
    }

    component SColor: Item {
        id: sc
        property string key: ""
        readonly property var swatches: ["#FFFFFF", "#F5F5F7", "#A5B4FC", "#C4B5FD", "#F9A8D4", "#FCD34D", "#86EFAC", "#7DD3FC", "#000000", "#0B0B10", "#1B1F3B", "#777780"]
        readonly property string cur: String(cfg[key]).toUpperCase()
        width: parent ? parent.width : 300
        height: 44
        Row {
            spacing: 8
            Repeater {
                model: sc.swatches
                Rectangle {
                    id: sw
                    required property string modelData
                    readonly property bool sel: modelData.toUpperCase() === sc.cur
                    width: 28; height: 28; radius: 14; color: modelData
                    border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.25)
                    scale: swh.hovered ? 1.14 : 1
                    Behavior on scale { NumberAnimation { duration: win.dFast; easing.type: Easing.OutBack } }
                    Rectangle { anchors.centerIn: parent; width: 38; height: 38; radius: 19; color: "transparent"; border.width: 2; border.color: "#FFFFFF"
                        opacity: sw.sel ? 1 : 0; scale: sw.sel ? 1 : 0.8
                        Behavior on opacity { NumberAnimation { duration: win.dFast } }
                        Behavior on scale { NumberAnimation { duration: win.dFast + 40; easing.type: Easing.OutBack } } }
                    HoverHandler { id: swh; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: cfg[sc.key] = sw.modelData }
                }
            }
        }
        Row {
            anchors.right: parent.right
            spacing: 10
            Rectangle { id: chip; y: 4; width: 36; height: 36; radius: 18; color: cfg[sc.key]; border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.3)
                Behavior on color { ColorAnimation { duration: win.dMed } } }
            TextField {
                id: hex
                y: 4; width: 104; height: 36
                text: cfg[sc.key]
                color: win.fg; font.pixelSize: 14; font.weight: Font.Medium; font.family: cfg.look_font_family
                selectByMouse: true
                leftPadding: 14
                validator: RegularExpressionValidator { regularExpression: /^#[0-9A-Fa-f]{6}$/ }
                background: Rectangle { radius: 18; color: win.field; border.width: hex.activeFocus ? 1 : 0; border.color: hex.acceptableInput ? win.accent : win.danger }
                onEditingFinished: if (acceptableInput) cfg[sc.key] = text.toUpperCase()
            }
            Pill { y: 4; label: "เลือกสีเอง…"; onClicked: dlg.open() }
        }
        ColorDialog {
            id: dlg
            title: "เลือกสี"
            selectedColor: cfg[sc.key]
            onAccepted: cfg[sc.key] = selectedColor.toString().toUpperCase()
        }
    }

    component SText: TextField {
        id: st
        property string key: ""
        width: parent ? parent.width : 200
        height: 40
        text: cfg[key]
        color: win.fg; font.pixelSize: 14; font.family: cfg.look_font_family; selectByMouse: true
        leftPadding: 16
        background: Rectangle { radius: 20; color: win.field; border.width: st.activeFocus ? 1 : 0; border.color: win.accent }
        onEditingFinished: cfg[key] = text.trim()
    }

    // ---------- เวทีตัวอย่างสด (จอกว้าง) ----------
    // หน้าต่างเต็มย่อส่วน: ปก + ชื่อเพลง + เนื้อเพลงจริงจาก LyricsView ตัวเดียวกับหน้าต่างเต็ม ผูกกับค่าเดียวกัน (fw_* และ ov_* ที่เนื้อเพลงใช้)
    // ไม่มีเพลงที่โหลดเนื้อไว้ = ใช้เนื้อตัวอย่าง (FxWord ตัวเดียวกัน) · ตัวเลือกเฉพาะหน้าต่างลอยดูผลที่หน้าต่างลอยจริง
    component Stage: Item {
        id: sg
        property real pos: 0
        FrameAnimation { running: win.shown && sg.visible; onTriggered: sg.pos = clockBridge.position() }
        readonly property real lyricPos: pos - player.lyricsOffset + cfg.ov_latency_ms / 1000
        Rectangle { anchors.fill: parent; radius: 32; color: Qt.rgba(1, 1, 1, 0.055) }
        Rectangle {                              // ขอบบนสว่างบางๆ ให้เวทีลอยขึ้นจากพื้น (แทนเส้นขอบ)
            anchors.fill: parent; radius: 32; color: "transparent"
            gradient: Gradient { GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.05) } GradientStop { position: 0.4; color: "transparent" } }
        }
        Item {
            id: hd
            x: 30; y: 30; width: parent.width - 60; height: 84
            Item {
                id: art
                width: 84; height: 84
                Rectangle { anchors.fill: parent; radius: 16; color: Qt.rgba(1, 1, 1, 0.1); visible: aimg.status !== Image.Ready }
                Image { id: aimg; anchors.fill: parent; source: player.coverUrl; fillMode: Image.Stretch; asynchronous: true; visible: false }
                ShaderEffect {
                    anchors.fill: parent
                    visible: aimg.status === Image.Ready
                    property variant source: aimg
                    property real radius: 16
                    property vector2d size: Qt.vector2d(width, height)
                    property vector2d imgSize: Qt.vector2d(aimg.implicitWidth, aimg.implicitHeight)
                    fragmentShader: "../shaders/rounded_image.frag.qsb"
                }
            }
            Column {
                x: 102; width: parent.width - 102; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                Text { width: parent.width; text: player.title.length > 0 ? player.title : "ยังไม่มีเพลง"; color: win.fg
                    font.pixelSize: 21; font.weight: Font.Bold; font.family: cfg.look_font_family; elide: Text.ElideRight }
                Text { width: parent.width; text: player.artist.length > 0 ? player.artist : "เล่นเพลงใน YouTube เพื่อดูของจริง"; color: win.fg2
                    font.pixelSize: 15; font.family: cfg.look_font_family; elide: Text.ElideRight }
            }
        }
        Item {
            id: lyr
            x: 30; y: 136; width: parent.width - 60; height: parent.height - 136 - 26
            LyricsView {
                id: lv
                anchors.fill: parent
                visible: lineCount > 0
                anchorFrac: 0.42
                lyricPos: sg.lyricPos
                sizeScale: 0.8 * cfg.fw_font_scale
                forceAlign: cfg.fw_align
                minimalMode: false
                colText: cfg.fw_text_color
                colInactive: Qt.alpha(cfg.fw_inactive_color, 0.40)
                colAccent: cfg.fw_accent_color
                colSecondary: Qt.alpha(cfg.fw_secondary_color, 0.62)
                textOpacity: 1.0
                inactiveOpacity: cfg.fw_inactive_opacity
                falloff: cfg.fw_falloff
                blurAmount: cfg.fw_blur * 0.45
                pastFilled: false
                showTranslation: cfg.fw_show_translation && player.showTranslation
                showSourceLabel: false
                edgeFade: Math.max(0.16, cfg.fw_edge_fade)
                edgeBlur: 0
            }
            // ไม่มีเนื้อเพลง: เนื้อตัวอย่างที่เติมสีวนซ้ำ
            Item {
                id: sample
                anchors.fill: parent
                visible: lv.lineCount === 0
                property real t: 0
                FrameAnimation { running: win.shown && sample.visible && !cfg.ov_reduced_motion; onTriggered: sample.t = (sample.t + frameTime) % 5.6 }
                readonly property real sz: Math.min(30, cfg.ov_font_size * 0.62 * cfg.fw_font_scale)
                readonly property var words: ["Girl,", "let's", "put", "some", "miles", "on it"]
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width; spacing: 22
                    Text { width: parent.width; text: "Jump in the Cadillac"; color: cfg.fw_inactive_color; opacity: 0.3; wrapMode: Text.Wrap
                        font.pixelSize: sample.sz; font.weight: cfg.ov_font_weight; font.family: cfg.look_font_family }
                    Row {
                        Repeater {
                            model: sample.words
                            delegate: Item {
                                id: sw2
                                required property int index
                                required property string modelData
                                readonly property real prog: cfg.ov_highlight === "line" ? 1
                                    : (cfg.ov_highlight === "word" ? (sample.t >= index * 0.8 ? 1 : 0)
                                       : Math.max(0, Math.min(1, (sample.t - index * 0.8) / 0.8)))
                                width: fxs.implicitWidth + sample.sz * 0.3
                                height: fxs.implicitHeight
                                FxWord {
                                    id: fxs
                                    text: sw2.modelData
                                    prog: sw2.prog
                                    sinceEnd: sample.t - (sw2.index + 1) * 0.8
                                    current: true
                                    still: cfg.ov_reduced_motion
                                    pixelSize: sample.sz
                                    weight: Math.min(900, cfg.ov_font_weight + cfg.ov_weight_boost)
                                    letterSpacing: cfg.ov_letter_spacing
                                    family: cfg.look_font_family
                                    colText: cfg.fw_text_color
                                    colInactive: Qt.alpha(cfg.fw_inactive_color, 0.40)
                                    colAccent: cfg.fw_accent_color
                                    hl: cfg.ov_highlight
                                    speed: Math.max(0.2, cfg.ov_anim_speed)
                                    k: cfg.ov_animation_intensity
                                }
                            }
                        }
                    }
                    Text { width: parent.width; text: "Our love is still spinning"; color: cfg.fw_inactive_color; opacity: 0.3; wrapMode: Text.Wrap
                        font.pixelSize: sample.sz; font.weight: cfg.ov_font_weight; font.family: cfg.look_font_family }
                }
            }
        }
        Text { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 18; text: "ตัวอย่างสด"; color: win.fg3
            font.pixelSize: 11; font.weight: Font.DemiBold; font.family: cfg.look_font_family }
    }

    // ---------- แถบตัวอย่าง (จอแคบ): บรรทัดเดียว กดขยาย ----------
    component Preview: Rectangle {
        id: pv
        property bool compact: true
        width: parent ? parent.width : 400
        height: 170
        radius: 22
        clip: true
        color: Qt.rgba(1, 1, 1, 0.07)
        property real t: 0
        readonly property var words: ["Girl,", "let's", "put", "some", "miles", "on it"]
        Timer { interval: 33; repeat: true; running: win.shown && pv.visible && !cfg.ov_reduced_motion; onTriggered: pv.t = (pv.t + 0.033) % 5.4 }
        readonly property real sz: Math.min(compact ? 28 : 36, cfg.ov_font_size * 0.8)
        Column {
            anchors.centerIn: parent
            width: parent.width - 48
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
        Text { x: 18; y: 12; text: "ตัวอย่าง"; color: win.fg3; font.pixelSize: 11; font.weight: Font.DemiBold; font.family: cfg.look_font_family }
        Text { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; color: win.fg2; opacity: pvh.hovered ? 1 : 0.7
            text: pv.compact ? "ขยาย ⌄" : "ย่อ ⌃"; font.pixelSize: 12; font.family: cfg.look_font_family
            Behavior on opacity { NumberAnimation { duration: win.dFast } } }
        HoverHandler { id: pvh; cursorShape: Qt.PointingHandCursor }
    }

    // ขนาดสำเร็จรูปของโหมดปัจจุบัน (UX UI ข้อ 3.3)
    function setSize(w, h) {
        cfg["ov_w_" + cfg.ov_mode] = w
        cfg["ov_h_" + cfg.ov_mode] = h
    }

    // ================= โครงหน้าต่าง =================
    property int page: 9
    onPageChanged: { previewOpen = false; scroller.contentY = 0; pageEnter.restart() }
    // title / คำที่ใช้ค้น / กลุ่มที่ปุ่ม "คืนค่า" จะรีเซ็ต / ไอคอน
    readonly property var pages: [
        { t: "คีย์ลัดและโปรแกรม", gs: ["general", "hotkeys"], n: "เริ่มต้น ปุ่มปิด คีย์ลัด ชุดการตั้งค่า รีเซ็ต ข้อมูล", ic: "keyboard" },
        { t: "หน้าต่างและการแสดงผล", gs: ["full", "float"], n: "หน้าต่างหลัก เต็มจอ หน้าต่างลอย ปก ตำแหน่ง ขนาด จอ", ic: "window" },
        { t: "หน้าต่างลอย", gs: ["float"], n: "ตำแหน่ง ขนาด จอ", ic: "float" },
        { t: "ตัวอักษร", gs: ["font"], n: "ฟอนต์ สี ขนาด น้ำหนัก ระยะห่าง", ic: "text" },
        { t: "หน้าตาแอป", gs: ["theme"], n: "ธีม สีพื้นหลัง ความโปร่งใส", ic: "palette" },
        { t: "เนื้อเพลง", gs: ["lyrics"], n: "ไฮไลต์ เลื่อน คำแปล การอ่าน", ic: "lyrics" },
        { t: "เอฟเฟกต์และแอนิเมชัน", gs: ["anim"], n: "การเคลื่อนไหว คาราโอเกะ แสง เบลอ", ic: "motion" },
        { t: "การซิงก์เพลง", gs: ["sync"], n: "เวลาเนื้อเพลง ชดเชย YouTube การเชื่อมต่อ", ic: "timer" },
        { t: "คีย์ลัด", gs: ["hotkeys"], n: "ทั้งระบบ", ic: "keyboard" },
        { t: "ตั้งค่าด่วน", gs: [], n: "ใช้บ่อย เริ่มที่นี่ ธีม ขนาด แอนิเมชัน AI", ic: "bolt" },
        { t: "แหล่งเนื้อเพลงและ AI", gs: ["sources", "ai"], n: "เว็บ LRCLIB NetEase QQ คำบรรยาย ตัดบรรทัด AI แปล ค้นหาเนื้อเพลง", ic: "globe" }
    ]
    // จัดกลุ่มตามคำถามที่ผู้ใช้อยากตอบ: h = หัวข้อกลุ่ม · pg = index ของ pages (ทุกตัวเลือกเดิมยังอยู่ครบ)
    readonly property var navItems: [
        { h: "เริ่มที่นี่" }, { pg: 9 },
        { h: "หน้าตา" }, { pg: 4 }, { pg: 3 }, { pg: 5 }, { pg: 6 },
        { h: "เวลาและข้อมูล" }, { pg: 7 }, { pg: 10 },
        { h: "ระบบ" }, { pg: 1 }, { pg: 0 }
    ]
    function show(p) { return win.q.length > 0 || win.page === p }

    // ---------- แถบซ้าย ----------
    Rectangle {
        id: nav
        width: win.navW
        height: parent.height
        color: Qt.rgba(0, 0, 0, 0.30)
        // ปุ่มกลับไปหน้าเล่นเพลง (หน้าต่างเดียวกัน — ไม่ปิดอะไร เพลงเล่นต่อ)
        Rectangle {
            id: backBtn
            objectName: "settingsBackButton"
            x: 16; y: 22; width: parent.width - 32; height: 44; radius: 22
            activeFocusOnTab: true
            border.width: activeFocus ? 2 : 0; border.color: "#FFFFFF"
            color: bkTap.pressed ? Qt.rgba(1, 1, 1, 0.22) : (bkh.hovered ? win.fieldHover : win.field)
            scale: bkTap.pressed ? 0.98 : 1
            Behavior on color { ColorAnimation { duration: win.dFast } }
            Behavior on scale { NumberAnimation { duration: win.dFast } }
            Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; kind: "back"; size: 20; color: win.fg }
            Text { x: 46; anchors.verticalCenter: parent.verticalCenter; text: "กลับไปเล่นเพลง"; color: win.fg; font.pixelSize: 15; font.weight: Font.Medium; font.family: cfg.look_font_family }
            HoverHandler { id: bkh; cursorShape: Qt.PointingHandCursor }
            TapHandler { id: bkTap; onTapped: win.backRequested() }
            Keys.onSpacePressed: win.backRequested()
            Keys.onReturnPressed: win.backRequested()
            ToolTip.visible: bkh.hovered
            ToolTip.delay: 500
            ToolTip.text: "กลับไปหน้าเล่นเพลง (Esc) — เพลงยังเล่นต่อ"
        }
        // ค้นหาอยู่บนสุดของแถบซ้าย (กด Esc ล้าง)
        TextField {
            id: searchBox
            x: 16; y: 82; width: parent.width - 32; height: 40
            placeholderText: "ค้นหา เช่น สี, เวลา"
            placeholderTextColor: win.fg3
            color: win.fg; font.pixelSize: 14; font.family: cfg.look_font_family
            leftPadding: 40; rightPadding: 34; selectByMouse: true
            text: win.query
            onTextChanged: win.query = text
            background: Rectangle { radius: 20; color: win.field; border.width: searchBox.activeFocus ? 1 : 0; border.color: win.accent }
            Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; kind: "search"; size: 18; color: win.fg3 }
            Text {
                visible: searchBox.text.length > 0
                anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
                text: "✕"; color: win.fg2; font.pixelSize: 13
                TapHandler { onTapped: { searchBox.text = ""; searchBox.forceActiveFocus() } }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }
        }
        Flickable {
            x: 12; y: 138; width: parent.width - 24; height: parent.height - 146
            contentWidth: width; contentHeight: navCol.implicitHeight + 8
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Rectangle {                         // ตัวชี้หมวดปัจจุบัน: เลื่อนนุ่มไปหาหมวดที่เลือก
                id: navInd
                width: parent.width; height: 40; radius: 12
                y: win.navCur ? win.navCur.y : 0
                color: Qt.rgba(1, 1, 1, 0.11)
                opacity: win.q.length === 0 ? 1 : 0
                Behavior on y { NumberAnimation { duration: win.dMed + 60; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: win.dMed } }
            }
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
                        readonly property bool cur: !isHead && win.page === pg
                        width: parent.width
                        height: isHead ? 40 : 40
                        onCurChanged: if (cur) win.navCur = ni
                        Component.onCompleted: if (cur) win.navCur = ni
                        Text { visible: ni.isHead; x: 16; anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                            text: ni.isHead ? ni.modelData.h : ""; color: win.fg3
                            font.pixelSize: 12; font.weight: Font.DemiBold; font.family: cfg.look_font_family }
                        Rectangle {
                            visible: !ni.isHead
                            activeFocusOnTab: !ni.isHead
                            width: parent.width; height: 40; radius: 12
                            border.width: activeFocus ? 2 : 0
                            border.color: "#FFFFFF"
                            color: nh.hovered && !ni.cur ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
                            Behavior on color { ColorAnimation { duration: win.dFast } }
                            Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; kind: ni.pg >= 0 ? win.pages[ni.pg].ic : "play"; size: 18
                                color: ni.cur && win.q.length === 0 ? win.accent : (nh.hovered ? win.fg : win.fg2)
                                Behavior on color { ColorAnimation { duration: win.dFast } } }
                            Text { anchors.verticalCenter: parent.verticalCenter; x: 44; text: ni.pg >= 0 ? win.pages[ni.pg].t : ""
                                color: ni.cur && win.q.length === 0 ? win.fg : (nh.hovered ? win.fg : win.fg2)
                                font.pixelSize: 15; font.family: cfg.look_font_family; font.weight: ni.cur && win.q.length === 0 ? Font.DemiBold : Font.Normal
                                Behavior on color { ColorAnimation { duration: win.dFast } } }
                            HoverHandler { id: nh; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: { win.query = ""; searchBox.text = ""; win.page = ni.pg } }
                            Keys.onSpacePressed: { win.query = ""; win.page = ni.pg }
                            Keys.onReturnPressed: { win.query = ""; win.page = ni.pg }
                        }
                    }
                }
            }
        }
    }

    // ---------- หัวหน้า: ชื่อหมวดใหญ่ + โหมดละเอียด + คืนค่า ----------
    Item {
        id: top
        x: win.contentX
        y: 28
        width: win.contentW
        height: 64
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 420
            elide: Text.ElideRight
            text: win.q.length > 0 ? "ผลการค้นหา" : win.pages[win.page].t
            color: win.fg; font.pixelSize: 36; font.weight: Font.Bold; font.family: cfg.look_font_family
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 16
            Pill {
                visible: win.q.length === 0 && win.pages[win.page].gs.length > 0
                anchors.verticalCenter: parent.verticalCenter
                label: "คืนค่าหมวดนี้"
                onClicked: { var g = win.pages[win.page].gs; for (var i = 0; i < g.length; ++i) settingsBridge.resetPage(g[i]) }
            }
            Row {
                spacing: 10
                anchors.verticalCenter: parent.verticalCenter
                Text { anchors.verticalCenter: parent.verticalCenter; text: "แสดงตัวเลือกขั้นสูง"; color: win.advanced ? win.fg : win.fg2
                    font.pixelSize: 14; font.weight: Font.Medium; font.family: cfg.look_font_family }
                SSwitch { useExternal: true; externalOn: win.advanced; onToggled: win.advanced = !win.advanced; anchors.right: undefined }
            }
        }
    }

    // เวทีตัวอย่างสดด้านขวา (จอกว้าง)
    Stage {
        id: stage
        visible: win.wide
        x: win.width - width - 32
        y: 28
        width: win.stageW
        height: win.height - 56
        opacity: win.wide ? 1 : 0
    }

    // แถบตัวอย่าง (จอแคบ เฉพาะหมวดที่เกี่ยวกับหน้าตาเนื้อเพลง)
    Preview {
        id: strip
        x: win.contentX
        y: top.y + top.height + 10
        width: win.contentW
        compact: !win.previewOpen
        visible: height > 1
        readonly property bool wanted: !win.wide && win.q.length === 0 && (win.page === 3 || win.page === 6 || win.page === 9)
        height: wanted ? (compact ? 84 : 200) : 0
        opacity: wanted ? 1 : 0
        Behavior on height { NumberAnimation { duration: win.dSlow; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: win.dMed } }
        TapHandler { onTapped: win.previewOpen = !win.previewOpen }
    }

    Flickable {
        id: scroller
        x: win.contentX
        y: strip.y + strip.height + (strip.height > 1 ? 20 : 0)
        width: win.contentW + 16
        height: parent.height - y
        contentWidth: width
        contentHeight: pageCol.implicitHeight + 64
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {
            id: vbar
            width: 8
            contentItem: Rectangle { implicitWidth: 4; radius: 2; color: "#FFFFFF"; opacity: vbar.pressed ? 0.4 : (vbar.hovered || vbar.active ? 0.25 : 0.1)
                Behavior on opacity { NumberAnimation { duration: win.dFast } } }
            background: Item { }
        }

        Column {
            id: pageCol
            width: win.contentW
            spacing: 0
            opacity: 1
            transform: Translate { id: pgShift; y: 0 }
            ParallelAnimation {                                  // เปลี่ยนหมวด: เนื้อหาจางเข้าพร้อมเลื่อนขึ้นเบาๆ
                id: pageEnter
                NumberAnimation { target: pageCol; property: "opacity"; from: 0; to: 1; duration: win.dSlow; easing.type: Easing.OutCubic }
                NumberAnimation { target: pgShift; property: "y"; from: 16; to: 0; duration: win.dSlow; easing.type: Easing.OutCubic }
            }

            Text {
                visible: win.q.length > 0 && pageCol.height < 60
                width: parent.width
                wrapMode: Text.Wrap
                text: "ไม่พบการตั้งค่าที่ตรงกับ \"" + win.query + "\" — ลองคำอื่น (ค้นได้จากชื่อ คำอธิบาย ชื่อหมวด หรือชื่อคีย์ เช่น font, blur)"
                color: win.fg2; font.pixelSize: 15; font.family: cfg.look_font_family
            }

            // ---------------- ตั้งค่าด่วน ----------------
            Column {
                property int pgIdx: 9; visible: win.show(9); width: parent.width; spacing: 6
                Intro { text: "เริ่มจากตรงนี้ — รวมตัวเลือกที่คนส่วนใหญ่ใช้ ปรับแล้วเห็นผลที่เวทีด้านขวาทันที · อยากปรับละเอียดกว่านี้เลือกหมวดทางซ้าย หรือพิมพ์ค้นหา" }
                Card { title: "หน้าตา"
                    Row2 { label: "ธีมหน้าต่างลอย"; kw: "สี มืด สว่าง ดำ ขาว theme"; hint: "โทนสีของหน้าต่างเนื้อเพลงลอย (หน้าต่างหลักใช้สีจากปกเพลงอัตโนมัติ)"; wide: true
                        Segment { key: "ov_theme"; options: [{v:"soft_dark",t:"Soft Dark"},{v:"pure_black",t:"Pure Black"},{v:"frosted",t:"Frosted Glass"},{v:"minimal_transparent",t:"โปร่งใส"},{v:"light",t:"Light"}] } }
                    Row2 { label: "ขนาดตัวอักษรเนื้อเพลง"; kw: "ตัวหนังสือ ใหญ่ เล็ก font size"; hint: "ใหญ่ขึ้น = อ่านง่ายแต่เห็นเนื้อน้อยลง · เป็นขนาดฐานของทั้งหน้าต่างลอยและหน้าต่างหลัก"; SSlider { key: "ov_font_size"; from: 12; to: 120; step: 1; decimals: 0; unit: " px" } }
                }
                Card { title: "การเคลื่อนไหว"
                    Row2 { label: "สไตล์การเคลื่อนไหว"; kw: "animation preset เด้ง นุ่ม"; hint: "เลือกชุดสำเร็จรูปแล้วปรับต่อเองได้ · ‘นุ่มนวล’ ใกล้ Apple Music ที่สุด"; wide: true
                        Segment { key: "ov_anim_preset"; options: [{v:"smooth",t:"นุ่มนวล (แบบ Apple)"},{v:"balanced",t:"สมดุล"},{v:"bouncy",t:"เด้งนิดๆ"},{v:"snappy",t:"ฉับไว"},{v:"none",t:"ไม่เคลื่อนไหว"}] } }
                    Row2 { label: "วิธีเน้นคำที่กำลังร้อง"; kw: "karaoke คาราโอเกะ highlight"; hint: "เติมสี = สีไหลตามเสียง · ทีละคำ = เปลี่ยนสีทั้งคำ · เรืองแสง = คำสว่างขึ้น · ทั้งบรรทัด = สว่างทั้งบรรทัด · เพลงที่มีเวลาแค่ระดับบรรทัด ระบบประมาณเวลาทีละคำให้"; wide: true
                        Segment { key: "ov_highlight"; options: [{v:"fill",t:"เติมสี"},{v:"word",t:"ทีละคำ"},{v:"glow",t:"เรืองแสง"},{v:"line",t:"ทั้งบรรทัด"}] } }
                    Row2 { label: "ชดเชยเสียงหน่วง (ทุกเพลง)"; hint: "ได้ยินเสียงร้องก่อนเนื้อเพลงขึ้น = เพิ่มค่านี้ · เนื้อเพลงขึ้นก่อนเสียง = ลดค่า (ใช้ชดเชยเสียงที่ช้าจากลำโพง/บลูทูธ)"; SSlider { key: "ov_latency_ms"; from: -500; to: 800; step: 10; decimals: 0; unit: " ms" } }
                    Row2 { label: "เริ่มเลื่อนบรรทัดก่อนถึงเวลาร้อง"; hint: "เนื้อเพลงเริ่มเลื่อนล่วงหน้าเท่านี้ เพื่อให้ถึงตำแหน่งพอดีตอนเริ่มร้อง · 0 = เลื่อนตอนเริ่มร้องพอดี (รู้สึกช้า)"; SSlider { key: "ov_scroll_lead_s"; from: 0; to: 1; step: 0.05; decimals: 2; unit: " วิ" } }
                    Row2 { label: "ลดการเคลื่อนไหว"; kw: "ปิดแอนิเมชัน เวียนหัว motion"; hint: "เนื้อเพลงเปลี่ยนบรรทัดทันทีโดยไม่เลื่อน ย่อ หรือลอย · เหมาะถ้าเวียนหัวง่ายหรืออยากประหยัดเครื่อง"; SSwitch { key: "ov_reduced_motion" } }
                }
                Card { title: "เนื้อเพลงและ AI"
                    Row2 { label: "ให้ AI ฟังเสียงเพื่อจัดเวลาเนื้อเพลง"; kw: "ai ซิงก์ ตรงเสียง"; hint: "AI ฟังเพลงเบื้องหลังแล้วเลื่อนเวลาเนื้อเพลงให้ตรงคำร้องจริง (ใช้การ์ดจอ NVIDIA) · ไม่แก้ข้อความเนื้อเพลง · ปิด = ใช้เวลาจากแหล่งเนื้อเพลงหรือประมาณเอา"; SSwitch { key: "ai_enabled" } }
                    Row2 { label: "แปลเนื้อเพลงเป็นภาษาไทย"; kw: "translate คำแปล"; hint: "เพลงที่ไม่ใช่ภาษาไทยแปลทั้งเพลงด้วยโมเดลในเครื่อง (ครั้งแรกอาจรอสักครู่) · แสดงเมื่อกดปุ่มแปลที่หน้าเล่นเพลง"; SSwitch { key: "ai_translate" } }
                    Row2 { label: "ปรับเวลาเนื้อเพลงเฉพาะเพลงนี้"; hint: "เนื้อเพลงขึ้นเร็วไป = กด −0.1 · ขึ้นช้าไป = กด +0.1 · จำแยกตามเพลง"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "−0.1"; onClicked: player.adjustOffset(-0.1) }
                            Text { anchors.verticalCenter: parent.verticalCenter; width: 64; horizontalAlignment: Text.AlignHCenter
                                text: (player.lyricsOffset >= 0 ? "+" : "") + player.lyricsOffset.toFixed(1) + " วิ"; color: win.fg; font.pixelSize: 14 }
                            Pill { label: "+0.1"; onClicked: player.adjustOffset(0.1) }
                            Pill { label: "รีเซ็ต"; onClicked: player.resetOffset() }
                        } }
                }
                Card { title: "โปรแกรม"
                    Row2 { label: "ปุ่มปิด (กากบาท) ซ่อนแอปลงถาดระบบ"; kw: "tray ถาดระบบ ปิดโปรแกรม"; hint: "ปิดตัวเลือกนี้ = กดกากบาทแล้วปิดโปรแกรมเลย"; SSwitch { key: "st_close_to_tray" } }
                    Row2 { label: "เปิดแอปพร้อมเปิดเครื่อง"; kw: "startup เริ่มต้น windows"; hint: "เปิดแล้วอยู่ที่ถาดระบบ ไม่เด้งหน้าต่างขึ้นมา · มีผลเมื่อเปิดเครื่องครั้งถัดไป"; SSwitch { key: "st_launch_with_windows" } }
                }
            }

            // ---------------- แหล่งเนื้อเพลง ----------------
            Column {
                property int pgIdx: 10; visible: win.show(10); width: parent.width; spacing: 6
                Intro { text: "แอปค้นเนื้อเพลงจากหลายแหล่งพร้อมกันแล้วเลือกฉบับที่ตรงกันมากที่สุด (ไม่ถูกใจกด “ตัวอื่น” ได้) · AI ช่วยจัดเวลาให้ตรงกับเสียงและแปลเป็นไทย ไม่แก้ข้อความเนื้อเพลง" }
                Card { title: "ค้นเนื้อเพลงจากที่ไหนบ้าง"
                    note: "ปิดทุกแหล่ง = ไม่ค้นเว็บเลย (ใช้ AI ถอดเสียงเป็นเนื้อเพลงอย่างเดียว) · แหล่งที่มีเวลาทีละคำ (NetEase/QQ) ให้ไฮไลต์ละเอียดกว่า"
                    Row2 { label: "LRCLIB"; hint: "เนื้อเพลงซิงก์ทีละบรรทัดแบบเปิด ครอบคลุมเพลงสากลดี"; SSwitch { key: "ls_src_lrclib" } }
                    Row2 { label: "NetEase"; hint: "มีเวลาทีละคำ เพลงจีน/เกาหลี/สากล"; SSwitch { key: "ls_src_netease" } }
                    Row2 { label: "QQ Music"; hint: "มีเวลาทีละคำ เพลงจีน/เกาหลี/สากล"; SSwitch { key: "ls_src_qqmusic" } }
                    Row2 { label: "คำบรรยาย YouTube"; hint: "คำบรรยายของวิดีโอนั้นเอง เวลาตรงกับวิดีโอแน่นอน (เหมาะกับ MV/คลิปที่ตัดต่อ)"; SSwitch { key: "ls_src_youtube_subs" } }
                    Row2 { label: "Lyrics.ovh"; hint: "ข้อความล้วนไม่มีเวลา ใช้เป็นตัวช่วยเทียบความถูกต้อง"; SSwitch { key: "ls_src_lyrics_ovh" } }
                    Row2 { label: "ให้ AI ถอดเสียงเป็นเนื้อเพลงเมื่อหาไม่เจอ"; hint: "AI ฟังเพลงแล้วเขียนเนื้อให้ (อาจมีคำผิด)"; SSwitch { key: "ls_allow_ai_transcribe" } }
                }
                Card { title: "การตัดบรรทัดยาว"
                    Row2 { label: "ตัดบรรทัดยาวให้สั้นลง"; kw: "บรรทัดยาว ขึ้นบรรทัดใหม่"; hint: "ตัดที่วรรคตอนหรือคำเชื่อม (and, but, และ, แต่) แบบ Apple Music · บรรทัดที่มีคำแปลไม่ตัด · มีผลตอนโหลดเพลงครั้งถัดไป"; SSwitch { key: "ls_split_long_lines" } }
                    Row2 { label: "ความยาวสูงสุดของแต่ละบรรทัด"; hint: "น้อย = บรรทัดสั้นตัดบ่อย · ตัวอักษรจีน/ญี่ปุ่น/เกาหลีนับเป็น 2"; adv: true; SSlider { key: "ls_max_line_width"; from: 20; to: 120; step: 2; decimals: 0 } }
                }
                Card { title: "เพลงที่เล่นอยู่ตอนนี้"
                    Row2 { label: "เพลงตอนนี้"; hint: player.title.length > 0 ? player.title + " — " + player.artist : "ยังไม่มี" }
                    Row2 { label: "แหล่งที่ใช้อยู่"; hint: player.sourceLabel.length > 0 ? player.sourceLabel : "-" }
                    Row2 { label: "เปลี่ยน/โหลดใหม่"; hint: "ตัวอื่น = ฉบับอันดับถัดไป · โหลดใหม่ = ค้นทุกแหล่งอีกรอบ"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "ตัวอื่น"; onClicked: player.nextCandidate() }
                            Pill { label: "โหลดใหม่"; onClicked: player.refreshLyrics() }
                        } }
                }
            
                Card { title: "AI ฟังเสียงและแปลภาษา"
                    note: "AI โหลดเสียงของเพลงมาฟังเบื้องหลัง (แอปไม่เล่นเสียงเอง) เพื่อจัดเวลาเนื้อเพลงให้ตรงคำร้องจริง — ใช้การ์ดจอ NVIDIA ของเครื่อง ไม่ทำให้ YouTube ช้าลง"
                    Row2 { label: "ให้ AI ฟังเสียงเพื่อจัดเวลาเนื้อเพลง"; kw: "ai ซิงก์ ตรงเสียง"; hint: "AI ฟังเพลงเบื้องหลังแล้วเลื่อนเวลาเนื้อเพลงให้ตรงคำร้องจริง (ใช้การ์ดจอ NVIDIA) · ไม่แก้ข้อความเนื้อเพลง · ปิด = ใช้เวลาจากแหล่งเนื้อเพลงหรือประมาณเอา"; SSwitch { key: "ai_enabled" } }
                    Row2 { label: "เก็บข้อมูลสอน AI จากเพลงที่ฟัง"; kw: "เทรน train ข้อมูล"; hint: "เก็บเสียงร้อง เนื้อเพลง และการกระทำของคุณ (กด ‘ตัวอื่น’ / ปรับเวลา) ไว้ในเครื่องเท่านั้น เพื่อฝึกโมเดลของเราเอง · กินดิสก์ ~6 MB ต่อเพลง"; SSwitch { key: "ai_collect_data" } }
                    Row2 { label: "แปลเนื้อเพลงเป็นภาษาไทย"; kw: "translate คำแปล"; hint: "เพลงที่ไม่ใช่ภาษาไทยแปลทั้งเพลงด้วยโมเดลในเครื่อง (ครั้งแรกอาจรอสักครู่) · แสดงเมื่อกดปุ่มแปลที่หน้าเล่นเพลง"; SSwitch { key: "ai_translate" } }
                }
                Card { title: "ค้นหาเนื้อเพลงเอง"
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


            // ---------------- ทั่วไป ----------------
                Intro { text: "" }
            Column {
                property int pgIdx: 0; visible: win.show(0); width: parent.width; spacing: 6
                Intro { text: "ชุดการตั้งค่าที่บันทึกไว้ การเริ่มต้นแอป การรีเซ็ต และคีย์ลัด · ทุกตัวเลือกที่ปรับแล้วมีปุ่ม ↺ ข้างๆ กดเพื่อคืนค่าเริ่มต้นเฉพาะข้อนั้น" }
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
                Card { title: "การเริ่มต้นและปุ่มปิด"
                    Row2 { label: "เปิดแอปพร้อมเปิดเครื่อง"; kw: "startup เริ่มต้น windows"; hint: "เปิดแล้วอยู่ที่ถาดระบบ ไม่เด้งหน้าต่างขึ้นมา · มีผลเมื่อเปิดเครื่องครั้งถัดไป"; SSwitch { key: "st_launch_with_windows" } }
                    Row2 { label: "ปุ่มปิด (กากบาท) ซ่อนแอปลงถาดระบบ"; kw: "tray ถาดระบบ ปิดโปรแกรม"; hint: "ปิดตัวเลือกนี้ = กดกากบาทแล้วปิดโปรแกรมเลย"; SSwitch { key: "st_close_to_tray" } }
                    Row2 { label: "รับเพลงจาก YouTube อัตโนมัติ"; kw: "extension ส่วนขยาย"; hint: "ส่วนขยายใน Chrome รายงานเพลงที่เล่นอยู่ให้แอปเอง"; SSwitch { key: "st_extension_sends_current_video" } }
                }
                Card { title: "ข้อมูลและการรีเซ็ต"
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
                Intro { text: "หน้าต่างหลักที่ใช้เล่นเพลงและตั้งค่า (แบบ Apple Music) กับ “หน้าต่างลอย” — หน้าต่างเนื้อเพลงเล็กที่ลอยบนจอ ใช้ตอนไม่ได้เปิดหน้าต่างหลัก" }
                Card { title: "หน้าต่างหลัก (เล่นเพลง + ตั้งค่า)"
                    Row2 { label: "หน้าต่างหลักของแอป"; kw: "เต็มจอ fullscreen หน้าต่างลอย"
                        hint: "แอปมีหน้าต่างหลักเดียว ใช้ทั้งเล่นเพลงและตั้งค่า · กด F หรือ F11 เพื่อเต็มจอ · Esc ออก"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "ใช้หน้าต่างลอยแทน"; onClicked: win.floatingRequested() }
                            Pill { label: "เต็มจอ"; active: cfg.fw_fullscreen; onClicked: cfg.fw_fullscreen = !cfg.fw_fullscreen }
                        } }
                    Row2 { label: "เปิดแอปมาที่หน้าต่างหลักเลย"; hint: "ปิด = จำสถานะครั้งก่อน (หน้าต่างหลักหรือหน้าต่างลอย)"; SSwitch { key: "fw_start_full" } }
                    Row2 { label: "เปิดหน้าต่างหลักแบบขยายใหญ่สุด"; hint: "ขยายเต็มหน้าจอแต่ยังมีแถบชื่อและแถบงาน (ไม่ใช่เต็มจอ) · ปิด = เปิดเป็นขนาดปกติ"; SSwitch { key: "fw_maximized" } }
                    Row2 { label: "ซ่อนปุ่มต่างๆ เมื่อไม่ขยับเมาส์"; hint: "ปุ่มมุมบนและป้ายที่มาของเนื้อเพลงหายไปเอง ขยับเมาส์แล้วกลับมา (ตอนเต็มจอเมาส์หายด้วย)"; SSwitch { key: "fw_idle_hide" } }
                    Row2 { label: "รอกี่วินาทีก่อนซ่อนปุ่ม"; hint: "ต่ำ = ซ่อนไว · สูง = ปุ่มอยู่นานขึ้น"; SSlider { key: "fw_idle_hide_s"; from: 1; to: 30; step: 1; decimals: 0; unit: " วิ" } }
                }
                Card { title: "เนื้อเพลงและปกในหน้าต่างหลัก"
                    Row2 { label: "แสดงเนื้อเพลงข้างปก"; hint: "ปิด = เห็นแต่ปกใหญ่กลางหน้าต่าง (สลับได้ที่ปุ่มบนขวา หรือกด L)"; SSwitch { key: "fw_lyrics_visible" } }
                    Row2 { label: "ตำแหน่งเนื้อเพลงในคอลัมน์"; kw: "จัดวาง align"; hint: "ชิดซ้าย = แบบ Apple Music · กึ่งกลาง = เนื้อเพลงอยู่กลางคอลัมน์"
                        Segment { key: "fw_align"; options: [{v:"left",t:"ชิดซ้าย"},{v:"center",t:"กึ่งกลาง"}] } }
                    Row2 { label: "ขนาดเนื้อเพลง (หน้าต่างหลัก)"; kw: "ใหญ่ เล็ก ตัวหนังสือ"; hint: "คูณกับขนาดที่ปรับตามความสูงหน้าต่างอัตโนมัติ · 1.00 = มาตรฐาน (กด + / − ได้)"; SSlider { key: "fw_font_scale"; from: 0.5; to: 2.0; step: 0.05 } }
                    Row2 { label: "ขนาดปกอัลบั้ม"; kw: "รูปปก cover"; hint: "เล็กลง = เหลือที่ว่างรอบปกมากขึ้น"; SSlider { key: "fw_cover_scale"; from: 0.6; to: 1.0; step: 0.05 } }
                    Row2 { label: "แสดงคำแปลใต้เนื้อเพลง (หน้าต่างหลัก)"; hint: "ต้องมีคำแปลภาษาไทยของเพลงนั้นก่อน (เปิดการแปลที่หน้า “แหล่งเนื้อเพลงและ AI”)"; SSwitch { key: "fw_show_translation" } }
                    Row2 { label: "ความสว่างของบรรทัดอื่น"; kw: "จาง มืด"; hint: "ต่ำ = บรรทัดที่ไม่ได้ร้องจางมาก · 0 = เห็นเฉพาะบรรทัดที่กำลังร้อง"; SSlider { key: "fw_inactive_opacity"; from: 0; to: 1; step: 0.05 } }
                    Row2 { label: "บรรทัดไกลๆ จางลงอีก"; hint: "บรรทัดที่อยู่ไกลจากบรรทัดที่ร้องจางลงตามระยะ (Apple Music แทบไม่จางเพิ่ม)"; SSlider { key: "fw_falloff"; from: 0; to: 0.3; step: 0.01 } }
                    Row2 { label: "ขอบบนและล่างของเนื้อเพลงค่อยๆ จาง"; hint: "ความสูงของแถบที่เนื้อเพลงจางหายก่อนถึงขอบ · 0 = ตัดเป็นเส้นแข็ง"; SSlider { key: "fw_edge_fade"; from: 0; to: 0.4; step: 0.01 } }
                    Row2 { label: "ขอบบนและล่างเบลอเพิ่ม"; hint: "เบลอเพิ่มเมื่อบรรทัดเข้าใกล้ขอบ ช่วยไม่ให้เห็นรอยตัด"; SSlider { key: "fw_edge_blur"; from: 0; to: 1; step: 0.05 } }
                    Row2 { label: "แสดงแถบปรับเสียง"; kw: "volume วอลลุ่ม"; hint: "ปรับเสียงของแท็บ YouTube (กด ↑ ↓ หรือ M ก็ได้)"; SSwitch { key: "fw_show_volume" } }
                }
                Card { title: "สีเนื้อเพลงเฉพาะหน้าต่างหลัก (ปกติใช้ตามหน้า “ตัวอักษร”)"
                    Row2 { label: "สีบรรทัดที่ร้อง"; adv: true; hint: "สีของคำที่ร้องแล้วและบรรทัดที่กำลังร้อง"; wide: true; SColor { key: "fw_text_color" } }
                    Row2 { label: "สีไฮไลต์"; adv: true; hint: "ใช้กับไฮไลต์แบบทีละคำ/เรืองแสง (สีแสงเรืองตั้งที่หมวดแอนิเมชัน)"; wide: true; SColor { key: "fw_accent_color" } }
                    Row2 { label: "สีบรรทัดที่ยังไม่ร้อง"; adv: true; hint: "ความจางตั้งที่ \"ความจางของบรรทัดที่ไม่ได้ร้อง\""; wide: true; SColor { key: "fw_inactive_color" } }
                    Row2 { label: "สีคำแปล"; adv: true; wide: true; SColor { key: "fw_secondary_color" } }
                }
                Card { title: "พื้นหลังหน้าต่างหลัก"
                    Row2 { label: "พื้นหลังของหน้าต่างหลัก"; kw: "background พื้นหลัง"; hint: "ไหลลื่นตามสีปก = สีผสมไหลจากปกเพลง · สีเรียบ = สีเข้มสีเดียวจากปก"
                        Segment { key: "fw_background"; options: [{v:"fluid",t:"ไหลลื่นตามสีปก"},{v:"solid",t:"สีเรียบ"}] } }
                    Row2 { label: "ความสว่างพื้นหลัง"; hint: "ต่ำ = มืดลง · สูง = สว่างขึ้น (เนื้อเพลงอ่านยากถ้าสว่างเกินไป)"; SSlider { key: "fw_brightness"; from: 0.3; to: 1.3 } }
                }
            }

            // ---------------- หน้าต่างลอย ----------------
            Column {
                property int pgIdx: 1; visible: win.show(1); width: parent.width; spacing: 6
                Intro { text: "" }
                Card { title: "หน้าต่างลอย — การแสดงผล"
                    Row2 { label: "แสดงหน้าต่างเนื้อเพลงลอย"; hint: "แสดงเมื่อไม่ได้เปิดหน้าต่างหลัก"; SSwitch { key: "ov_visible" } }
                    Row2 { label: "ขนาดการแสดงผล"; hint: "เล็ก = บรรทัดเดียว พื้นโปร่งมาก · โฟกัส = หลายบรรทัด"
                        Segment { key: "ov_mode"; options: [{v:"minimal",t:"เล็ก"},{v:"focus",t:"โฟกัส"}] } }
                    Row2 { label: "จำนวนบรรทัดที่เห็น (โหมดโฟกัส)"; hint: "มาก = เห็นบรรทัดรอบๆ มากขึ้น แต่หน้าต่างสูงขึ้น"; SSlider { key: "ov_visible_lines"; from: 1; to: 9; step: 1; decimals: 0 } }
                    Row2 { label: "การจัดวางข้อความ"
                        Segment { key: "ov_align"; options: [{v:"left",t:"ซ้าย"},{v:"center",t:"กลาง"},{v:"right",t:"ขวา"}] } }
                    Row2 { label: "แสดงแถบปุ่มเมื่อชี้เมาส์"; hint: "แถบปุ่มเล็กๆ (ตั้งค่า แปล ฯลฯ) โผล่ตอนเมาส์อยู่บนหน้าต่างลอย"; SSwitch { key: "ov_hover_controls" } }
                }
                Card { title: "หน้าต่างลอย — พฤติกรรม"
                    Row2 { label: "อยู่บนสุดเสมอ"; kw: "topmost"; hint: "หน้าต่างลอยอยู่เหนือโปรแกรมอื่นตลอด"; SSwitch { key: "ov_always_on_top" } }
                    Row2 { label: "ล็อกตำแหน่งและขนาด"; hint: "กันลาก/ปรับขนาดพลาดตอนอ่าน"; SSwitch { key: "ov_locked" } }
                    Row2 { label: "คลิกทะลุหน้าต่าง"; hint: "เมาส์ผ่านไปที่โปรแกรมด้านหลัง ปิดได้จากถาดระบบหรือคีย์ลัด"; SSwitch { key: "ov_click_through" } }
                    Row2 { label: "จำตำแหน่งและขนาดล่าสุด"; hint: "เปิดครั้งหน้าอยู่ที่เดิม"; SSwitch { key: "ov_remember_position" } }
                }
                Card { title: "หน้าต่างลอย — ตำแหน่งและขนาด"
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
                    Row2 { label: "ความกว้างหน้าต่างลอย"; adv: true; SSlider { key: "ov_w_" + cfg.ov_mode; from: 240; to: 2400; step: 10; decimals: 0; unit: " px" } }
                    Row2 { label: "ความสูงหน้าต่างลอย"; adv: true; SSlider { key: "ov_h_" + cfg.ov_mode; from: 60; to: 1600; step: 10; decimals: 0; unit: " px" } }
                    Row2 { label: "คืนขนาดเริ่มต้น"; Pill { anchors.right: parent.right; label: "คืนขนาด"; onClicked: settingsBridge.resetSize() } }
                }
            }

            // ---------------- ตัวอักษร ----------------
            Column {
                property int pgIdx: 3; visible: win.show(3); width: parent.width; spacing: 6
                Intro { text: "ฟอนต์ ขนาด น้ำหนัก ระยะห่าง และสีของเนื้อเพลง · ใช้ทั้งหน้าต่างหลักและหน้าต่างลอย" }
                Card { title: "ฟอนต์และขนาด"
                    Row2 { label: "ฟอนต์เนื้อเพลง"; kw: "ตัวอักษร font family"; hint: "ใช้ทั้งหน้าต่างหลักและหน้าต่างลอย · ฟอนต์หลักคือ SF Thonburi (ถ้าเครื่องไม่มีจะใช้ตัวสำรองให้เอง)"; resetKey: "look_font_family"
                        ComboBox {
                            id: fontBox
                            width: parent.width
                            model: Qt.fontFamilies()
                            currentIndex: Math.max(0, model.indexOf(cfg.look_font_family))
                            onActivated: cfg.look_font_family = model[currentIndex]
                            background: Rectangle { radius: 8; color: win.field; border.width: fontBox.activeFocus ? 2 : 0; border.color: "#FFFFFF" }
                            contentItem: Text { leftPadding: 10; text: cfg.look_font_family; color: win.fg; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                        } }
                    Row2 { label: "ขนาดตัวอักษรเนื้อเพลง"; kw: "ตัวหนังสือ ใหญ่ เล็ก font size"; hint: "ใหญ่ขึ้น = อ่านง่ายแต่เห็นเนื้อน้อยลง · เป็นขนาดฐานของทั้งหน้าต่างลอยและหน้าต่างหลัก"; SSlider { key: "ov_font_size"; from: 12; to: 120; step: 1; decimals: 0; unit: " px" } }
                    Row2 { label: "ความหนาตัวอักษร"; kw: "bold weight"; hint: "ตัวบาง ↔ ตัวหนา · 400 = ปกติ · 700 = หนา"; SSlider { key: "ov_font_weight"; from: 100; to: 900; step: 100; decimals: 0 } }
                    Row2 { label: "บรรทัดที่กำลังร้องหนาขึ้น"; hint: "เพิ่มความหนาให้บรรทัดปัจจุบันจากปกติกี่หน่วย"; adv: true; SSlider { key: "ov_weight_boost"; from: 0; to: 300; step: 50; decimals: 0 } }
                    Row2 { label: "ระยะห่างระหว่างบรรทัด"; kw: "line height"; hint: "ต่ำ = บรรทัดชิดกัน · สูง = บรรทัดห่างกัน"; SSlider { key: "ov_line_spacing"; from: 0.8; to: 2.5; step: 0.05 } }
                    Row2 { label: "ระยะห่างระหว่างตัวอักษร"; kw: "letter spacing"; hint: "ต่ำ = ตัวอักษรชิด · สูง = ตัวอักษรห่าง"; adv: true; SSlider { key: "ov_letter_spacing"; from: -3; to: 12; step: 0.5; decimals: 1 } }
                    Row2 { label: "ความกว้างของข้อความ"; hint: "สัดส่วนของพื้นที่เนื้อเพลง · ต่ำ = ตัดขึ้นบรรทัดใหม่เร็วขึ้น"; SSlider { key: "ov_text_width"; from: 0.4; to: 1.0; step: 0.05 } }
                    Row2 { label: "เงาตัวอักษร"; kw: "shadow"; hint: "เงาจางๆ ช่วยให้อ่านง่ายบนพื้นสว่าง"; adv: true; SSlider { key: "ov_text_shadow"; from: 0; to: 1 } }
                }
                Card { title: "สี"
                    note: "สีที่ตั้งตรงนี้ใช้ทั้งหน้าต่างลอยและหน้าต่างหลัก · อยากให้หน้าต่างหลักสีต่างออกไป เปิด “แสดงตัวเลือกขั้นสูง” แล้วตั้งที่หน้า “หน้าต่างและการแสดงผล”"
                    Row2 { label: "สีเนื้อเพลงที่ร้องแล้ว"; kw: "color สี ตัวหนังสือ"; hint: "สีของคำที่ร้องไปแล้วและบรรทัดที่กำลังร้อง"; wide: true; SColor { key: "ov_text_color" } }
                    Row2 { label: "สีไฮไลต์"; kw: "accent"; hint: "สีเน้นของคำที่กำลังร้อง (ไฮไลต์แบบทีละคำ/เรืองแสง)"; wide: true; SColor { key: "ov_accent_color" } }
                    Row2 { label: "สีบรรทัดที่ยังไม่ร้อง"; hint: "สีของคำที่ยังไม่ถึงเวลาร้อง"; wide: true; SColor { key: "ov_inactive_color" } }
                    Row2 { label: "สีคำแปล"; hint: "สีของคำแปลและข้อความรอง"; adv: true; wide: true; SColor { key: "ov_secondary_color" } }
                    Row2 { label: "ความทึบของตัวอักษร"; hint: "ต่ำ = ตัวอักษรจางลงทั้งหมด"; adv: true; SSlider { key: "ov_text_opacity"; from: 0.2; to: 1 } }
                    Row2 { label: "ความสว่างของบรรทัดอื่น (หน้าต่างลอย)"; hint: "ต่ำ = บรรทัดที่ไม่ได้ร้องจางมาก"; adv: true; SSlider { key: "ov_inactive_opacity"; from: 0.05; to: 1 } }
                }
            }

            // ---------------- พื้นหลังและธีม ----------------
            Column {
                property int pgIdx: 4; visible: win.show(4); width: parent.width; spacing: 6
                Intro { text: "สีและความโปร่งใสของ “หน้าต่างลอย” · หน้าต่างหลักใช้สีจากปกเพลงอัตโนมัติ (ปรับได้ที่ “หน้าต่างและการแสดงผล”)" }
                Card { title: "โทนสีสำเร็จรูป"
                    Row2 { label: "ธีมหน้าต่างลอย"; kw: "สี มืด สว่าง ดำ ขาว theme"; hint: "โทนสีของหน้าต่างเนื้อเพลงลอย (หน้าต่างหลักใช้สีจากปกเพลงอัตโนมัติ)"; wide: true
                        Segment { key: "ov_theme"; options: [{v:"soft_dark",t:"Soft Dark"},{v:"pure_black",t:"Pure Black"},{v:"frosted",t:"Frosted Glass"},{v:"minimal_transparent",t:"Minimal Transparent"},{v:"light",t:"Light"},{v:"custom",t:"กำหนดเอง"}] } }
                }
                Card { title: "พื้นหลังของหน้าต่างลอย"
                    Row2 { label: "ลักษณะพื้นหลังหน้าต่างลอย"; kw: "background พื้นหลัง โปร่ง"; hint: "โปร่งใส / กระจกฝ้า / ดำนุ่ม / ทึบ / ไล่สี / สีที่กำหนดเอง"; wide: true
                        Segment { key: "ov_bg_style"; options: [{v:"transparent",t:"โปร่งใส"},{v:"frosted",t:"กระจกฝ้า"},{v:"soft_dark",t:"ดำนุ่ม"},{v:"solid",t:"ทึบ"},{v:"gradient",t:"Gradient"},{v:"custom",t:"สีกำหนดเอง"}] } }
                    Row2 { label: "เบลอสิ่งที่อยู่ด้านหลังหน้าต่าง"; kw: "blur acrylic"; hint: "ใช้กับพื้นหลัง “กระจกฝ้า” (Windows acrylic) · ปิดหรือระบบไม่รองรับ = พื้นโปร่งแสงธรรมดา"; SSwitch { key: "ov_blur_behind" } }
                    Row2 { label: "สีพื้นหลัง"; hint: "สีหลักของพื้นหลังหน้าต่างลอย"; wide: true; SColor { key: "ov_bg_color" } }
                    Row2 { label: "สีที่สองของพื้นหลังไล่สี"; hint: "ใช้เมื่อเลือกพื้นหลังแบบ “ไล่สี”"; adv: true; wide: true; SColor { key: "ov_bg_color2" } }
                    Row2 { label: "ความโปร่งใสของพื้นหลัง"; kw: "โปร่งใส transparent"; hint: "ต่ำ = มองทะลุพื้นหลัง · ตัวอักษรยังชัดแม้พื้นโปร่งมาก"; SSlider { key: "ov_bg_opacity"; from: 0; to: 1 } }
                    Row2 { label: "ความทึบของทั้งหน้าต่าง"; hint: "รวมตัวอักษรด้วย · ต่ำ = มองทะลุได้ทั้งหน้าต่าง"; adv: true; SSlider { key: "ov_window_opacity"; from: 0.3; to: 1 } }
                    Row2 { label: "ความชัดของเส้นขอบ"; hint: "เส้นขอบบางๆ รอบหน้าต่างลอย · 0 = ไม่มีขอบ"; adv: true; SSlider { key: "ov_border_opacity"; from: 0; to: 0.6 } }
                    Row2 { label: "เงาหน้าต่าง"; hint: "เงารอบหน้าต่างลอย ช่วยให้แยกจากพื้นหลังเดสก์ท็อป"; adv: true; SSlider { key: "ov_shadow"; from: 0; to: 1 } }
                    Row2 { label: "ความโค้งของมุมหน้าต่าง"; hint: "มาก = มุมมน"; SSlider { key: "ov_corner_radius"; from: 0; to: 60; step: 1; decimals: 0; unit: " px" } }
                }
            }

            // ---------------- เนื้อเพลง ----------------
            Column {
                property int pgIdx: 5; visible: win.show(5); width: parent.width; spacing: 6
                Intro { text: "เนื้อเพลงแสดงและเลื่อนอย่างไร: ไฮไลต์คำ การเลื่อนตามเพลง การคลิกเพื่อกรอ และคำแปล" }
                Card { title: "การอ่านและการเลื่อน"
                    Row2 { label: "วิธีเน้นคำที่กำลังร้อง"; kw: "karaoke คาราโอเกะ highlight"; hint: "เติมสี = สีไหลตามเสียง · ทีละคำ = เปลี่ยนสีทั้งคำ · เรืองแสง = คำสว่างขึ้น · ทั้งบรรทัด = สว่างทั้งบรรทัด · เพลงที่มีเวลาแค่ระดับบรรทัด ระบบประมาณเวลาทีละคำให้"; wide: true
                        Segment { key: "ov_highlight"; options: [{v:"fill",t:"เติมสี"},{v:"word",t:"ทีละคำ"},{v:"glow",t:"เรืองแสง"},{v:"line",t:"ทั้งบรรทัด"}] } }
                    Row2 { label: "รวมบรรทัดที่ร้องต่อกันเป็นกลุ่มเดียว"; hint: "บรรทัดที่ร้องติดกัน (เช่น ประโยคเดียวที่ขึ้นบรรทัดใหม่) สว่างค้างไว้โดยไม่เลื่อนจอ แล้วจางพร้อมกันเมื่อจบ"; SSwitch { key: "ov_group_lines" } }
                    Row2 { label: "ช่องว่างสูงสุดที่ยังนับเป็นกลุ่มเดียว"; hint: "ถ้าเว้นระหว่างบรรทัดนานกว่านี้ จะแยกเป็นกลุ่มใหม่"; adv: true; SSlider { key: "ov_group_gap_s"; from: 0.1; to: 2.0; step: 0.1; decimals: 1; unit: " วิ" } }
                    Row2 { label: "เลื่อนเนื้อเพลงตามเพลงเอง"; kw: "auto scroll"; hint: "ปิด = เนื้อเพลงอยู่นิ่ง ต้องเลื่อนเอง"; SSwitch { key: "ov_auto_scroll" } }
                    Row2 { label: "รอกี่วินาทีหลังเลื่อนเอง แล้วกลับมาตามเพลง"; hint: "หลังคุณเลื่อนอ่านเอง เนื้อเพลงจะกลับมาตามเสียงอัตโนมัติ"; SSlider { key: "ov_resume_s"; from: 1; to: 15; step: 1; decimals: 0; unit: " วิ" } }
                    Row2 { label: "คลิกบรรทัดเพื่อกรอเพลง"; kw: "seek กรอ"; hint: "กรอวิดีโอ YouTube ไปที่บรรทัดนั้น"; SSwitch { key: "ov_click_seek" } }
                    Row2 { label: "แสดงที่มาของเนื้อเพลง"; hint: "ป้ายเล็กมุมขวาล่าง (ซ่อนเองเมื่อเมาส์นิ่งในหน้าต่างหลัก)"; SSwitch { key: "ov_show_source" } }
                }
                Card { title: "คำแปล"
                    Row2 { label: "แสดงคำแปลใต้เนื้อเพลง (หน้าต่างลอย)"; hint: "แสดงเมื่อมีคำแปลภาษาไทย (เพลงภาษาอื่นกดปุ่มแปล)"; SSwitch { key: "ov_show_translation" } }
                    Row2 { label: "ขนาดคำแปล"; hint: "เทียบกับขนาดเนื้อเพลง"; SSlider { key: "ov_translation_size"; from: 0.3; to: 1.2 } }
                    Row2 { label: "แสดงคำอ่านเป็นตัวอักษรโรมัน"; kw: "romanization คำอ่าน"; hint: "เช่น เพลงเกาหลี/ญี่ปุ่นแสดงคำอ่านใต้บรรทัด (ถ้ามีข้อมูล)"; adv: true; SSwitch { key: "look_show_romanization" } }
                }
            }

            // ---------------- แอนิเมชัน ----------------
            Column {
                property int pgIdx: 6; visible: win.show(6); width: parent.width; spacing: 6
                Intro { text: "การเคลื่อนไหว แสง และเบลอของเนื้อเพลง · เริ่มจากเลือกสไตล์สำเร็จรูปแล้วค่อยปรับต่อ · เปิด “แสดงตัวเลือกขั้นสูง” ที่มุมขวาบนเพื่อดูค่าละเอียดเพิ่ม" }
                Card { title: "สไตล์สำเร็จรูป"
                    Row2 { label: "สไตล์การเคลื่อนไหว"; kw: "animation preset เด้ง นุ่ม"; hint: "เลือกชุดสำเร็จรูปแล้วปรับต่อเองได้ · ‘นุ่มนวล’ ใกล้ Apple Music ที่สุด"; wide: true
                        Segment { key: "ov_anim_preset"; options: [{v:"smooth",t:"นุ่มนวล (แบบ Apple)"},{v:"balanced",t:"สมดุล"},{v:"bouncy",t:"เด้งนิดๆ"},{v:"snappy",t:"ฉับไว"},{v:"none",t:"ไม่เคลื่อนไหว"},{v:"custom",t:"กำหนดเอง"}] } }
                    Row2 { label: "ลดการเคลื่อนไหว"; kw: "ปิดแอนิเมชัน เวียนหัว motion"; hint: "เนื้อเพลงเปลี่ยนบรรทัดทันทีโดยไม่เลื่อน ย่อ หรือลอย · เหมาะถ้าเวียนหัวง่ายหรืออยากประหยัดเครื่อง"; SSwitch { key: "ov_reduced_motion" } }
                }
                Card { title: "คำที่กำลังร้อง (เอฟเฟกต์คาราโอเกะ)"
                    Row2 { label: "เอฟเฟกต์ตอนร้องถึงคำ"; kw: "ลอย ขยาย เรืองแสง glow"; wide: true
                        hint: ({ none: "คำอยู่นิ่ง มีแค่การเติมสี",
                                 word: "ทั้งคำลอย/ขยาย/เรืองแสงทันทีที่ร้องถึงคำนั้น (ไม่ต้องรอร้องจบคำ)",
                                 char: "ทีละตัวอักษร: ตัวที่การเติมสีไล่ผ่านจะลอย/ขยาย/เรืองแสงตามไปเรื่อยๆ" })[cfg.ov_word_anim]
                        Segment { key: "ov_word_anim"; options: [{v:"none",t:"ไม่มี"},{v:"word",t:"ทั้งคำ"},{v:"char",t:"ทีละตัวอักษร"}] } }
                    Row2 { label: "ลอยสูงแค่ไหน"; hint: "ลอยขึ้นกี่พิกเซลตอนร้อง · 0 = ไม่ลอย (ใช้ร่วมกับขยาย/เรืองแสงได้)"; SSlider { key: "ov_lift_px"; from: 0; to: 14; step: 0.5; decimals: 1; unit: " px" } }
                    Row2 { label: "ขยายใหญ่แค่ไหน"; hint: "1.00 = ไม่ขยาย · ค่ามากๆ ตัวอักษรข้างเคียงจะซ้อนกัน"; SSlider { key: "ov_word_scale"; from: 1.0; to: 1.35; step: 0.01 } }
                    Row2 { label: "แสงเรืองแรงแค่ไหน"; kw: "glow เรืองแสง"; hint: "0 = ไม่มีแสง · เรืองเฉพาะส่วนที่เติมสีแล้ว"; SSlider { key: "ov_glow_strength"; from: 0; to: 1 } }
                    Row2 { label: "สีของแสงเรืองรอบคำ"; hint: "ใช้กับแสงของคำ และคำเน้น"; wide: true; SColor { key: "ov_glow_color" } }
                    Row2 { label: "ค้างเอฟเฟกต์ไว้จนจบบรรทัด"; hint: "คำที่ร้องแล้วยังลอย/ขยาย/เรืองแสงค้างอยู่จนบรรทัดจบ (ปิด = คืนกลับหลังหน่วงเวลาด้านล่าง)"; SSwitch { key: "ov_word_stay" } }
                    Row2 { label: "ค้างเอฟเฟกต์หลังร้องจบคำ"; hint: "ใช้เมื่อปิด “ค้างเอฟเฟกต์ไว้จนจบบรรทัด” — ค้างอีกเท่านี้ก่อนเริ่มคืนสู่ปกติ"; SSlider { key: "ov_word_hold_ms"; from: 0; to: 2000; step: 50; decimals: 0; unit: " ms" } }
                    Row2 { label: "ใช้เวลาคืนสู่ปกติ"; hint: "ลอยลงและแสงจางลงช้าแค่ไหน (มาก = นุ่ม · 0 = หายทันที)"; SSlider { key: "ov_word_release_ms"; from: 0; to: 3000; step: 50; decimals: 0; unit: " ms" } }
                    Row2 { label: "ใช้เวลาตอนเด่นขึ้น"; hint: "โหมดทั้งคำ: ลอยขึ้น/แสงสว่างขึ้นเร็วแค่ไหน"; adv: true; SSlider { key: "ov_word_anim_ms"; from: 60; to: 1200; step: 20; decimals: 0; unit: " ms" } }
                    Row2 { label: "ลักษณะความนุ่มของการเคลื่อนไหว"; kw: "easing จังหวะ"; wide: true; adv: true
                        hint: ({ smooth: "เริ่มเร็วแล้วค่อยๆ ช้าลงจนหยุดนุ่มๆ (แนะนำ)", gentle: "เริ่มช้า เร็วกลางทาง จบช้า",
                                 spring: "เลยจุดหมายนิดแล้วดีดกลับ (มีเด้ง)", linear: "ความเร็วเท่ากันตลอด" })[cfg.ov_word_ease]
                        Segment { key: "ov_word_ease"; options: [{v:"smooth",t:"นุ่ม"},{v:"gentle",t:"อ่อนโยน"},{v:"spring",t:"เด้ง"},{v:"linear",t:"เส้นตรง"}] } }
                }
                Card { title: "คำเน้น (ลากเสียงยาว)"
                    note: "แบบ Apple Music: คำที่ลากเสียงยาวจะเรืองแสงและขยายตอนร้อง · ใช้ได้กับเพลงที่มีเวลาทีละคำจริงเท่านั้น"
                    Row2 { label: "เน้นคำที่ลากเสียงยาว"; hint: "คำที่ร้องลากนานจะเรืองแสงและขยายตอนร้อง (เหมือน Apple Music)"; SSwitch { key: "ov_emph_on" } }
                    Row2 { label: "คำที่ยาวเท่าไรถึงนับว่าลากเสียง"; hint: "ร้องคำเดียวนานตั้งแต่กี่วินาทีขึ้นไป"; SSlider { key: "ov_emph_min_s"; from: 0.4; to: 4.0; step: 0.1; decimals: 1; unit: " วิ" } }
                    Row2 { label: "แสงเรืองของคำเน้น"; hint: "0 = ไม่เรือง"; SSlider { key: "ov_emph_glow"; from: 0; to: 1 } }
                    Row2 { label: "ขยายของคำเน้น"; hint: "1.00 = ไม่ขยาย"; adv: true; SSlider { key: "ov_emph_scale"; from: 1.0; to: 1.3; step: 0.01 } }
                }
                Card { title: "การเปลี่ยนบรรทัดและการเบลอ"
                    Row2 { label: "วิธีเปลี่ยนบรรทัด"; wide: true
                        hint: ({ fade_move: "บรรทัดเลื่อนมาตรงกลางอย่างนุ่มนวล พร้อมความสว่างที่ค่อยๆ เปลี่ยน (แนะนำ)",
                                 fade: "เลื่อนเร็วกว่าและเน้นการเปลี่ยนความสว่างของบรรทัด",
                                 move: "เลื่อนอย่างเดียว ความสว่างของบรรทัดไม่ค่อยๆ เปลี่ยน (จะเปลี่ยนทันที)",
                                 scale: "บรรทัดปัจจุบันขยายใหญ่ บรรทัดอื่นย่อเล็ก" })[cfg.ov_animation]
                        Segment { key: "ov_animation"; options: [{v:"fade_move",t:"จาง + เลื่อน"},{v:"fade",t:"จาง"},{v:"move",t:"เลื่อน"},{v:"scale",t:"ย่อ/ขยาย"}] } }
                    Row2 { label: "ความเร็วของการเปลี่ยนบรรทัด"; kw: "speed"; hint: "มาก = เปลี่ยนเร็วขึ้น"; adv: true; SSlider { key: "ov_anim_speed"; from: 0.3; to: 3.0; step: 0.05 } }
                    Row2 { label: "ความแรงของการเคลื่อนไหว"; hint: "0 = แทบไม่เคลื่อน · 2 = เคลื่อนแรง"; adv: true; SSlider { key: "ov_animation_intensity"; from: 0; to: 2 } }
                    Row2 { label: "เบลอบรรทัดที่ไม่ได้ร้อง (หน้าต่างหลัก)"; kw: "blur"; hint: "ยิ่งไกลจากบรรทัดที่ร้องยิ่งเบลอ (แบบ Apple Music) · 0 = ไม่เบลอ"; SSlider { key: "fw_blur"; from: 0; to: 1; step: 0.05 } }
                    Row2 { label: "เบลอบรรทัดที่ไม่ได้ร้อง (หน้าต่างลอย)"; hint: "ใช้กับหน้าต่างเนื้อเพลงลอยเท่านั้น"; SSlider { key: "ov_blur"; from: 0; to: 1 } }
                    Row2 { label: "บรรทัดไกลๆ จางลงตามระยะ (หน้าต่างลอย)"; hint: "ต่ำ = จางช้า · สูง = จางเร็ว"; adv: true; SSlider { key: "ov_falloff"; from: 0.03; to: 0.3 } }
                    Row2 { label: "ย่อบรรทัดที่ไม่ได้ร้อง"; hint: "ต่ำ = บรรทัดอื่นเล็กลง · 1.00 = ขนาดเท่ากัน"; adv: true; SSlider { key: "ov_idle_scale"; from: 0.6; to: 1.0 } }
                    Row2 { label: "ให้บรรทัดไกลเคลื่อนช้ากว่าเล็กน้อย"; hint: "ทำให้การเลื่อนดูเป็นคลื่น · 0 = ทุกบรรทัดเคลื่อนพร้อมกัน"; adv: true; SSlider { key: "ov_wave_ms"; from: 0; to: 150; step: 5; decimals: 0; unit: " ms" } }
                    Row2 { label: "ความกระชับของการเลื่อน"; kw: "spring"; hint: "ต่ำ = เลื่อนนุ่มช้า · สูง = กระชับเร็ว"; adv: true; SSlider { key: "look_spring_stiffness"; from: 40; to: 600; step: 10; decimals: 0 } }
                    Row2 { label: "ความเด้งของการเลื่อน"; kw: "damping bounce"; hint: "สูง = ไม่เด้ง · ต่ำ = เด้งนิดๆ ตอนถึงตำแหน่ง"; adv: true; SSlider { key: "look_spring_damping"; from: 8; to: 60; step: 1; decimals: 0 } }
                }
            }
            // ---------------- การซิงก์เพลง ----------------
            Column {
                property int pgIdx: 7; visible: win.show(7); width: parent.width; spacing: 6
                Intro { text: "เนื้อเพลงขึ้นเร็วหรือช้าเกินไปใช่ไหม? ลองปรับเฉพาะเพลงนี้ก่อน · ถ้าทุกเพลงช้า/เร็วเท่ากันเสมอ ให้ใช้ “ชดเชยเสียงหน่วง” (ใช้กับทุกเพลง) · การจัดเวลาอัตโนมัติด้วย AI อยู่ที่หน้า “แหล่งเนื้อเพลงและ AI”" }
                Card { title: "ปรับเวลาให้ตรงกับเสียง"
                    Row2 { label: "ปรับเวลาเนื้อเพลงเฉพาะเพลงนี้"; kw: "เร็ว ช้า offset ไม่ตรง เลื่อนเวลา ซิงก์"
                        hint: "เนื้อเพลงขึ้นเร็วไป = กด −0.1 · ขึ้นช้าไป = กด +0.1 (ทีละ 0.1 วินาที) · จำแยกตามเพลง"
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "−0.1"; onClicked: player.adjustOffset(-0.1) }
                            Text { anchors.verticalCenter: parent.verticalCenter; width: 64; horizontalAlignment: Text.AlignHCenter
                                text: (player.lyricsOffset >= 0 ? "+" : "") + player.lyricsOffset.toFixed(1) + " วิ"; color: win.fg; font.pixelSize: 15; font.weight: Font.Medium }
                            Pill { label: "+0.1"; onClicked: player.adjustOffset(0.1) }
                            Pill { label: "รีเซ็ต"; onClicked: player.resetOffset() }
                        } }
                    Row2 { label: "ชดเชยเสียงหน่วง (ทุกเพลง)"; kw: "latency บลูทูธ ลำโพง หน่วง ดีเลย์ delay"
                        hint: "ได้ยินเสียงร้องก่อนเนื้อเพลงขึ้น = เพิ่มค่านี้ · เนื้อเพลงขึ้นก่อนเสียง = ลดค่า (ใช้ชดเชยเสียงที่ช้าจากลำโพง/บลูทูธ)"
                        SSlider { key: "ov_latency_ms"; from: -500; to: 800; step: 10; decimals: 0; unit: " ms" } }
                    Row2 { label: "เริ่มเลื่อนบรรทัดก่อนถึงเวลาร้อง"; kw: "เลื่อนช้า เลื่อนไว lead"
                        hint: "เนื้อเพลงเริ่มเลื่อนล่วงหน้าเท่านี้ เพื่อให้ถึงตำแหน่งพอดีตอนเริ่มร้อง · 0 = เลื่อนตอนเริ่มร้องพอดี (รู้สึกช้า)"
                        SSlider { key: "ov_scroll_lead_s"; from: 0; to: 1; step: 0.05; decimals: 2; unit: " วิ" } }
                }
                Card { title: "สถานะการเชื่อมต่อ"
                    Row2 { label: "การเชื่อมต่อกับ YouTube"
                        hint: player.bridgeConnected ? "● เชื่อมต่อกับส่วนขยายแล้ว" : (player.everConnected ? "● การเชื่อมต่อหลุด (กำลังเชื่อมต่อใหม่)" : "● ยังไม่เชื่อมต่อ (เปิด Chrome ที่ติดตั้งส่วนขยายไว้)")
                        Row { anchors.right: parent.right; spacing: 8
                            Pill { label: "เชื่อมต่อใหม่"; onClicked: player.reconnectYouTube() }
                            Pill { label: "ติดตั้งส่วนขยาย"; onClicked: win.installRequested() }
                        } }
                    Row2 { label: "ความแม่นยำของเวลาเนื้อเพลง"
                        hint: player.sourceLabel.length === 0 ? "ยังไม่มีเนื้อเพลง" : (player.timingApprox ? "เวลาทีละคำเป็นการประมาณ (ไม่ใช่เวลาจริงจากแหล่ง) · เปิดให้ AI จัดเวลาจะแม่นขึ้น" : "เวลาตรงตามแหล่งเนื้อเพลง") }
                }
            }


            // ---------------- คีย์ลัด ----------------
            Column {
                property int pgIdx: 0; visible: win.show(0); width: parent.width; spacing: 6
                Text { width: parent.width; wrapMode: Text.Wrap; color: win.fg2; font.pixelSize: 12; font.family: cfg.look_font_family
                    visible: win.q.length === 0
                    text: "รูปแบบ Ctrl+Alt+L (ใช้ Ctrl, Alt, Shift, Win + ตัวอักษร/ตัวเลข/F1-F12/ลูกศร) · ว่าง = ปิดคีย์ลัดนั้น · ใช้ได้แม้ไม่ได้โฟกัสโปรแกรม" }
                Text { width: parent.width; wrapMode: Text.Wrap; visible: cfg.hk_status.length > 0; color: "#FCA5A5"; font.pixelSize: 12; text: cfg.hk_status }
                Card { title: "คีย์ลัดทั้งระบบ (ใช้ได้แม้ไม่ได้เปิดหน้าต่างแอป)"
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
                Card { title: "คีย์ลัดในหน้าต่างหลัก"
                    Row2 { label: "F / F11 เต็มจอ · Esc ออก · Space เล่น/หยุด · ← → กรอ 5 วิ · N / P เพลงถัดไป/ก่อนหน้า · ↑ ↓ วอลลุ่ม · M ปิดเสียง · L ซ่อน/แสดงเนื้อเพลง · T คำแปล · + − ขนาดเนื้อเพลง · [ ] ปรับเวลา" }
                }
            }
        }
    }
}
