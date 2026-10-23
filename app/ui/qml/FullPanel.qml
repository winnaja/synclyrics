// แผงเพลงฝั่งซ้ายของหน้าต่างโหมดเต็ม (แบบ Apple Music "Now Playing"):
//   ปกมุมโค้ง (ครอปเต็มช่อง ไม่บีบ) → ชื่อเพลง/ศิลปินชิดซ้าย → แถบเวลาบาง → ปุ่ม ก่อนหน้า/เล่น-หยุด/ถัดไป (ไอคอนเวกเตอร์ ไม่มีวงกลมขาว)
//   → แถบวอลลุ่ม (ลำโพงสองข้าง) → ปุ่มสลับเนื้อเพลง/แปล
// แอปไม่เล่นเสียงเอง: ทุกปุ่มสั่งแท็บ YouTube ผ่านส่วนขยาย (เล่น/หยุด/กรอ/ถัดไป/ก่อนหน้า/วอลลุ่ม/ปิดเสียง)
import QtQuick
import QtQuick.Controls

Item {
    id: root

    property real pos: 0
    // สี: หน้าต่างโหมดเต็มส่งสีขาวมาทับ (พื้นหลังเป็นสีจากปก ไม่ใช่ธีมของหน้าต่างลอย)
    property color colText: "#FFFFFF"
    property color colSecondary: Qt.rgba(1, 1, 1, 0.66)
    property real coverScale: 1.0
    property bool showVolume: true
    property bool lyricsOn: true
    signal lyricsToggled()

    // ความสูงส่วนที่ไม่ใช่ปก (ชื่อ+เวลา+ปุ่ม+วอลลุ่ม+ปุ่มสลับ+ช่องไฟ) ที่ต้องเผื่อไว้
    readonly property real below: 74 + 44 + 88 + (showVolume ? 44 : 0) + 40
    readonly property real coverSide: Math.max(140, Math.min(root.width, (root.height - below)) * Math.min(1.0, coverScale)
                                               + Math.max(0, coverScale - 1.0) * 0)
    readonly property real fraction: player.durationS > 0 ? Math.max(0, Math.min(1, pos / player.durationS)) : 0
    property real scrub: -1
    readonly property real shownFraction: scrub >= 0 ? scrub : fraction

    function fmt(s) {
        var t = Math.max(0, Math.floor(s))
        var r = t % 60
        return Math.floor(t / 60) + ":" + (r < 10 ? "0" : "") + r
    }

    // ปุ่มไอคอนล้วน: ชี้เมาส์/โฟกัสแล้วมีวงกลมจางๆ · กดแล้วย่อเล็กน้อย
    component IconBtn: Item {
        id: ib
        property string kind: "play"
        property real iconSize: 28
        property real hit: 52
        property bool active: false
        property string tip: ""
        signal clicked()
        activeFocusOnTab: true
        width: hit
        height: hit
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: root.colText
            opacity: tap.pressed ? 0.24 : (hov.hovered || ib.activeFocus ? 0.14 : (ib.active ? 0.2 : 0))
            Behavior on opacity { NumberAnimation { duration: 120 } }
        }
        Icon {
            id: ico
            anchors.centerIn: parent
            kind: ib.kind
            size: ib.iconSize
            color: root.colText
            scale: tap.pressed ? 0.9 : 1.0
            Behavior on scale { enabled: !pop.running; NumberAnimation { duration: 90 } }
            // เปลี่ยนไอคอน (เล่น <-> หยุด) แล้วเด้งเข้าเบาๆ ให้รู้ว่าสถานะเปลี่ยนจริง
            NumberAnimation { id: pop; target: ico; property: "scale"; from: 0.78; to: 1.0; duration: 240; easing.type: Easing.OutBack; easing.overshoot: 1.6 }
        }
        onKindChanged: if (!cfg.ov_reduced_motion) pop.restart()
        HoverHandler { id: hov }
        TapHandler { id: tap; onTapped: ib.clicked() }
        Keys.onSpacePressed: ib.clicked()
        Keys.onReturnPressed: ib.clicked()
        ToolTip.visible: hov.hovered && ib.tip.length > 0
        ToolTip.text: ib.tip
        ToolTip.delay: 600
    }

    // แถบแนวนอนบาง (ใช้กับเวลาและวอลลุ่ม): ชี้เมาส์แล้วหนาขึ้นและมีปุ่มกลม
    component Track: Item {
        id: tr
        property real value: 0            // 0-1
        property bool enabledDrag: true
        signal moved(real v)              // ระหว่างลาก
        signal released(real v)
        implicitHeight: 20
        readonly property bool hot: area.containsMouse || area.pressed
        Rectangle {
            id: rail
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: tr.hot ? 7 : 5
            radius: height / 2
            color: Qt.alpha(root.colText, 0.25)
            Behavior on height { NumberAnimation { duration: 120 } }
            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, tr.value))
                height: parent.height
                radius: parent.radius
                color: root.colText
            }
            Rectangle {                      // ปุ่มกลมโผล่ตอนชี้/ลาก
                width: 14; height: 14; radius: 7
                color: root.colText
                x: rail.width * Math.max(0, Math.min(1, tr.value)) - width / 2
                y: (rail.height - height) / 2
                opacity: tr.hot ? 1 : 0
                scale: tr.hot ? 1 : 0.4
                Behavior on opacity { NumberAnimation { duration: 120 } }
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutBack } }
            }
        }
        MouseArea {
            id: area
            anchors.fill: parent
            enabled: tr.enabledDrag
            hoverEnabled: true
            function frac(mx) { return Math.max(0, Math.min(1, mx / width)) }
            onPressed: (m) => tr.moved(frac(m.x))
            onPositionChanged: (m) => { if (pressed) tr.moved(frac(m.x)) }
            onReleased: (m) => tr.released(frac(m.x))
        }
    }

    Item {
        id: stack
        width: root.coverSide
        height: root.coverSide + root.below
        x: (root.width - width) / 2
        y: Math.max(0, (root.height - height) / 2)

        // ---------- ปก ----------
        Item {
            id: cover
            width: root.coverSide
            height: root.coverSide
            readonly property real corner: Math.max(8, root.coverSide * 0.03)

            // เงานุ่ม: สี่เหลี่ยมโปร่งใสซ้อนหลายชั้น (เบา ไม่ใช้ shader)
            Repeater {
                model: 6
                Rectangle {
                    required property int index
                    anchors.fill: parent
                    anchors.margins: -index * 7
                    anchors.topMargin: -index * 5 + 14
                    radius: cover.corner + index * 6
                    color: "#000000"
                    opacity: 0.045
                }
            }
            Rectangle {
                anchors.fill: parent
                radius: cover.corner
                color: Qt.alpha(root.colText, 0.12)
                Icon {
                    anchors.centerIn: parent
                    kind: "cover"
                    size: parent.width * 0.3
                    color: root.colSecondary
                    visible: img.status !== Image.Ready
                }
            }
            // ต้นฉบับของปก: ซ่อนไว้ให้ ShaderEffect ครอปเต็มช่อง+ตัดมุมโค้ง (ครอปทำใน shader — ดู rounded_image.frag)
            Image {
                id: img
                anchors.fill: parent
                source: player.coverUrl
                fillMode: Image.Stretch
                asynchronous: true
                smooth: true
                visible: false
            }
            ShaderEffect {
                anchors.fill: parent
                visible: img.status === Image.Ready
                property variant source: img
                property real radius: cover.corner
                property vector2d size: Qt.vector2d(width, height)
                property vector2d imgSize: Qt.vector2d(img.implicitWidth, img.implicitHeight)
                fragmentShader: "../shaders/rounded_image.frag.qsb"
            }
            // ครอสเฟดปกเก่า -> ปกใหม่ตอนเปลี่ยนเพลง: เก็บปกเก่าไว้ด้านบนแล้วจางหาย เมื่อปกใหม่โหลดเสร็จ
            property string lastUrl: ""
            property bool fadePending: false
            Image { id: oldImg; anchors.fill: parent; fillMode: Image.Stretch; asynchronous: false; visible: false }
            ShaderEffect {
                id: oldFx
                anchors.fill: parent
                opacity: 0
                visible: opacity > 0.01
                property variant source: oldImg
                property real radius: cover.corner
                property vector2d size: Qt.vector2d(width, height)
                property vector2d imgSize: Qt.vector2d(oldImg.implicitWidth, oldImg.implicitHeight)
                fragmentShader: "../shaders/rounded_image.frag.qsb"
            }
            NumberAnimation { id: oldFade; target: oldFx; property: "opacity"; from: 1; to: 0; duration: 520; easing.type: Easing.InOutQuad }
            function startFade() {
                if (!fadePending || img.status !== Image.Ready) return
                fadePending = false
                failsafe.stop()
                if (cfg.ov_reduced_motion) { oldFx.opacity = 0; return }
                oldFade.restart()
            }
            // กันปกเก่าค้างบนจอ: ถ้าปกใหม่ไม่พร้อม/ไม่มีปก ภายใน 1.5 วิ ให้ล้างปกเก่าทิ้งเสมอ
            Timer { id: failsafe; interval: 1500; onTriggered: { cover.fadePending = false; oldFade.stop(); oldFx.opacity = 0 } }
            Connections {
                target: player
                function onCoverUrlChanged() {
                    var nu = player.coverUrl.toString()
                    oldFade.stop()
                    oldFx.opacity = 0
                    if (cover.lastUrl.length > 0 && nu.length > 0 && nu !== cover.lastUrl) {
                        oldImg.source = cover.lastUrl
                        oldFx.opacity = 1
                        cover.fadePending = true
                        failsafe.restart()
                        cover.startFade()
                    }
                    cover.lastUrl = nu
                }
            }
            Connections { target: img; function onStatusChanged() { cover.startFade() } }
            Component.onCompleted: lastUrl = player.coverUrl.toString()
            // ย่อลงเล็กน้อยตอนหยุดเพลง (Apple Music)
            scale: player.playing || cfg.ov_reduced_motion ? 1.0 : 0.94
            Behavior on scale { NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
        }

        // ---------- ชื่อ / ศิลปิน ----------
        Column {
            id: info
            y: cover.height + 26
            width: parent.width
            spacing: 3
            NumberAnimation { id: infoIn; target: info; property: "opacity"; from: 0; to: 1; duration: 360; easing.type: Easing.OutCubic }
            Connections { target: player; function onTitleChanged() { if (!cfg.ov_reduced_motion) infoIn.restart() } }
            Text {
                width: parent.width
                text: player.title.length > 0 ? player.title : "ยังไม่มีเพลง"
                color: root.colText
                font.pixelSize: Math.max(18, Math.min(26, root.coverSide * 0.058))
                font.weight: Font.Bold
                font.family: cfg.look_font_family
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: player.artist
                color: root.colSecondary
                font.pixelSize: Math.max(14, Math.min(20, root.coverSide * 0.043))
                font.family: cfg.look_font_family
                elide: Text.ElideRight
            }
        }

        // ---------- แถบเวลา ----------
        Item {
            id: timeBar
            y: info.y + 74
            width: parent.width
            height: 44
            Track {
                id: prog
                width: parent.width
                value: root.shownFraction
                enabledDrag: player.durationS > 0
                onMoved: (v) => root.scrub = v
                onReleased: (v) => { player.seek(v * player.durationS); root.scrub = -1 }
            }
            Text {
                y: 22
                text: root.fmt(root.scrub >= 0 ? root.scrub * player.durationS : root.pos)
                color: root.colSecondary
                font.pixelSize: 12
                font.weight: Font.Medium
                font.family: cfg.look_font_family
            }
            Text {
                y: 22
                anchors.right: parent.right
                text: player.durationS > 0 ? "-" + root.fmt(Math.max(0, player.durationS - (root.scrub >= 0 ? root.scrub * player.durationS : root.pos))) : "-:--"
                color: root.colSecondary
                font.pixelSize: 12
                font.family: cfg.look_font_family
            }
        }

        // ---------- ปุ่มควบคุม (สั่งแท็บ YouTube) ----------
        Row {
            id: transport
            y: timeBar.y + timeBar.height + 10
            x: (parent.width - width) / 2
            spacing: 36
            anchors.verticalCenter: undefined
            IconBtn { kind: "prev"; iconSize: 40; hit: 64; anchors.verticalCenter: parent.verticalCenter; tip: "เพลงก่อนหน้า (P)"; onClicked: player.skipPrev() }
            IconBtn { kind: player.playing ? "pause" : "play"; iconSize: 56; hit: 76; tip: player.playing ? "หยุด (Space)" : "เล่น (Space)"; onClicked: player.togglePause() }
            IconBtn { kind: "next"; iconSize: 40; hit: 64; anchors.verticalCenter: parent.verticalCenter; tip: "เพลงถัดไป (N)"; onClicked: player.skipNext() }
        }

        // ---------- วอลลุ่ม (ลำโพงสองข้าง แบบ Apple Music) ----------
        Item {
            id: volRow
            visible: root.showVolume
            y: transport.y + 72 + 14
            width: parent.width
            height: root.showVolume ? 30 : 0
            IconBtn {
                id: spkLow
                x: -8
                anchors.verticalCenter: parent.verticalCenter
                kind: player.muted || player.volume <= 0.001 ? "mute" : "volume_low"
                iconSize: 20
                hit: 34
                tip: player.muted ? "เปิดเสียง" : "ปิดเสียง"
                onClicked: player.toggleMute()
            }
            Track {
                x: 34
                width: parent.width - 34 - 34
                anchors.verticalCenter: parent.verticalCenter
                value: player.muted ? 0 : player.volume
                onMoved: (v) => player.setVolume(v)
                onReleased: (v) => player.setVolume(v)
            }
            IconBtn {
                x: parent.width - 26
                anchors.verticalCenter: parent.verticalCenter
                kind: "volume_high"
                iconSize: 20
                hit: 34
                tip: "เสียงดังสุด"
                onClicked: player.setVolume(1.0)
            }
        }
    }
}
