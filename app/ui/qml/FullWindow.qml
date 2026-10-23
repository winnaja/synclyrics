// หน้าต่างโหมดเต็ม (แบบ Apple Music) — UX UI ข้อ 3.2 C "Full Lyrics Mode": เนื้อเพลงทั้งเพลงในหน้าต่างขนาดใหญ่
// - หน้าต่างปกติ (มีแถบชื่อ ย่อ/ขยาย/ปิดได้เหมือน Chrome) + เต็มจอ (F / F11, Esc ออก) จำขนาด/ตำแหน่ง
// - พื้นหลังไหลลื่นสีจากปกเพลง (fluid shader) · ปกใหญ่ซ้าย (FullPanel) เนื้อเพลงใหญ่ชิดซ้ายขวา
// - เต็มจอ: แถบควบคุมและเมาส์ซ่อนเองเมื่อไม่ขยับ (cfg.fw_idle_hide_s) · ขนาดตัวอักษรตามความสูงหน้าต่าง × cfg.fw_font_scale
// - เปิดหน้าต่างนี้แล้วหน้าต่างเนื้อเพลงลอยจะซ่อน (ไม่ให้เนื้อเพลงซ้อนกัน)
import QtQuick
import QtQuick.Window
import QtQuick.Controls

Window {
    id: win
    objectName: "fullWindow"

    signal placeRequested(string name)
    signal installRequested()
    signal quitRequested()
    signal hiddenToTray()

    // หน้าตั้งค่าอยู่ในหน้าต่างหลักนี้ (ซ้อนทับเครื่องเล่นที่ยังเล่นต่อข้างใต้) — ไม่เปิดหน้าต่างแยก
    property bool settingsOpen: false
    property bool settingsFromFloating: false     // เปิดตั้งค่าตอนใช้หน้าต่างลอยอยู่ → กลับแล้วปิดหน้าต่างหลัก คืนสถานะเดิม
    property alias settingsView: settingsView
    function openSettings() {
        settingsFromFloating = !cfg.fw_open
        cfg.fw_open = true
        settingsOpen = true
        raise()
        requestActivate()
    }
    function closeSettings() {
        settingsOpen = false
        if (settingsFromFloating) { cfg.fw_fullscreen = false; cfg.fw_open = false }
        settingsFromFloating = false
    }
    Connections { target: cfg; function onFw_openChanged() { if (!cfg.fw_open) { win.settingsOpen = false; win.settingsFromFloating = false } } }

    // เวลาของเพลง (วินาที) + เวลาแอนิเมชันพื้นหลัง อัปเดตจาก FrameAnimation เดียว
    property real pos: 0
    property real t: 0
    // + ov_latency_ms: ชดเชยความหน่วงจนเห็นเนื้อตรงกับเสียง (เวลาจาก YouTube ไม่ใช่เวลาที่เสียงออกลำโพงจริง)
    readonly property real lyricPos: pos - player.lyricsOffset + cfg.ov_latency_ms / 1000
    readonly property bool fs: visibility === Window.FullScreen
    property bool idle: false

    visibility: !cfg.fw_open ? Window.Hidden
        : (cfg.fw_fullscreen ? Window.FullScreen : (cfg.fw_maximized ? Window.Maximized : Window.Windowed))
    minimumWidth: 640
    minimumHeight: 420
    title: player.title.length > 0 ? player.title + " — SyncLyrics" : "SyncLyrics"
    color: "#101018"

    // ปิดด้วยปุ่มของหน้าต่าง = ซ่อน (โปรแกรมยังทำงาน) · กำลังออกจากโปรแกรมจริง = ยอมปิด
    onClosing: (close) => {
        if (settingsBridge.quitting) return
        if (!cfg.st_close_to_tray) { settingsBridge.quit(); return }   // ผู้ใช้เลือกให้ปุ่มปิด = ปิดโปรแกรม
        close.accepted = false
        settingsOpen = false
        settingsFromFloating = false
        cfg.fw_fullscreen = false
        cfg.fw_open = false
        win.hiddenToTray()
    }
    // สถานะที่ผู้ใช้เปลี่ยนเองผ่านระบบ (ปุ่มขยายของ Windows) ให้ cfg ตามเสมอ
    onVisibilityChanged: () => {
        // จำสถานะที่ผู้ใช้เปลี่ยนเองผ่านปุ่มของ Windows: ออกจาก fullscreen แล้วกลับไปสถานะขยายเต็ม/ปกติเดิม
        if (win.visibility === Window.FullScreen) cfg.fw_fullscreen = true
        else if (win.visibility === Window.Maximized) { cfg.fw_fullscreen = false; cfg.fw_maximized = true }
        else if (win.visibility === Window.Windowed) { cfg.fw_fullscreen = false; cfg.fw_maximized = false }
        
    }

    // ---------- ขนาด/ตำแหน่ง ----------
    property bool applying: false
    function ensureVisible() {
        var list = Qt.application.screens
        for (var i = 0; i < list.length; ++i) {
            var s = list[i]
            var ox = Math.min(x + width, s.virtualX + s.width) - Math.max(x, s.virtualX)
            var oy = Math.min(y + height, s.virtualY + s.height) - Math.max(y, s.virtualY)
            if (ox >= 160 && oy >= 60) return
        }
        centerOnScreen()
    }
    function centerOnScreen() {
        var s = screen ? screen : (Qt.application.screens.length > 0 ? Qt.application.screens[0] : null)
        if (!s) return
        x = Math.round(s.virtualX + (s.width - width) / 2)
        y = Math.round(s.virtualY + (s.height - height) / 2)
    }
    Component.onCompleted: {
        applying = true
        width = cfg.fw_w
        height = cfg.fw_h
        if (cfg.fw_x !== "" && cfg.fw_y !== "") { x = cfg.fw_x; y = cfg.fw_y } else centerOnScreen()
        applying = false
        ensureVisible()
    }
    Timer {
        id: saveGeom
        interval: 600
        onTriggered: {
            if (win.visibility !== Window.Windowed) return   // เต็มจอ/ขยายสุด/ซ่อน ไม่บันทึกขนาด
            cfg.fw_w = win.width
            cfg.fw_h = win.height
            cfg.fw_x = win.x
            cfg.fw_y = win.y
        }
    }
    onWidthChanged: if (!applying) saveGeom.restart()
    onHeightChanged: if (!applying) saveGeom.restart()
    onXChanged: if (!applying) saveGeom.restart()
    onYChanged: if (!applying) saveGeom.restart()

    // ---------- เวลา/แอนิเมชัน (เฉพาะตอนมองเห็น) ----------
    FrameAnimation {
        running: win.visible
        onTriggered: {
            win.pos = clockBridge.position()
            if (!cfg.ov_reduced_motion) win.t += frameTime
        }
    }

    // ---------- พื้นหลัง ----------
    Rectangle { anchors.fill: parent; color: "#101018" }
    ShaderEffect {
        id: fluid
        anchors.fill: parent
        visible: cfg.fw_background === "fluid"
        property real time: win.t
        property real brightness: cfg.fw_brightness
        property real speed: cfg.ov_reduced_motion ? 0 : 1
        property vector2d aspect: Qt.vector2d(width / Math.max(1, height), 1)
        // สีเปลี่ยนตามเพลงอย่างนุ่มนวล (0.9 วิ)
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
    // ม่านเข้มบางๆ ให้เนื้อเพลงอ่านออกเสมอ: ปกสว่าง/สีอ่อน = ม่านเข้มขึ้น (ค่อยๆ เปลี่ยนตามเพลง) · ขอบล่างเข้มขึ้นนิดให้ปุ่มชัด
    readonly property color pal0: player.palette[0]
    readonly property color pal1: player.palette[1]
    readonly property color pal2: player.palette[2]
    readonly property real palLum: {
        var a = [pal0, pal1, pal2], l = 0
        for (var i = 0; i < 3; ++i) l += 0.2126 * a[i].r + 0.7152 * a[i].g + 0.0722 * a[i].b
        return l / 3
    }
    Rectangle {
        anchors.fill: parent
        visible: cfg.fw_background === "fluid"
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, Math.max(0.03, Math.min(0.45, (win.palLum - 0.3) * 1.1))) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, Math.max(0.1, Math.min(0.55, (win.palLum - 0.22) * 1.2))) }
        }
        Behavior on opacity { NumberAnimation { duration: 900 } }
    }
    Rectangle {
        anchors.fill: parent
        visible: cfg.fw_background === "solid"
        color: Qt.darker(player.palette[0], 2.2)
    }

    // ---------- เนื้อหา ----------
    // แถบบน (ปุ่มเมนู) เป็นแถบของตัวเอง เนื้อเพลงเริ่มใต้แถบนี้ → ปุ่มไม่ทับบรรทัดเนื้อเพลง คลิกปุ่มไม่ไปโดนบรรทัด
    readonly property real barH: 64
    readonly property bool lyricsOn: cfg.fw_lyrics_visible

    // เวที: อยู่กึ่งกลางหน้าต่าง กว้างสูงสุด 1500 (จอกว้างไม่ให้ปกกับเนื้อเพลงห่างกัน)
    Item {
        id: stage
        x: (win.width - width) / 2
        y: win.barH
        width: Math.min(win.width - (win.fs ? 120 : 72), 1500)
        height: win.height - win.barH - (win.fs ? 48 : 28)
        readonly property bool wide: width >= 760
        // ปก+แผงควบคุม: เนื้อเพลงเปิด = เสาซ้าย ~38% · ซ่อนเนื้อเพลง = ปกใหญ่กึ่งกลาง
        readonly property real gap: width * 0.07
        readonly property real sideW: Math.max(300, Math.min(width * 0.38, 520))
        readonly property real soloW: Math.min(width * 0.6, 640)

        FullPanel {
            id: panel
            visible: win.lyricsOn ? stage.wide : true
            width: win.lyricsOn ? (stage.wide ? stage.sideW : 0) : stage.soloW
            height: stage.height
            x: win.lyricsOn ? 0 : (stage.width - width) / 2
            pos: win.pos
            coverScale: cfg.fw_cover_scale
            showVolume: cfg.fw_show_volume
            lyricsOn: win.lyricsOn
            onLyricsToggled: cfg.fw_lyrics_visible = !cfg.fw_lyrics_visible
            Behavior on x { enabled: !cfg.ov_reduced_motion; NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            Behavior on width { enabled: !cfg.ov_reduced_motion; NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
        }

        // หัวเรื่องเล็กเมื่อหน้าต่างแคบ (ไม่มีแผงปก)
        Column {
            id: narrowHead
            visible: win.lyricsOn && !stage.wide
            width: stage.width
            spacing: 2
            Text { width: parent.width; text: player.title.length > 0 ? player.title : "ยังไม่มีเพลง"; color: "#FFFFFF"; elide: Text.ElideRight
                font.pixelSize: 20; font.weight: Font.Bold; font.family: cfg.look_font_family }
            Text { width: parent.width; text: player.artist; color: Qt.rgba(1, 1, 1, 0.65); elide: Text.ElideRight
                font.pixelSize: 14; font.family: cfg.look_font_family }
        }

        LyricsView {
            id: lyricsView
            visible: opacity > 0.01
            opacity: win.lyricsOn ? 1 : 0
            Behavior on opacity { enabled: !cfg.ov_reduced_motion; NumberAnimation { duration: 300 } }
            x: stage.wide ? panel.width + stage.gap : 0
            y: stage.wide ? 0 : narrowHead.height + 10
            width: stage.width - x
            height: stage.height - y
            lyricPos: win.lyricPos
            // ตัวอักษรตามความสูงหน้าต่าง (740px ≈ 36px, เต็มจอ 1080p ≈ 53px) × ตัวคูณของผู้ใช้
            sizeScale: Math.max(0.6, win.height / 740 * 0.95) * cfg.fw_font_scale
            forceAlign: cfg.fw_align
            anchorFrac: 0.42
            minimalMode: false
            colText: cfg.fw_text_color
            colInactive: Qt.alpha(cfg.fw_inactive_color, 0.40)   // คำที่ยังไม่ร้องในบรรทัดปัจจุบัน ~40% (วัดจากคลิป Apple Music)
            colAccent: cfg.fw_accent_color
            colSecondary: Qt.alpha(cfg.fw_secondary_color, 0.62)
            textOpacity: 1.0
            inactiveOpacity: cfg.fw_inactive_opacity
            falloff: cfg.fw_falloff
            blurAmount: cfg.fw_blur
            pastFilled: false
            showTranslation: cfg.fw_show_translation && player.showTranslation
            labelsHidden: win.chromeHidden
            edgeFade: cfg.fw_edge_fade
            edgeBlur: cfg.fw_edge_blur
        }
    }

    // ---------- ซ่อนปุ่ม/ป้าย/เมาส์เมื่อไม่ขยับ (ตั้งเวลาได้: cfg.fw_idle_hide_s) ----------
    readonly property bool chromeHidden: cfg.fw_idle_hide && idle && !settingsOpen
    HoverHandler {
        id: wake
        cursorShape: win.fs && win.chromeHidden ? Qt.BlankCursor : Qt.ArrowCursor
        onPointChanged: { win.idle = false; idleTimer.restart() }
    }
    Timer {
        id: idleTimer
        interval: Math.round(cfg.fw_idle_hide_s * 1000)
        running: cfg.fw_idle_hide && win.visible
        onTriggered: win.idle = true
    }
    onFsChanged: { idle = false; idleTimer.restart() }

    // ปุ่มกลมไอคอนล้วน (แบบ Apple: ไม่มีกรอบ/ตัวหนังสือ ชี้เมาส์แล้วมีวงจางๆ + คำอธิบาย)
    component BarBtn: Item {
        id: btn
        property string kind: "settings"
        property string tip: ""
        property bool active: false
        signal clicked()
        activeFocusOnTab: true
        width: 40
        height: 40
        Rectangle {
            anchors.fill: parent
            anchors.margins: 3
            radius: width / 2
            color: "#FFFFFF"
            opacity: tap.pressed ? 0.28 : (btn.active ? 0.2 : (bh.hovered || btn.activeFocus ? 0.12 : 0.0))
            Behavior on opacity { NumberAnimation { duration: 140 } }
        }
        Icon { anchors.centerIn: parent; kind: btn.kind; size: 20; color: "#FFFFFF"; opacity: btn.active || bh.hovered ? 1.0 : 0.72
            scale: tap.pressed ? 0.9 : 1.0
            Behavior on opacity { NumberAnimation { duration: 140 } }
            Behavior on scale { NumberAnimation { duration: 100 } } }
        HoverHandler { id: bh }
        TapHandler { id: tap; onTapped: btn.clicked() }
        Keys.onSpacePressed: btn.clicked()
        Keys.onReturnPressed: btn.clicked()
        ToolTip.visible: bh.hovered && btn.tip.length > 0
        ToolTip.text: btn.tip
        ToolTip.delay: 500
    }

    // แถบปุ่มมุมขวาบนเป็นแคปซูลโปร่งฝ้าเดียว (ไม่ใช่ปุ่มลอยเรียงกัน) · ปุ่มที่เปิดอยู่สว่างเต็ม ที่เหลือจางลง
    Rectangle {
        id: topCap
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 12
        anchors.rightMargin: win.fs ? 28 : 16
        width: topBar.width + 12
        height: 46
        radius: 23
        color: Qt.rgba(1, 1, 1, 0.10)
        z: 4
        opacity: win.chromeHidden ? 0 : 1
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 260 } }
    }
    Row {
        id: topBar
        anchors.verticalCenter: topCap.verticalCenter
        anchors.right: topCap.right
        anchors.rightMargin: 6
        spacing: 0
        z: 5
        opacity: win.chromeHidden ? 0 : 1
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 260 } }
        BarBtn { visible: player.hasTranslation; kind: "translate"; active: player.showTranslation; tip: "แสดง/ซ่อนคำแปล (T)"; onClicked: player.toggleTranslation() }
        BarBtn { kind: "swap"; tip: "เปลี่ยนเนื้อเพลงตัวอื่น"; onClicked: player.nextCandidate() }
        BarBtn { kind: "lyrics"; active: win.lyricsOn; tip: win.lyricsOn ? "ซ่อนเนื้อเพลง (ดูแต่ปก)" : "แสดงเนื้อเพลง"; onClicked: cfg.fw_lyrics_visible = !cfg.fw_lyrics_visible }
        BarBtn { kind: "settings"; tip: "ตั้งค่า"; onClicked: win.openSettings() }
        BarBtn { kind: win.fs ? "fullscreen_exit" : "fullscreen"; tip: win.fs ? "ออกจากเต็มจอ (Esc)" : "เต็มจอ (F)"; onClicked: cfg.fw_fullscreen = !cfg.fw_fullscreen }
        BarBtn { kind: "close"; tip: cfg.st_close_to_tray ? "ปิดหน้าต่างโหมดเต็ม (โปรแกรมยังทำงานที่ถาดระบบ)" : "ปิดโปรแกรม"; onClicked: win.close() }
    }

    // ---------- คีย์ลัด (เมื่อหน้าต่างนี้ถูกโฟกัส) ----------
    // ตอนอยู่หน้าตั้งค่า ปิดคีย์ลัดตัวอักษรของเครื่องเล่นทั้งหมด (พิมพ์ค้นหา/ตั้งชื่อชุดได้โดยไม่สั่งเล่น-หยุดโดยบังเอิญ) เหลือ F11 กับ Esc
    readonly property bool playerKeys: !settingsOpen
    Shortcut { sequence: "F11"; onActivated: cfg.fw_fullscreen = !cfg.fw_fullscreen }
    Shortcut { sequence: "F"; enabled: win.playerKeys; onActivated: cfg.fw_fullscreen = !cfg.fw_fullscreen }
    // Esc: อยู่หน้าตั้งค่า = ล้างคำค้น/กลับหน้าเล่นเพลง · ไม่งั้นออกจากเต็มจอ
    Shortcut { sequence: "Escape"; enabled: win.settingsOpen || win.fs
        onActivated: { if (win.settingsOpen) settingsView.handleEscape(); else cfg.fw_fullscreen = false } }
    Shortcut { sequence: "Space"; enabled: win.playerKeys; onActivated: player.togglePause() }
    Shortcut { sequence: "Left"; enabled: win.playerKeys; onActivated: player.seek(Math.max(0, win.pos - 5)) }
    Shortcut { sequence: "Right"; enabled: win.playerKeys; onActivated: player.seek(win.pos + 5) }
    Shortcut { sequence: "N"; enabled: win.playerKeys; onActivated: player.skipNext() }
    Shortcut { sequence: "P"; enabled: win.playerKeys; onActivated: player.skipPrev() }
    Shortcut { sequence: "["; enabled: win.playerKeys; onActivated: player.adjustOffset(-0.1) }
    Shortcut { sequence: "]"; enabled: win.playerKeys; onActivated: player.adjustOffset(0.1) }
    Shortcut { sequences: ["+", "="]; enabled: win.playerKeys; onActivated: cfg.fw_font_scale = Math.min(2.0, cfg.fw_font_scale + 0.1) }
    Shortcut { sequence: "-"; enabled: win.playerKeys; onActivated: cfg.fw_font_scale = Math.max(0.5, cfg.fw_font_scale - 0.1) }
    Shortcut { sequence: "T"; enabled: win.playerKeys; onActivated: player.toggleTranslation() }
    Shortcut { sequence: "L"; enabled: win.playerKeys; onActivated: cfg.fw_lyrics_visible = !cfg.fw_lyrics_visible }
    Shortcut { sequence: "Up"; enabled: win.playerKeys; onActivated: player.setVolume(Math.min(1, player.volume + 0.05)) }
    Shortcut { sequence: "Down"; enabled: win.playerKeys; onActivated: player.setVolume(Math.max(0, player.volume - 0.05)) }
    Shortcut { sequence: "M"; enabled: win.playerKeys; onActivated: player.toggleMute() }

    // ---------- หน้าตั้งค่า (ซ้อนทับเครื่องเล่น เปลี่ยนด้วยการจางเข้า-ออก) ----------
    SettingsView {
        id: settingsView
        anchors.fill: parent
        z: 50
        shown: win.settingsOpen
        onBackRequested: win.closeSettings()
        onFloatingRequested: { win.settingsOpen = false; win.settingsFromFloating = false; cfg.fw_fullscreen = false; cfg.fw_open = false }
        onPlaceRequested: (name) => win.placeRequested(name)
        onInstallRequested: win.installRequested()
        onQuitRequested: win.quitRequested()
    }
}
