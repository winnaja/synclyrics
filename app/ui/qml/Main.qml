// หน้าต่างหลัก — โครงเปล่า (เฟส 0) เติมจริงในเฟส 1 และ 3
// โครงที่วางไว้:
//   Main.qml            หน้าต่าง + สลับโหมด (Immersive / ปกติ / มินิ)
//   NowPlaying.qml      ปก ชื่อ ศิลปิน progress bar (มีแถบ coverage ของ AI) ปุ่มควบคุม
//   LyricsView.qml      ListView ของบรรทัด + spring scroll + เบลอตามระยะ
//   LyricLine.qml       หนึ่งบรรทัด: คำ + shader mask ไฮไลต์ทีละคำ
//   Background.qml      Fluid / Blur Cover / Video / Solid / Gradient / Image (ShaderEffect)
//   Transitions.qml     ทรานซิชั่นระหว่างเพลง (ส่วนที่ 8)
//   RatingPopup.qml     ป๊อปอัปให้ดาว (ข้อ 7.7)
//   SettingsPage.qml    หน้าตั้งค่า + ตัวอย่างสด (ส่วนที่ 9)
//   DebugPage.qml       Ctrl+Shift+D (ข้อ 11.3)
//   DesktopLyrics.qml   เนื้อเพลงลอยบนเดสก์ท็อป (หน้าต่างแยก)
import QtQuick
import QtQuick.Window

Window {
    width: 1280
    height: 800
    visible: true
    color: "#111318"
    title: "SyncLyrics"
}
