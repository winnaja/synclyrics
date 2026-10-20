// หน้าต่างเนื้อเพลงลอย (add by win/UX UI.txt หมวด 3, 5, 8, 12)
// - frameless โปร่งใส ไม่ขึ้น Taskbar/Alt+Tab (Qt.Tool) always-on-top ปรับได้ · ลากย้ายด้วยปุ่ม "ย้าย" · ปรับขนาดที่ขอบ
// - 2 โหมดลอย: minimal (บรรทัดเดียว พื้นหลังโปร่งมาก) · focus (3 บรรทัด ค่าเริ่มต้น) — ขนาดจำแยกตามโหมด
//   โหมดเต็ม (ปก + ทั้งเพลง + เต็มจอ) เป็นหน้าต่างแยก FullWindow.qml (ปุ่ม "เต็มจอ" ที่แถบควบคุม)
// - พื้นหลัง: โปร่งใส / กระจกฝ้า / ดำนุ่ม / ทึบ / gradient · ความโปร่งใสพื้นหลังแยกจากตัวอักษร
// - แถบควบคุมเล็กๆ โผล่ตอนชี้เมาส์ (fade) · ล็อกตำแหน่ง · click-through · จำตำแหน่ง/ขนาด · กันหลุดจอ
// ทุกค่าอ่านจาก cfg (เปลี่ยนในหน้าตั้งค่าแล้วเห็นผลทันที)
import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic

Window {
    id: win
    objectName: "overlay"

    // เวลาของเพลง (วินาที) อัปเดตทุกเฟรมจาก FrameAnimation เดียวเท่านั้น (ไม่ใช้ Timer)
    property real pos: 0
    // เวลาที่ใช้หาบรรทัด = เวลาเสียง - offset ที่ผู้ใช้ปรับ
    readonly property real lyricPos: pos - player.lyricsOffset
    // ค่า "full" เป็นของเก่า (ตอนนี้โหมดเต็มเป็นหน้าต่างแยก) — มองเป็น focus เสมอ
    readonly property string mode: cfg.ov_mode === "full" ? "focus" : cfg.ov_mode
    readonly property bool locked: cfg.ov_locked

    signal openSettingsRequested()

    // เปิดหน้าต่างโหมดเต็มอยู่ = ซ่อนหน้าต่างลอย (ไม่ให้เนื้อเพลงซ้อนกัน)
    visible: cfg.ov_visible && !cfg.fw_open
    opacity: cfg.ov_window_opacity   // ความโปร่งใสทั้งหน้าต่าง (UX UI ข้อ 5.2)
    color: "transparent"
    title: "SyncLyrics"
    minimumWidth: 240
    minimumHeight: 64
    flags: Qt.FramelessWindowHint | Qt.Tool
        | (cfg.ov_always_on_top ? Qt.WindowStaysOnTopHint : 0)
        | (cfg.ov_click_through ? Qt.WindowTransparentForInput : 0)

    // ---------- ขนาด/ตำแหน่ง ----------
    property bool applying: false   // กำลังตั้งค่าเองจากโปรแกรม (ไม่ต้องบันทึกซ้ำ)

    function applyModeSize() {
        applying = true
        width = cfg["ov_w_" + mode]
        height = cfg["ov_h_" + mode]
        applying = false
    }

    function screenOf(x, y) {
        var list = Qt.application.screens
        for (var i = 0; i < list.length; ++i) {
            var s = list[i]
            if (x >= s.virtualX && x < s.virtualX + s.width && y >= s.virtualY && y < s.virtualY + s.height)
                return s
        }
        return list.length > 0 ? list[0] : null
    }

    // กันหน้าต่างหลุดนอกพื้นที่ที่มองเห็น (ถอดจอเสริม/เปลี่ยนความละเอียด): ต้องเห็นอย่างน้อย 120x40 px ไม่งั้นย้ายมาจอหลัก
    function ensureVisible() {
        var list = Qt.application.screens
        for (var i = 0; i < list.length; ++i) {
            var s = list[i]
            var ox = Math.min(x + width, s.virtualX + s.width) - Math.max(x, s.virtualX)
            var oy = Math.min(y + height, s.virtualY + s.height) - Math.max(y, s.virtualY)
            if (ox >= 120 && oy >= 40)
                return
        }
        placePreset("bottom_center")
    }

    // ตำแหน่งสำเร็จรูป (UX UI ข้อ 3.4): center / top_center / bottom_center / top_left / top_right / bottom_left / bottom_right
    function placePreset(name) {
        var s = screen ? screen : (Qt.application.screens.length > 0 ? Qt.application.screens[0] : null)
        if (!s) return
        var m = 24
        var gx = s.virtualX, gy = s.virtualY, gw = s.width, gh = s.height
        var nx = gx + (gw - width) / 2, ny = gy + (gh - height) / 2
        if (name === "center_h") ny = y   // กึ่งกลางแนวนอน คงความสูงเดิม
        if (name.indexOf("top") === 0) ny = gy + m
        if (name.indexOf("bottom") === 0) ny = gy + gh - height - m - 40   // เผื่อ taskbar
        if (name.slice(-4) === "left") nx = gx + m
        if (name.slice(-5) === "right") nx = gx + gw - width - m
        x = Math.round(nx)
        y = Math.round(ny)
    }

    // ดูดติดขอบจอ (UX UI ข้อ 3.4 Snap to screen edges): เมื่อวางห่างขอบไม่เกิน 18px ดูดเข้าขอบ (ไม่ทำตอนล็อก/คลิกทะลุ)
    function snapToEdges() {
        if (locked) return
        var s = screenOf(x + width / 2, y + height / 2)
        if (!s) return
        var near = 18, nx = x, ny = y
        if (Math.abs(x - s.virtualX) <= near) nx = s.virtualX
        else if (Math.abs((x + width) - (s.virtualX + s.width)) <= near) nx = s.virtualX + s.width - width
        if (Math.abs(y - s.virtualY) <= near) ny = s.virtualY
        else if (Math.abs((y + height) - (s.virtualY + s.height)) <= near) ny = s.virtualY + s.height - height
        if (nx !== x || ny !== y) { applying = true; x = nx; y = ny; applying = false }
    }

    // จำนวนบรรทัดของโหมด focus (ตั้งค่า "จำนวนบรรทัด") -> ความสูงหน้าต่าง
    function heightForLines(n) {
        return Math.round(n * cfg.ov_font_size * cfg.ov_line_spacing * 1.35 + 40)
    }
    Connections {
        target: cfg
        function onOv_visible_linesChanged() {
            if (win.mode === "focus") cfg.ov_h_focus = Math.max(100, Math.min(2000, win.heightForLines(cfg.ov_visible_lines)))
        }
        function onOv_h_focusChanged() {
            if (win.mode === "focus" && Math.abs(win.height - cfg.ov_h_focus) > 1) { win.applying = true; win.height = cfg.ov_h_focus; win.applying = false }
        }
        function onOv_w_focusChanged() {
            if (win.mode === "focus" && Math.abs(win.width - cfg.ov_w_focus) > 1) { win.applying = true; win.width = cfg.ov_w_focus; win.applying = false }
        }
        function onOv_h_minimalChanged() {
            if (win.mode === "minimal" && Math.abs(win.height - cfg.ov_h_minimal) > 1) { win.applying = true; win.height = cfg.ov_h_minimal; win.applying = false }
        }
        function onOv_w_minimalChanged() {
            if (win.mode === "minimal" && Math.abs(win.width - cfg.ov_w_minimal) > 1) { win.applying = true; win.width = cfg.ov_w_minimal; win.applying = false }
        }
        function onOv_monitorChanged() { win.moveToMonitor(cfg.ov_monitor) }
    }

    // ย้ายไปจอที่ N (UX UI หมวด 12 เลือกจอ)
    function moveToMonitor(i) {
        var list = Qt.application.screens
        if (list.length === 0) return
        var s = list[Math.min(i, list.length - 1)]
        screen = s
        applying = true
        x = Math.round(s.virtualX + (s.width - width) / 2)
        y = Math.round(s.virtualY + s.height - height - 64)
        applying = false
        saveGeom.restart()
    }

    // บันทึกขนาด/ตำแหน่งหลังผู้ใช้ปล่อยมือ (debounce — ไม่เซฟทุกพิกเซล)
    Timer {
        id: saveGeom
        interval: 600
        onTriggered: {
            win.snapToEdges()
            if (!cfg.ov_remember_position || win.visibility === Window.Minimized) return
            cfg["ov_w_" + win.mode] = win.width
            cfg["ov_h_" + win.mode] = win.height
            cfg.ov_x = win.x
            cfg.ov_y = win.y
        }
    }
    onWidthChanged: { if (!applying) saveGeom.restart(); if (blurBehind) blurTimer.restart() }
    onHeightChanged: { if (!applying) saveGeom.restart(); if (blurBehind) blurTimer.restart() }
    onXChanged: if (!applying) saveGeom.restart()
    onYChanged: if (!applying) saveGeom.restart()
    onModeChanged: {
        // เปลี่ยนโหมด: ใช้ขนาดของโหมดใหม่ โดยคงกึ่งกลางหน้าต่างไว้ที่เดิม
        var cx = x + width / 2, cy = y + height / 2
        applyModeSize()
        applying = true
        x = Math.round(cx - width / 2)
        y = Math.round(cy - height / 2)
        applying = false
        ensureVisible()
        saveGeom.restart()
    }
    Component.onCompleted: {
        applyModeSize()
        applying = true
        if (cfg.ov_remember_position && cfg.ov_x !== "" && cfg.ov_y !== "") {
            x = cfg.ov_x
            y = cfg.ov_y
        } else {
            var list = Qt.application.screens
            if (list.length > 0) screen = list[Math.min(cfg.ov_monitor, list.length - 1)]
            placePreset(cfg.ov_start_position)
        }
        applying = false
        ensureVisible()
    }
    onScreenChanged: Qt.callLater(ensureVisible)

    FrameAnimation {
        running: win.visible
        onTriggered: win.pos = clockBridge.position()
    }

    // ---------- เบลอฉากหลังจริง (acrylic, Windows) ----------
    // พื้นหลัง "กระจกฝ้า" + ov_blur_behind: เบลอฉากหลังจริง แล้วตัดมุมหน้าต่างให้โค้งตรงกับพื้นหลัง (ไม่ให้เบลอล้นที่มุม)
    readonly property bool blurBehind: cfg.ov_bg_style === "frosted" && cfg.ov_blur_behind && !minimal
    function syncBlur() { settingsBridge.applyBlurBehind(win.blurBehind, cfg.ov_corner_radius) }
    Timer { id: blurTimer; interval: 150; onTriggered: win.syncBlur() }
    onBlurBehindChanged: blurTimer.restart()
    onVisibleChanged: if (visible) blurTimer.restart()
    onFlagsChanged: blurTimer.restart()      // เปลี่ยน flags = สร้างหน้าต่างจริงใหม่ ต้องใส่เอฟเฟกต์ใหม่
    Connections { target: cfg; function onOv_corner_radiusChanged() { if (win.blurBehind) blurTimer.restart() } }

    // ---------- เฟรมหน้าต่าง ----------
    // โหมด minimal: พื้นหลังโปร่งมาก ไม่มีเงา/ขอบ (UX UI ข้อ 3.2 A)
    readonly property bool minimal: mode === "minimal"
    // เบลอฉากหลัง = ไม่มีขอบเงา (พื้นที่ blur คือทั้งหน้าต่าง ถ้ามีขอบโปร่งใสจะเห็นเป็นแถบเบลอล้น)
    readonly property int shadowPad: !minimal && !blurBehind && cfg.ov_shadow > 0.01 && cfg.ov_bg_style !== "transparent" ? 12 : 0

    Item {
        id: frame
        anchors.fill: parent
        anchors.margins: win.shadowPad

        // เงานุ่มของหน้าต่าง: สี่เหลี่ยมโปร่งใสซ้อนหลายชั้น (เบา ไม่ใช้ shader)
        Repeater {
            model: win.shadowPad > 0 ? 4 : 0
            Rectangle {
                required property int index
                anchors.fill: parent
                anchors.margins: -(index + 1) * 3
                radius: cfg.ov_corner_radius + (index + 1) * 3
                color: "#000000"
                opacity: 0.07 * cfg.ov_shadow * (4 - index) / 2
            }
        }

        // พื้นหลัง
        Rectangle {
            id: bg
            anchors.fill: parent
            // เบลอฉากหลังจริง: ระบบตัดมุมหน้าต่างรัศมี 8px (Windows 11) พื้นหลังต้องโค้งเท่ากันไม่งั้นมีมุมเหลี่ยมโผล่
            radius: win.blurBehind ? 8 : cfg.ov_corner_radius
            readonly property string style: cfg.ov_bg_style
            readonly property real alphaMul: win.minimal ? 0.35 : 1.0
            color: style === "transparent" ? "transparent" : Qt.alpha(cfg.ov_bg_color, cfg.ov_bg_opacity * alphaMul)
            gradient: style === "gradient" ? grad : null
            Gradient {
                id: grad
                GradientStop { position: 0.0; color: Qt.alpha(cfg.ov_bg_color, cfg.ov_bg_opacity * bg.alphaMul) }
                GradientStop { position: 1.0; color: Qt.alpha(cfg.ov_bg_color2, cfg.ov_bg_opacity * bg.alphaMul) }
            }
            border.width: !win.minimal && cfg.ov_border_opacity > 0.005 ? 1 : 0
            border.color: Qt.rgba(1, 1, 1, cfg.ov_border_opacity)
            // กระจกฝ้า: แสงบางๆ ด้านบน (ไม่ใช้เอฟเฟกต์หนัก)
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                visible: bg.style === "frosted"
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.09) }
                    GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.02) }
                    GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0.05) }
                }
            }
        }

        // ---------- เนื้อหา ----------
        Item {
            id: content
            anchors.fill: parent
            anchors.margins: win.mode === "minimal" ? 6 : 12
            clip: true

            LyricsView {
                id: lyricsView
                anchors.fill: parent
                lyricPos: win.lyricPos
                showSourceLabel: false   // หน้าต่างเล็ก: ป้ายแหล่งไปอยู่ที่แถบชื่อเพลงตอนชี้เมาส์ (ไม่ทับบรรทัดเนื้อเพลง)
            }
        }

        // ---------- แถบควบคุม (โผล่ตอนชี้เมาส์) ----------
        HoverHandler { id: hover }

        component BarBtn: Rectangle {
            id: btn
            property string label: ""
            property bool active: false
            property bool dim: false
            property string tip: ""
            signal clicked()
            activeFocusOnTab: true
            ToolTip.visible: bh.hovered && tip.length > 0
            ToolTip.text: tip
            ToolTip.delay: 500
            Keys.onSpacePressed: btn.clicked()
            Keys.onReturnPressed: btn.clicked()
            width: lbl.implicitWidth + 18
            height: 26
            radius: 13
            opacity: dim ? 0.4 : 1.0
            border.width: activeFocus ? 2 : 0
            border.color: "#FFFFFF"
            color: active ? Qt.alpha(cfg.ov_accent_color, 0.55)
                          : Qt.rgba(1, 1, 1, tap.pressed ? 0.3 : (bh.hovered ? 0.22 : 0.12))
            Behavior on color { ColorAnimation { duration: 120 } }
            Text {
                id: lbl
                anchors.centerIn: parent
                text: btn.label
                color: "#FFFFFF"
                font.pixelSize: 12
                font.family: cfg.look_font_family
            }
            HoverHandler { id: bh }
            TapHandler { id: tap; onTapped: btn.clicked() }
        }

        Rectangle {
            id: bar
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: 6
            width: barRow.implicitWidth + 12
            height: 34
            radius: 17
            color: Qt.rgba(0, 0, 0, 0.62)
            visible: opacity > 0.01
            opacity: cfg.ov_hover_controls && hover.hovered && !cfg.ov_click_through ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: cfg.ov_reduced_motion ? 0 : 180 } }

            Row {
                id: barRow
                anchors.centerIn: parent
                spacing: 4
                BarBtn {
                    label: "ย้าย"
                    tip: win.locked ? "ปลดล็อกก่อนจึงจะย้ายได้" : "ลากเพื่อย้ายหน้าต่าง"
                    dim: win.locked
                    DragHandler {
                        target: null
                        enabled: !win.locked
                        onActiveChanged: if (active) win.startSystemMove()
                    }
                }
                BarBtn {
                    label: win.locked ? "ล็อกอยู่" : "ล็อก"
                    tip: "ล็อกตำแหน่งและขนาด (" + cfg.hk_lock + ")"
                    active: win.locked
                    onClicked: cfg.ov_locked = !cfg.ov_locked
                }
                BarBtn {
                    label: win.mode === "minimal" ? "โหมด: เล็ก" : "โหมด: โฟกัส"
                    tip: "สลับระหว่างบรรทัดเดียว / 3 บรรทัด"
                    onClicked: cfg.ov_mode = win.mode === "minimal" ? "focus" : "minimal"
                }
                BarBtn {
                    label: "เต็มจอ"
                    tip: "เปิดโหมดเต็ม: หน้าต่างใหญ่แบบ Apple Music / เต็มจอ (" + cfg.hk_full_toggle + ")"
                    onClicked: cfg.fw_open = true
                }
                BarBtn {
                    visible: player.hasTranslation
                    tip: "เปิด/ปิดคำแปล (" + cfg.hk_translation + ")"
                    label: "แปล"
                    active: player.showTranslation
                    onClicked: player.toggleTranslation()
                }
                BarBtn {
                    visible: lyricsView.lineCount > 0 || !player.lyricsLoading
                    tip: "เปลี่ยนไปเนื้อเพลงอันดับถัดไป"
                    label: "ตัวอื่น"
                    onClicked: player.nextCandidate()
                }
                BarBtn { label: "ตั้งค่า"; tip: "ปรับรูปลักษณ์/แอนิเมชัน/คีย์ลัด"; onClicked: win.openSettingsRequested() }
                BarBtn { label: "ซ่อน"; tip: "ซ่อนหน้าต่าง (เปิดคืนได้จากไอคอนถาดระบบ หรือ " + cfg.hk_show_hide + ")"; onClicked: cfg.ov_visible = false }
            }
        }

        // ชื่อเพลงเล็กๆ มุมซ้ายบนตอนชี้เมาส์ (โหมดที่ไม่มีปก)
        Text {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.margins: 12
            anchors.topMargin: 14
            width: Math.max(0, parent.width - bar.width - 36)
            visible: bar.opacity > 0.01
            opacity: bar.opacity
            text: (player.title.length > 0 ? player.title + (player.artist.length > 0 ? " · " + player.artist : "") : "")
                + (player.sourceLabel.length > 0 ? "  —  " + player.sourceLabel + (player.timingApprox ? " · เวลาทีละคำเป็นการประมาณ" : "") : "")
            color: cfg.ov_secondary_color
            font.pixelSize: 12
            font.family: cfg.look_font_family
            elide: Text.ElideRight
        }

        // ---------- ปรับขนาดที่ขอบ (ปิดเมื่อล็อก) ----------
        component Edge: MouseArea {
            property int edges: 0
            enabled: !win.locked && !cfg.ov_click_through
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton
            onPressed: win.startSystemResize(edges)
        }
        Edge { edges: Qt.LeftEdge; x: -win.shadowPad; y: 12; width: 6 + win.shadowPad; height: parent.height - 24; cursorShape: Qt.SizeHorCursor }
        Edge { edges: Qt.RightEdge; x: parent.width - 6; y: 12; width: 6 + win.shadowPad; height: parent.height - 24; cursorShape: Qt.SizeHorCursor }
        Edge { edges: Qt.TopEdge; x: 12; y: -win.shadowPad; width: parent.width - 24; height: 6 + win.shadowPad; cursorShape: Qt.SizeVerCursor }
        Edge { edges: Qt.BottomEdge; x: 12; y: parent.height - 6; width: parent.width - 24; height: 6 + win.shadowPad; cursorShape: Qt.SizeVerCursor }
        Edge { edges: Qt.LeftEdge | Qt.TopEdge; x: -win.shadowPad; y: -win.shadowPad; width: 12 + win.shadowPad; height: 12 + win.shadowPad; cursorShape: Qt.SizeFDiagCursor }
        Edge { edges: Qt.RightEdge | Qt.BottomEdge; x: parent.width - 12; y: parent.height - 12; width: 12 + win.shadowPad; height: 12 + win.shadowPad; cursorShape: Qt.SizeFDiagCursor }
        Edge { edges: Qt.RightEdge | Qt.TopEdge; x: parent.width - 12; y: -win.shadowPad; width: 12 + win.shadowPad; height: 12 + win.shadowPad; cursorShape: Qt.SizeBDiagCursor }
        Edge { edges: Qt.LeftEdge | Qt.BottomEdge; x: -win.shadowPad; y: parent.height - 12; width: 12 + win.shadowPad; height: 12 + win.shadowPad; cursorShape: Qt.SizeBDiagCursor }

        // ---------- ข้อความแจ้งสั้นๆ ----------
        Rectangle {
            id: toast
            property string text: ""
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 10
            width: toastText.implicitWidth + 24
            height: 28
            radius: 14
            color: Qt.rgba(0, 0, 0, 0.7)
            opacity: 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Text { id: toastText; anchors.centerIn: parent; text: toast.text; color: "#FFFFFF"; font.pixelSize: 12; font.family: cfg.look_font_family }
            Timer { id: toastTimer; interval: 3500; onTriggered: toast.opacity = 0 }
            function show(t) { text = t; opacity = 1; toastTimer.restart() }
        }
    }

    function showToast(text) { toast.show(text) }

    // เมาส์ทะลุเปิดอยู่: บอกวิธีปิด (UX UI ข้อ 8.3 — ห้ามให้ผู้ใช้คิดว่าแอปค้าง)
    Connections {
        target: cfg
        function onOv_click_throughChanged() {
            if (cfg.ov_click_through)
                win.showToast("คลิกทะลุเปิดอยู่ — ปิดได้ที่ไอคอนถาดระบบ หรือกด " + cfg.hk_click_through)
        }
    }

    // ---------- คีย์ลัดเมื่อหน้าต่างนี้ถูกโฟกัส ----------
    Shortcut { sequence: "["; onActivated: player.adjustOffset(-0.1) }
    Shortcut { sequence: "]"; onActivated: player.adjustOffset(0.1) }
    Shortcut { sequence: "Space"; onActivated: player.togglePause() }
    Shortcut { sequence: "Left"; onActivated: player.seek(Math.max(0, win.pos - 5)) }
    Shortcut { sequence: "Right"; onActivated: player.seek(win.pos + 5) }
}
