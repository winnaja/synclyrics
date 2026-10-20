// ไอคอนถาดระบบ (UX UI หมวด 11): แสดง/ซ่อนเนื้อเพลง · ตั้งค่า · คลิกทะลุ · ล็อก · เชื่อมต่อ YouTube · ออก
// ปุ่มปิดของหน้าต่างไม่ปิดโปรแกรม (ซ่อนไว้) จึงต้องมีทางออกที่นี่เสมอ
import QtQuick
import Qt.labs.platform as Labs

Labs.SystemTrayIcon {
    id: tray
    signal settingsRequested()
    signal fullRequested()
    signal installRequested()

    visible: true
    icon.source: Qt.resolvedUrl("../assets/tray.png")
    tooltip: player.title.length > 0 ? "SyncLyrics — " + player.title : "SyncLyrics"
    onActivated: (reason) => {
        if (reason === Labs.SystemTrayIcon.Trigger)
            cfg.ov_visible = !cfg.ov_visible
    }

    menu: Labs.Menu {
        Labs.MenuItem {
            text: cfg.ov_visible ? "ซ่อนเนื้อเพลง" : "แสดงเนื้อเพลง"
            onTriggered: cfg.ov_visible = !cfg.ov_visible
        }
        Labs.MenuItem {
            text: cfg.fw_open ? "ปิดโหมดเต็ม" : "เปิดโหมดเต็ม (หน้าต่างเต็ม/เต็มจอ)"
            onTriggered: cfg.fw_open ? cfg.fw_open = false : tray.fullRequested()
        }
        Labs.MenuItem { text: "ตั้งค่า..."; onTriggered: tray.settingsRequested() }
        Labs.MenuSeparator { }
        Labs.MenuItem {
            text: "คลิกทะลุหน้าต่าง"
            checkable: true
            checked: cfg.ov_click_through
            onTriggered: cfg.ov_click_through = !cfg.ov_click_through
        }
        Labs.MenuItem {
            text: "ล็อกตำแหน่ง"
            checkable: true
            checked: cfg.ov_locked
            onTriggered: cfg.ov_locked = !cfg.ov_locked
        }
        Labs.MenuSeparator { }
        Labs.MenuItem {
            text: player.bridgeConnected ? "YouTube: เชื่อมต่อแล้ว" : "YouTube: ยังไม่เชื่อม — ติดตั้ง/เชื่อมต่อส่วนขยาย"
            onTriggered: tray.installRequested()
        }
        Labs.MenuSeparator { }
        Labs.MenuItem { text: "ออกจากโปรแกรม"; onTriggered: settingsBridge.quit() }
    }
}
