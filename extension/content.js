// SyncLyrics — content script บน YouTube / YouTube Music
// หน้าที่เดียว: รายงาน "เพลงไหน (videoId) เล่นอยู่ที่วินาทีเท่าไร" ให้โปรแกรมแสดงเนื้อเพลงแบบเรียลไทม์
//   - ไม่หยุด/ไม่แตะวิดีโอ (YouTube เล่นเสียงเอง) ไม่ใส่ปุ่ม ไม่แก้หน้าเว็บ ไม่มี MutationObserver
//   - ไม่ส่งชื่อเพลงจากหน้าเว็บ: ตอนเปลี่ยนเพลง YouTube อัปเดต URL ก่อนชื่อบนหน้า (เคยทำให้เนื้อเพลง/ปกเป็นของเพลงก่อนหน้า)
//     โปรแกรมดึงชื่อ/ศิลปิน/ปกที่ถูกต้องจาก videoId เอง
//   - รับคำสั่งจากโปรแกรม (เล่น/หยุด/กรอ/ถัดไป/ก่อนหน้า) ไปสั่งวิดีโอในหน้านี้
// กติกา: เบามาก · ทุกอย่างห่อ try/catch ห้าม throw ออกไปทำหน้าเว็บพัง
(() => {
  "use strict";
  if (window.__synclyricsLoaded) return;
  window.__synclyricsLoaded = true;

  const IS_MUSIC = location.hostname === "music.youtube.com";
  const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/;
  const TICK_MS = 250;       // ส่งเวลาทุก 250ms ตอนกำลังเล่น (โปรแกรมทำ smoothing ต่อเอง)
  const JUMP_S = 0.7;        // เวลาเล่นกระโดดเกินนี้จากที่คาด = มีการกรอ

  const st = {
    connected: false,   // โปรแกรมเปิดอยู่และเชื่อมต่อแล้ว
    enabled: true,      // ผู้ใช้เปิด "ส่งเพลงอัตโนมัติ" ไว้ (ค่าจากโปรแกรม)
    lastVid: null,      // videoId ที่ส่ง companion_track ไปแล้ว
    timer: null,
    lastT: 0,           // เวลา/วินาทีที่ส่งล่าสุด ไว้ตรวจการกรอ
    lastAt: 0,
  };

  const getVideo = () => document.querySelector("video.html5-main-video") || document.querySelector("video");

  /** กำลังเล่นโฆษณา (บัญชีไม่มี Premium): <video> เดียวกันเล่นโฆษณา เวลาไม่ใช่ของเพลง — ต้องไม่ให้เนื้อเพลงเดินตามโฆษณา */
  function adShowing() {
    const pl = document.getElementById("movie_player");
    return !!(pl && pl.classList.contains("ad-showing"));
  }

  function videoId() {
    try {
      const id = new URL(location.href).searchParams.get("v");
      return id && VIDEO_ID_RE.test(id) ? id : null;
    } catch (e) { return null; }
  }

  function send(type, payload) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ kind: "send", msg: { type, payload } }, (r) => {
          void chrome.runtime.lastError;
          resolve((r && r.result) || "dropped");
        });
      } catch (e) { resolve("dropped"); } // ส่วนขยายถูกรีโหลดระหว่างหน้าเปิดอยู่
    });
  }

  /** รายงานสถานะการเล่นปัจจุบัน (เรียกถี่ตอนเล่น + ทันทีที่ play/pause/seek/เปลี่ยนเพลง) */
  async function report(forceSeek = false) {
    try {
      if (!st.connected || !st.enabled) return;
      const v = getVideo();
      const vid = videoId();
      if (!v || !vid) return;
      const now = Date.now();
      const rate = v.playbackRate || 1;
      // โฆษณา: รายงานว่าหยุด ที่เวลาล่าสุดของเพลงจริง (ไม่ใช้เวลาของโฆษณา)
      const ad = adShowing();
      const paused = v.paused || ad;
      const curT = ad ? st.lastT : v.currentTime;
      const expected = st.lastT + ((now - st.lastAt) / 1000) * (paused ? 0 : rate);
      const seeked = forceSeek || (!ad && st.lastAt > 0 && Math.abs(curT - expected) > JUMP_S);
      st.lastT = curT;
      st.lastAt = now;
      if (vid !== st.lastVid) {
        st.lastVid = vid;
        // ส่งแค่ videoId — ชื่อ/ศิลปิน/ปกโปรแกรมหาเองจาก videoId
        if ((await send("companion_track", { track: { video_id: vid } })) === "dropped") st.lastVid = null;
      }
      await send("companion_state", {
        video_id: vid, current_time: curT, rate, paused, sent_at_ms: now, seeked,
        duration: !ad && isFinite(v.duration) ? v.duration : undefined,
        volume: st.vol !== undefined ? st.vol : v.volume,
        muted: st.muted !== undefined ? st.muted : v.muted,
      });
    } catch (e) { /* ห้ามพังหน้าเว็บ */ }
  }

  function syncTimer() {
    const v = getVideo();
    const playing = !!v && !v.paused && st.connected && st.enabled;
    if (playing && !st.timer) st.timer = setInterval(() => report(false), TICK_MS);
    else if (!playing && st.timer) { clearInterval(st.timer); st.timer = null; }
  }

  function onMediaEvent(seeked) {
    return (e) => {
      if (e.target !== getVideo()) return;
      syncTimer();
      report(seeked);
    };
  }

  /** คำสั่งจากโปรแกรม (ปุ่มในหน้าต่างเนื้อเพลง/คีย์ลัด) -> วิดีโอในหน้านี้ */
  function applyControl(m) {
    const v = getVideo();
    if (!v) return;
    switch (m.action) {
      case "play": v.play().catch(() => {}); break;
      case "pause": v.pause(); break;
      case "seek":
        if (typeof m.time === "number" && isFinite(m.time)) {
          if (st.pageAlive) {
            window.postMessage({ target: "synclyrics", type: "seek", value: m.time }, "*");
          } else {
            const top = isFinite(v.duration) && v.duration > 1 ? v.duration - 1 : Infinity;
            v.currentTime = Math.max(0, Math.min(m.time, top));
          }
        }
        break;
      case "volume":
        // ปรับผ่านตัวเล่นของ YouTube (page.js ในโลกของหน้าเว็บ) ให้แถบเสียงของ YouTube ขยับตาม · ถ้า page.js ไม่ตอบใน 400 ms ค่อยตั้งที่ <video> ตรงๆ
        if (typeof m.value === "number" && isFinite(m.value)) {
          const want = Math.max(0, Math.min(1, m.value));
          window.postMessage({ target: "synclyrics", type: "volume", value: want }, "*");
          setTimeout(() => {
            if (!st.pageAlive) { v.volume = want; if (want > 0 && v.muted) v.muted = false; }
          }, 400);
        }
        break;
      case "mute":
        window.postMessage({ target: "synclyrics", type: "mute", value: !!m.value }, "*");
        setTimeout(() => { if (!st.pageAlive) v.muted = !!m.value; }, 400);
        break;
      case "next": { const b = document.querySelector(IS_MUSIC ? ".next-button" : ".ytp-next-button"); if (b) b.click(); break; }
      case "prev": { const b = document.querySelector(IS_MUSIC ? ".previous-button" : ".ytp-prev-button"); if (b) b.click(); break; }
    }
  }

  function onNavigate() {
    try {
      st.lastVid = null;  // หน้า/เพลงเปลี่ยน -> ส่งเพลงใหม่ในรอบถัดไป
      st.lastAt = 0;
      syncTimer();
      report(true);
    } catch (e) { /* ignore */ }
  }

  // ค่าเสียงจากตัวเล่น YouTube (page.js) — ใช้รายงานให้โปรแกรมแทนค่าของ <video> (ค่าของ <video> ไม่ตรงกับแถบเสียงเมื่อเปิดปรับเสียงอัตโนมัติ)
  window.addEventListener("message", (e) => {
    const d = e.data;
    if (e.source !== window || !d || d.source !== "synclyrics" || d.type !== "volume_state") return;
    st.pageAlive = true;
    const changed = st.vol !== d.volume || st.muted !== d.muted;
    st.vol = d.volume;
    st.muted = d.muted;
    if (changed) report(false);
  });

  chrome.runtime.onMessage.addListener((m) => {
    try {
      if (m.kind === "app_state") {
        st.connected = !!m.appConnected;
        if (typeof m.autoSend === "boolean") st.enabled = m.autoSend;
        if (!st.connected) st.lastVid = null;  // แอปกลับมาแล้วต้องส่งเพลงซ้ำ
        syncTimer();
        report(true);
      } else if (m.kind === "tab_control") {
        applyControl(m);
      }
    } catch (e) { /* ห้ามพังหน้าเว็บ */ }
  });

  // เหตุการณ์ของ <video> ไม่ bubble — ฟังแบบ capture ที่ document
  for (const ev of ["play", "playing", "pause", "ratechange", "loadedmetadata", "durationchange", "ended", "emptied", "volumechange"])
    document.addEventListener(ev, onMediaEvent(false), true);
  document.addEventListener("seeked", onMediaEvent(true), true);
  window.addEventListener("yt-navigate-finish", onNavigate);
  document.addEventListener("yt-navigate-finish", onNavigate);
  window.addEventListener("popstate", onNavigate);
  window.addEventListener("pageshow", onNavigate);
  // ปิดแท็บ/ออกจากหน้า: บอกโปรแกรมว่าหยุดแล้ว (ไม่ให้ไฮไลต์เดินต่อทั้งที่ไม่มีเสียง)
  window.addEventListener("pagehide", () => {
    try {
      const vid = videoId();
      if (st.connected && vid) send("companion_state", { video_id: vid, current_time: st.lastT, rate: 1, paused: true,
        sent_at_ms: Date.now(), seeked: false });
    } catch (e) { /* ignore */ }
  });

  try {
    chrome.runtime.sendMessage({ kind: "get_state" }, (r) => {
      void chrome.runtime.lastError;
      if (!r) return;
      st.connected = !!r.appConnected;
      st.enabled = r.autoSend !== false;
      syncTimer();
      report(true);
    });
  } catch (e) { /* ส่วนขยายถูกรีโหลด */ }
})();
