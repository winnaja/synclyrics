// สคริปต์ที่รันใน "โลกของหน้าเว็บ" (world: MAIN) — มีไว้ปรับเสียงเท่านั้น
// เหตุผล: content.js รันในโลกแยก เรียก API ของตัวเล่น YouTube (#movie_player.setVolume ฯลฯ) ไม่ได้
// และการตั้ง <video>.volume ตรงๆ ไม่ทำให้แถบเสียงของ YouTube ขยับ + ตัวเล่นมักตั้งค่ากลับเอง (ปรับเสียงจากโปรแกรมแล้วไม่ติด)
// ทำงานคู่กับ content.js ผ่าน window.postMessage (ไม่มีข้อมูลส่วนตัวผ่านช่องนี้ มีแค่ค่าเสียง 0-1 กับสถานะปิดเสียง)
(() => {
  "use strict";
  const TAG = "synclyrics";
  if (window.__synclyricsPage) return;
  window.__synclyricsPage = true;

  function player() {
    const p = document.getElementById("movie_player");
    return p && typeof p.setVolume === "function" ? p : null;
  }
  function video() {
    return document.querySelector("video");
  }

  function setVolume(value) {
    const v = Math.max(0, Math.min(1, value));
    const p = player();
    if (p) {
      p.setVolume(Math.round(v * 100));
      if (v > 0 && p.isMuted && p.isMuted()) p.unMute();       // ลากวอลลุ่มขึ้น = เลิกปิดเสียง
      return;
    }
    const el = video();                                          // ไม่มีตัวเล่น (เช่น embed) -> ตั้งที่ <video> ตรงๆ
    if (el) { el.volume = v; if (v > 0 && el.muted) el.muted = false; }
  }

  function setMuted(on) {
    const p = player();
    if (p) { if (on) p.mute(); else p.unMute(); return; }
    const el = video();
    if (el) el.muted = !!on;
  }

  function post() {
    let volume, muted;
    const p = player();
    if (p && typeof p.getVolume === "function") {
      volume = p.getVolume() / 100;
      muted = !!(p.isMuted && p.isMuted());
    } else {
      const el = video();
      if (!el) return;
      volume = el.volume; muted = el.muted;
    }
    window.postMessage({ source: TAG, type: "volume_state", volume, muted }, "*");
  }

  window.addEventListener("message", (e) => {
    if (e.source !== window || !e.data || e.data.target !== TAG) return;
    const m = e.data;
    try {
      if (m.type === "volume" && typeof m.value === "number" && isFinite(m.value)) setVolume(m.value);
      else if (m.type === "mute") setMuted(!!m.value);
      else if (m.type === "get_volume") { /* ตอบด้านล่าง */ }
      post();
    } catch (err) { /* ห้ามพังหน้าเว็บ */ }
  });

  // แจ้งค่าเสียงเมื่อผู้ใช้ปรับเองในหน้า YouTube (ผ่านเหตุการณ์ของตัวเล่น) + เช็กเป็นระยะกันตกหล่น
  let last = "";
  setInterval(() => {
    try {
      const p = player();
      if (!p || typeof p.getVolume !== "function") return;
      const key = p.getVolume() + ":" + (p.isMuted && p.isMuted());
      if (key !== last) { last = key; post(); }
    } catch (err) { /* ignore */ }
  }, 700);
})();
