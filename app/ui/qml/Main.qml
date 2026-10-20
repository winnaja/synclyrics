// รากของ UI (add by win/UX UI.txt): โปรแกรมเป็น Desktop Lyrics Utility — ไม่มีหน้าต่างหลักแบบโปรแกรมทั่วไป
//   Overlay.qml         หน้าต่างเนื้อเพลงลอย (minimal / focus)
//   FullWindow.qml      หน้าต่างโหมดเต็มแบบ Apple Music (หน้าต่างปกติ + เต็มจอ, พื้นหลัง fluid สีจากปก)
//   SettingsWindow.qml  หน้าตั้งค่า 5 หมวด (เห็นผลทันที)
//   Tray.qml            ไอคอนถาดระบบ
//   LyricsView.qml / LyricLine.qml / FullPanel.qml  ส่วนประกอบของหน้าต่างเนื้อเพลง
// object จาก Python (context property): cfg (QQmlPropertyMap ของการตั้งค่า), player, lyricsModel, clockBridge,
//   settingsBridge, safeMode
import QtQuick
import QtQuick.Window

QtObject {
    id: root

    property var overlay: Overlay {
        onOpenSettingsRequested: root.showSettings()
    }
    property var fullWin: FullWindow {
        onSettingsRequested: root.showSettings()
    }
    property var settingsWin: SettingsWindow {
        onHiddenToTray: root.hintTray()
        onPlaceRequested: (name) => root.overlay.placePreset(name)
        onInstallRequested: player.installExtension()
        onQuitRequested: settingsBridge.quit()
    }
    property var tray: Tray {
        onFullRequested: root.showFull()
        onSettingsRequested: root.showSettings()
        onInstallRequested: player.installExtension()
    }

    // เปิดโปรแกรมมาให้โหมดเต็มเป็นหน้าแรก (ปิดได้ที่ ตั้งค่า > โหมดเต็ม)
    Component.onCompleted: if (cfg.fw_start_full) cfg.fw_open = true

    // เรียกจาก Python (เปิดโปรแกรมซ้ำ / ส่วนขยายสั่ง focus / คีย์ลัด)
    function showOverlay() {
        cfg.ov_visible = true
        overlay.show()
        overlay.raise()
    }
    // ซ่อนลงถาดครั้งแรกของรอบนี้: บอกผู้ใช้ว่าโปรแกรมยังทำงานอยู่ (ไม่ให้เข้าใจผิดว่าปิดแล้ว — UX UI ข้อ 11)
    property bool trayHinted: false
    function hintTray() {
        if (trayHinted) return
        trayHinted = true
        tray.showMessage("SyncLyrics ยังทำงานอยู่", "อยู่ที่ไอคอนถาดระบบ — คลิกไอคอนเพื่อแสดง/ซ่อนเนื้อเพลง คลิกขวาเพื่อตั้งค่าหรือออกจากโปรแกรม", 1, 5000)
    }
    function showFull() {
        cfg.fw_open = true
        fullWin.raise()
        fullWin.requestActivate()
    }
    function showSettings() {
        settingsWin.visible = true
        settingsWin.raise()
        settingsWin.requestActivate()
    }
    function toast(text) { overlay.showToast(text) }

    // บันทึกภาพหน้าต่างเป็นไฟล์ (ไล่บั๊กหน้าตา/test)
    function saveShot(path, which) {
        var w = which === "settings" ? settingsWin : (which === "full" ? fullWin : overlay)
        w.contentItem.grabToImage(function(r) { r.saveToFile(path) })
    }
}
