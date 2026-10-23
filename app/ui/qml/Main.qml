// รากของ UI (add by win/UX UI.txt): โปรแกรมเป็น Desktop Lyrics Utility — ไม่มีหน้าต่างหลักแบบโปรแกรมทั่วไป
//   Overlay.qml         หน้าต่างเนื้อเพลงลอย (minimal / focus)
//   FullWindow.qml      หน้าต่างโหมดเต็มแบบ Apple Music (หน้าต่างปกติ + เต็มจอ, พื้นหลัง fluid สีจากปก)
//   SettingsView.qml    หน้าตั้งค่า (ฝังในหน้าต่างหลัก FullWindow ซ้อนทับเครื่องเล่น · เห็นผลทันที)
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
        onHiddenToTray: root.hintTray()
        onPlaceRequested: (name) => root.overlay.placePreset(name)
        onInstallRequested: player.installExtension()
        onQuitRequested: settingsBridge.quit()
    }
    // หน้าตั้งค่าเป็นส่วนหนึ่งของหน้าต่างหลัก (FullWindow) ไม่ใช่หน้าต่างแยก
    property var settingsWin: fullWin.settingsView
    property var tray: Tray {
        onFullRequested: root.showFull()
        onSettingsRequested: root.showSettings()
        onInstallRequested: player.installExtension()
    }

    // เปิดโปรแกรมมาให้หน้าต่างหลักเป็นหน้าแรก (ปิดได้ที่ ตั้งค่า > หน้าต่างและการแสดงผล)
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
        fullWin.openSettings()
    }
    function toast(text) { overlay.showToast(text) }

    // บันทึกภาพหน้าต่างเป็นไฟล์ (ไล่บั๊กหน้าตา/test)
    function saveShot(path, which) {
        var w = which === "settings" ? fullWin : (which === "full" ? fullWin : overlay)
        w.contentItem.grabToImage(function(r) { r.saveToFile(path) })
    }
}
