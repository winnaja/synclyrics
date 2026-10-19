// แผงข้อมูลเพลง: ปก ชื่อ ศิลปิน progress bar ปุ่มเล่น/หยุด ช่องวางลิงก์ สถานะ
// อ่านค่าจาก player (context property) — pos ส่งเข้ามาจาก Main (อัปเดตต่อเฟรม)
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Layouts

Item {
    id: root

    property real pos: 0
    readonly property bool urlFocused: urlField.activeFocus

    // เวลาที่กำลังลาก (>= 0) ถ้าไม่ได้ลากเป็น -1
    property real scrub: -1
    readonly property real shownPos: scrub >= 0 ? scrub : pos
    readonly property real fraction: player.durationS > 0
        ? Math.max(0, Math.min(1, shownPos / player.durationS)) : 0

    function fmt(s) {
        var t = Math.max(0, Math.floor(s))
        var m = Math.floor(t / 60)
        var r = t % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    function submitUrl() {
        if (urlField.text.trim().length > 0) {
            player.playUrl(urlField.text)
            urlField.text = ""
            urlField.focus = false
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        // ---------- ปก ----------
        Item {
            id: coverBox
            Layout.fillWidth: true
            Layout.preferredHeight: width
            Layout.maximumHeight: root.height * 0.5

            // ย่อลงเล็กน้อยตอนหยุดเพลง
            scale: player.playing ? 1.0 : 0.93
            Behavior on scale {
                NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
            }

            readonly property real side: Math.min(width, height)

            // ปก (มุมโค้ง + เงานุ่มด้วย layer.effect — ข้ามใน safe mode)
            // หมายเหตุ: ห้ามซ่อน (visible:false) ต้นฉบับของปกแล้วใช้ MultiEffect แยก — Image ข้างในจะไม่ถูกโหลด/วาด
            Item {
                id: coverSource
                width: coverBox.side
                height: coverBox.side
                anchors.centerIn: parent
                layer.enabled: !safeMode
                layer.effect: MultiEffect {
                    maskEnabled: true
                    maskSource: coverMask
                    shadowEnabled: true
                    shadowColor: "#000000"
                    shadowOpacity: 0.55
                    shadowBlur: 1.0
                    shadowVerticalOffset: 10
                    shadowScale: 0.96
                }

                Rectangle {
                    anchors.fill: parent
                    color: "#262a40"
                    radius: safeMode ? 20 : 0
                }
                Text {
                    anchors.centerIn: parent
                    text: "♪"
                    color: "#7a82a8"
                    font.pixelSize: parent.width * 0.35
                    visible: cover.status !== Image.Ready
                }
                Image {
                    id: cover
                    objectName: "coverImg"
                    anchors.fill: parent
                    source: player.coverUrl
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    sourceSize.width: 800
                    sourceSize.height: 800
                    smooth: true
                    visible: status === Image.Ready
                }
            }

            // มาสก์มุมโค้ง
            Item {
                id: coverMask
                width: coverBox.side
                height: coverBox.side
                anchors.centerIn: parent
                layer.enabled: true
                visible: false
                Rectangle {
                    width: parent.width
                    height: parent.height
                    radius: 20
                    color: "black"
                }
            }
        }

        // ---------- ชื่อเพลง / ศิลปิน ----------
        Text {
            Layout.fillWidth: true
            text: player.title.length > 0 ? player.title : "วางลิงก์ YouTube เพื่อเริ่มเล่น"
            color: "#ffffff"
            font.pixelSize: 22
            font.weight: Font.Bold
            font.family: look.font_family
            elide: Text.ElideRight
            maximumLineCount: 2
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: text.length > 0
            text: player.artist
            color: "#b9bdd6"
            font.pixelSize: 15
            font.family: look.font_family
            elide: Text.ElideRight
        }

        // ---------- progress bar (กดหรือลากเพื่อ seek) ----------
        Item {
            id: bar
            Layout.fillWidth: true
            Layout.preferredHeight: 22

            Rectangle {
                id: track
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 6
                radius: 3
                color: "#33ffffff"

                Rectangle {
                    width: parent.width * root.fraction
                    height: parent.height
                    radius: 3
                    color: "#ffffff"
                }
            }
            Rectangle {
                width: 12
                height: 12
                radius: 6
                color: "#ffffff"
                x: track.width * root.fraction - width / 2
                anchors.verticalCenter: parent.verticalCenter
                visible: player.durationS > 0
            }
            MouseArea {
                anchors.fill: parent
                enabled: player.durationS > 0
                function timeAt(x) {
                    return Math.max(0, Math.min(1, x / width)) * player.durationS
                }
                onPressed: (m) => root.scrub = timeAt(m.x)
                onPositionChanged: (m) => { if (pressed) root.scrub = timeAt(m.x) }
                onReleased: (m) => {
                    player.seek(timeAt(m.x))
                    root.scrub = -1
                }
                onCanceled: root.scrub = -1
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: root.fmt(root.shownPos)
                color: "#9fa4c2"
                font.pixelSize: 12
            }
            Item { Layout.fillWidth: true }
            Text {
                text: player.durationS > 0 ? root.fmt(player.durationS) : "-:--"
                color: "#9fa4c2"
                font.pixelSize: 12
            }
        }

        // ---------- ปุ่มควบคุม ----------
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 18

            Rectangle {
                id: playBtn
                width: 56
                height: 56
                radius: 28
                color: playTap.pressed ? "#d8d8e6" : "#ffffff"
                Text {
                    anchors.centerIn: parent
                    text: player.playing ? "❚❚" : "▶"
                    color: "#15162b"
                    font.pixelSize: 20
                }
                TapHandler {
                    id: playTap
                    onTapped: player.togglePause()
                }
            }
            Rectangle {
                width: 44
                height: 44
                radius: 22
                color: nextTap.pressed ? "#44ffffff" : "#22ffffff"
                ToolTip.visible: nextHover.hovered
                ToolTip.text: "เปลี่ยนเนื้อเพลงตัวอื่น"
                Text {
                    anchors.centerIn: parent
                    text: "↻"
                    color: "#ffffff"
                    font.pixelSize: 20
                }
                HoverHandler { id: nextHover }
                TapHandler {
                    id: nextTap
                    onTapped: player.nextCandidate()
                }
            }
        }

        // ---------- ระดับเสียง ----------
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Text {
                text: volume.value <= 0.001 ? "🔇" : (volume.value < 0.5 ? "🔉" : "🔊")
                color: "#b9bdd6"
                font.pixelSize: 16
            }
            Slider {
                id: volume
                Layout.fillWidth: true
                from: 0
                to: 1
                value: 1
                stepSize: 0.01
                onMoved: player.setVolume(value)
                background: Rectangle {
                    x: volume.leftPadding
                    y: volume.topPadding + volume.availableHeight / 2 - height / 2
                    width: volume.availableWidth
                    height: 4
                    radius: 2
                    color: "#33ffffff"
                    Rectangle {
                        width: volume.visualPosition * parent.width
                        height: parent.height
                        radius: 2
                        color: "#ffffff"
                    }
                }
                handle: Rectangle {
                    x: volume.leftPadding + volume.visualPosition * (volume.availableWidth - width)
                    y: volume.topPadding + volume.availableHeight / 2 - height / 2
                    width: 12
                    height: 12
                    radius: 6
                    color: "#ffffff"
                }
            }
        }

        // ---------- ช่องวางลิงก์ ----------
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            TextField {
                id: urlField
                Layout.fillWidth: true
                placeholderText: "วางลิงก์ YouTube แล้วกด Enter"
                placeholderTextColor: "#7c82a3"
                color: "#ffffff"
                selectByMouse: true
                font.pixelSize: 14
                leftPadding: 12
                rightPadding: 12
                background: Rectangle {
                    radius: 10
                    color: urlField.activeFocus ? "#2effffff" : "#1affffff"
                    border.width: urlField.activeFocus ? 1 : 0
                    border.color: "#88ffffff"
                }
                onAccepted: root.submitUrl()
            }
            Rectangle {
                Layout.preferredWidth: 64
                Layout.preferredHeight: urlField.height
                radius: 10
                color: goTap.pressed ? "#55ffffff" : "#33ffffff"
                Text {
                    anchors.centerIn: parent
                    text: "เล่น"
                    color: "#ffffff"
                    font.pixelSize: 14
                    font.family: look.font_family
                }
                TapHandler {
                    id: goTap
                    onTapped: root.submitUrl()
                }
            }
        }

        // ---------- สถานะ / ป้าย AI ----------
        Text {
            Layout.fillWidth: true
            visible: text.length > 0
            text: player.statusText
            color: "#ffd479"
            font.pixelSize: 13
            font.family: look.font_family
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: player.aiTranscribed
            text: "ถอดเสียงโดย AI อาจมีคำผิด"
            color: "#9fe3ff"
            font.pixelSize: 12
            font.family: look.font_family
        }

        Item { Layout.fillHeight: true }
    }
}
