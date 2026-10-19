// หน้าต่างหลัก (เฟส 1: เรียบๆ อ่านง่าย — เอฟเฟกต์ shader อยู่เฟส 3)
// ไฟล์ในโฟลเดอร์นี้:
//   Main.qml        หน้าต่าง + พื้นหลังไล่สี + นาฬิกาต่อเฟรม + คีย์ลัด
//   NowPlaying.qml  ปก ชื่อ ศิลปิน progress bar ปุ่มเล่น ช่องวางลิงก์
//   LyricsView.qml  ListView ของบรรทัด + เลื่อนแบบสปริง + ติดตามเพลงอัตโนมัติ
//   LyricLine.qml   หนึ่งบรรทัด: คำ + เติมสีซ้ายไปขวาตามเวลา
// object จาก Python (context property): player, lyricsModel, clockBridge, look, safeMode
// ที่วางไว้สำหรับเฟสถัดไป: Background.qml, Transitions.qml, RatingPopup.qml, SettingsPage.qml,
//   DebugPage.qml, DesktopLyrics.qml
import QtQuick
import QtQuick.Window
import QtQuick.Layouts

Window {
    id: root

    // เวลาของเสียง (วินาที) อัปเดตทุกเฟรมจาก FrameAnimation เดียวเท่านั้น
    property real pos: 0
    // เวลาที่ใช้หาบรรทัด = เวลาเสียง - offset ที่ผู้ใช้ปรับ
    readonly property real lyricPos: pos - player.lyricsOffset

    width: 1100
    height: 720
    minimumWidth: 760
    minimumHeight: 520
    visible: true
    color: "#0e1016"
    title: "SyncLyrics"

    // บันทึกภาพหน้าต่างเป็นไฟล์ (ใช้ตอนไล่บั๊กหน้าตา/test)
    function saveShot(path) {
        root.contentItem.grabToImage(function(r) { r.saveToFile(path) })
    }

    // อ่านนาฬิกาครั้งเดียวต่อเฟรม (ไม่ใช้ Timer)
    FrameAnimation {
        running: root.visible
        onTriggered: root.pos = clockBridge.position()
    }

    // พื้นหลังไล่สีมืด
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#1a1d3a" }
            GradientStop { position: 0.55; color: "#15162b" }
            GradientStop { position: 1.0; color: "#2a1a3c" }
        }
    }

    Item {
        id: content
        anchors.fill: parent
        focus: true

        // คลิกที่ว่างเพื่อเอาโฟกัสออกจากช่องวางลิงก์ (ให้คีย์ลัดทำงาน)
        TapHandler {
            onTapped: content.forceActiveFocus()
        }

        RowLayout {
            anchors.fill: parent
            anchors.margins: 28
            spacing: 28

            NowPlaying {
                id: nowPlaying
                Layout.preferredWidth: Math.max(300, Math.min(380, root.width * 0.34))
                Layout.fillHeight: true
                pos: root.pos
            }

            LyricsView {
                id: lyricsView
                Layout.fillWidth: true
                Layout.fillHeight: true
                lyricPos: root.lyricPos
            }
        }
    }

    // ---------- คีย์ลัด (ทำงานเมื่อช่องวางลิงก์ไม่ได้โฟกัส) ----------
    Shortcut {
        sequence: "Space"
        enabled: !nowPlaying.urlFocused
        onActivated: player.togglePause()
    }
    Shortcut {
        sequence: "Left"
        enabled: !nowPlaying.urlFocused
        onActivated: player.seek(Math.max(0, clockBridge.position() - 5))
    }
    Shortcut {
        sequence: "Right"
        enabled: !nowPlaying.urlFocused
        onActivated: {
            var t = clockBridge.position() + 5
            player.seek(player.durationS > 0 ? Math.min(player.durationS, t) : t)
        }
    }
    Shortcut {
        sequence: "["
        enabled: !nowPlaying.urlFocused
        onActivated: player.adjustOffset(-0.1)
    }
    Shortcut {
        sequence: "]"
        enabled: !nowPlaying.urlFocused
        onActivated: player.adjustOffset(0.1)
    }
    Shortcut {
        sequences: [StandardKey.Paste]
        enabled: !nowPlaying.urlFocused
        onActivated: player.pasteAndPlay()
    }
}
