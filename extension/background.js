// SyncLyrics — service worker
// หน้าที่: ต่อ native host, ส่งต่อรายงานเวลาเล่นจากแท็บ YouTube ไปโปรแกรม (เลือกแท็บที่กำลังเล่นให้ ไม่สลับไปมา),
//          ส่งคำสั่งจากโปรแกรม (เล่น/หยุด/กรอ/ถัดไป/ก่อนหน้า) ไปแท็บนั้น, ไอคอนสถานะ, เมนูคลิกขวาที่ไอคอน
// กติกา: เบา ไม่ทำงานหนัก · ผิดพลาดต้องไม่ throw ออกนอกฟังก์ชัน · ซอง = {v:1,type,id,payload}
"use strict";

const HOST = "com.synclyrics.host";
const EXT_VERSION = chrome.runtime.getManifest().version;
const RECONNECT_MS = 2000;
const ACTIVE_STALE_MS = 3000;   // แท็บที่เล่นอยู่เงียบเกินนี้ = ถือว่าไม่ได้เล่นแล้ว แท็บอื่นเข้าแทนได้
const YT_URLS = ["https://www.youtube.com/*", "https://music.youtube.com/*"];

const S = {
  port: null,
  hostError: "",
  appConnected: false,   // host ต่อ pipe ของโปรแกรมได้ และผ่าน hello_ack แล้ว
  autoSend: true,        // ค่าจากโปรแกรม (ตั้งค่า "ส่งเพลงจาก YouTube อัตโนมัติ")
  activeTab: null,       // แท็บที่เป็นต้นทางของเนื้อเพลงตอนนี้
  activeAt: 0,           // ครั้งสุดท้ายที่แท็บนั้นรายงานว่ากำลังเล่น
  lastState: null,       // payload companion_state ล่าสุดของแท็บที่ active (ไว้ส่ง paused ตอนแท็บปิด)
  focusPending: null,    // คำสั่งที่รอแอปเปิด (กดไอคอน/เมนูตอนแอปปิด) ส่งเมื่อเชื่อมต่อแล้ว
  reconnectTimer: null,
};

const env = (type, payload = {}) => ({ v: 1, type, id: "", payload });

// ---------- ไอคอน ----------
function setIcon(state) {
  const p = {};
  for (const s of [16, 32, 48, 128]) p[s] = `icons/${state}-${s}.png`;
  chrome.action.setIcon({ path: p }).catch(() => {});
  const title = {
    on: "SyncLyrics — เชื่อมแล้ว",
    off: "SyncLyrics — โปรแกรมปิดอยู่ (กดเพื่อเปิด)",
    error: "SyncLyrics — มีปัญหา: " + (S.hostError || "ต่อโปรแกรมไม่ได้"),
  }[state];
  chrome.action.setTitle({ title }).catch(() => {});
}
function refreshIcon() {
  if (S.hostError) return setIcon("error");
  setIcon(S.appConnected ? "on" : "off");
}

// ---------- ต่อ host ----------
function connect() {
  if (S.port) return;
  clearTimeout(S.reconnectTimer);
  try {
    const port = chrome.runtime.connectNative(HOST);
    S.port = port;
    port.onMessage.addListener(onHostMessage);
    port.onDisconnect.addListener(() => {
      const err = chrome.runtime.lastError && chrome.runtime.lastError.message;
      S.port = null;
      S.appConnected = false;
      S.hostError = err || "";   // host ลงทะเบียนไม่ได้/พัง = จุดแดง · ปิดปกติ = เทา
      refreshIcon();
      broadcast({ kind: "app_state", appConnected: false });
      S.reconnectTimer = setTimeout(connect, RECONNECT_MS);
    });
    S.hostError = "";
  } catch (e) {
    S.port = null;
    S.hostError = String((e && e.message) || e);
    refreshIcon();
    S.reconnectTimer = setTimeout(connect, RECONNECT_MS);
  }
}

function rawSend(msg) {
  try { if (S.port) { S.port.postMessage(msg); return true; } } catch (e) { /* port ปิดไปแล้ว */ }
  return false;
}

// ---------- ข้อความจาก host/โปรแกรม ----------
function onHostMessage(m) {
  if (!m || typeof m.type !== "string") return;
  const p = m.payload || {};
  switch (m.type) {
    case "host_connected":   // host ต่อ pipe ของโปรแกรมติดแล้ว -> ทักทาย
      rawSend(env("hello", { ext_version: EXT_VERSION, browser: "chrome" }));
      break;
    case "hello_ack":
      S.appConnected = true;
      S.hostError = "";
      if (typeof p.auto_send === "boolean") S.autoSend = p.auto_send;
      refreshIcon();
      if (S.focusPending) { rawSend(env("command", { name: S.focusPending })); S.focusPending = null; }
      broadcast({ kind: "app_state", appConnected: true, autoSend: S.autoSend });
      break;
    case "status":
      if (p.connected === false) {   // โปรแกรมปิด (host ยังอยู่ รอโปรแกรมกลับมา)
        S.appConnected = false;
        refreshIcon();
        broadcast({ kind: "app_state", appConnected: false });
      }
      break;
    case "tab_control":
      if (S.activeTab != null) chrome.tabs.sendMessage(S.activeTab, { kind: "tab_control", ...p }).catch(() => {});
      break;
    case "reload_extension":
      chrome.runtime.reload();
      break;
    case "error":
      if (p.code === "app_not_running") {
        S.appConnected = false;
        refreshIcon();
        broadcast({ kind: "app_state", appConnected: false });
      }
      break;
  }
}

/** ส่งให้แท็บ YouTube ทุกแท็บ */
async function broadcast(msg) {
  try {
    const tabs = await chrome.tabs.query({ url: YT_URLS });
    for (const t of tabs) chrome.tabs.sendMessage(t.id, msg).catch(() => {});
  } catch (e) { /* ไม่มีแท็บ */ }
}

// ---------- เลือกแท็บต้นทาง (UX UI ข้อ 6.1: หลายแท็บต้องไม่สลับเพลงไปมาโดยไม่มีเหตุผล) ----------
// ยึดแท็บที่กำลังเล่นอยู่ · แท็บอื่นเริ่มเล่น = ย้ายไปแท็บนั้น · แท็บที่ไม่ได้เล่น (หยุดอยู่) ไม่แย่งจากแท็บที่เล่นอยู่
function accept(tabId, type, payload, now) {
  const playing = type === "companion_state" && payload && payload.paused === false;
  if (playing) {
    if (S.activeTab !== tabId) { S.activeTab = tabId; }
    S.activeAt = now;
    return true;
  }
  if (S.activeTab == null || S.activeTab === tabId || now - S.activeAt > ACTIVE_STALE_MS) {
    if (S.activeTab !== tabId) S.activeTab = tabId;
    return true;
  }
  return false;   // แท็บอื่นกำลังเล่นอยู่ — ทิ้งรายงานของแท็บที่หยุดนี้
}

// ---------- ข้อความจาก content script ----------
chrome.runtime.onMessage.addListener((m, sender, reply) => {
  (async () => {
    try {
      if (m.kind === "get_state") {
        const opts = await chrome.storage.local.get({ autoSend: true });
        reply({ appConnected: S.appConnected, autoSend: S.autoSend && opts.autoSend });
      } else if (m.kind === "send" && m.msg) {
        const tabId = sender.tab ? sender.tab.id : null;
        const t = m.msg.type;
        if (t === "companion_track" || t === "companion_state") {
          if (!S.appConnected || tabId == null || !accept(tabId, t, m.msg.payload, Date.now())) return reply({ result: "dropped" });
          if (t === "companion_state") S.lastState = m.msg.payload;
        }
        reply({ result: S.appConnected && rawSend(env(t, m.msg.payload || {})) ? "sent" : "dropped" });
      } else {
        reply({});
      }
    } catch (e) {
      reply({ error: String((e && e.message) || e) });
    }
  })();
  return true;   // ตอบแบบ async
});

// แท็บต้นทางถูกปิด: บอกโปรแกรมว่าหยุดแล้ว
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId !== S.activeTab) return;
  S.activeTab = null;
  if (S.lastState && S.appConnected) rawSend(env("companion_state", Object.assign({}, S.lastState, { paused: true, sent_at_ms: Date.now() })));
});

// ---------- กดไอคอน / เมนูคลิกขวาที่ไอคอน ----------
chrome.action.onClicked.addListener(() => {
  if (S.appConnected) return void rawSend(env("command", { name: "focus" }));
  S.focusPending = "focus";
  if (!S.port) connect();
  rawSend(env("launch_app"));
});

const MENU = [
  { id: "act_focus", title: "เปิดหน้าต่างเนื้อเพลง", contexts: ["action"] },
  { id: "act_playpause", title: "เล่น / หยุด", contexts: ["action"] },
  { id: "act_prev", title: "เพลงก่อนหน้า", contexts: ["action"] },
  { id: "act_next", title: "เพลงถัดไป", contexts: ["action"] },
  { id: "act_settings", title: "เปิดหน้าตั้งค่า", contexts: ["action"] },
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => { for (const m of MENU) chrome.contextMenus.create(m); });
});

chrome.contextMenus.onClicked.addListener((info) => {
  const cmd = (name) => {
    if (S.appConnected) return rawSend(env("command", { name }));
    S.focusPending = name === "focus" || name === "open_settings" ? name : null;
    if (!S.port) connect();
    rawSend(env("launch_app"));
  };
  switch (info.menuItemId) {
    case "act_focus": cmd("focus"); break;
    case "act_playpause": cmd("play_pause"); break;
    case "act_prev": cmd("prev"); break;
    case "act_next": cmd("next"); break;
    case "act_settings": cmd("open_settings"); break;
  }
});

// ---------- เริ่มต้น / กัน service worker หลับ ----------
chrome.alarms.create("reconnect", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "reconnect" && !S.port) connect(); });
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
refreshIcon();
connect();
