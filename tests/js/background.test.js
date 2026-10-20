// ทดสอบลอจิกของ extension/background.js ด้วย Node (จำลอง chrome API) — รันผ่าน tests/test_extension_js.py
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const code = fs.readFileSync(path.join(__dirname, "..", "..", "extension", "background.js"), "utf8");

function makeEnv() {
  const env = { ports: [], icons: [], timers: [], listeners: {}, tabMsgs: [], storage: {}, now: 1000000 };
  const listener = (name) => ({ addListener: (fn) => { (env.listeners[name] = env.listeners[name] || []).push(fn); } });
  const chrome = {
    runtime: {
      lastError: null,
      getManifest: () => ({ version: "9.9.9" }),
      connectNative: (host) => {
        const port = { host, sent: [], onMsg: [], onDisc: [],
          postMessage(m) { this.sent.push(m); },
          onMessage: { addListener: (fn) => port.onMsg.push(fn) },
          onDisconnect: { addListener: (fn) => port.onDisc.push(fn) } };
        env.ports.push(port);
        return port;
      },
      onMessage: listener("runtime.onMessage"),
      onInstalled: listener("onInstalled"),
      onStartup: listener("onStartup"),
      reload: () => { env.reloaded = true; },
    },
    action: { setIcon: (o) => { env.icons.push(o.path[16]); return Promise.resolve(); }, setTitle: () => Promise.resolve(), onClicked: listener("action.onClicked") },
    tabs: { query: () => Promise.resolve([{ id: 7 }, { id: 8 }]), sendMessage: (id, m) => { env.tabMsgs.push([id, m]); return Promise.resolve(); }, onRemoved: listener("tabs.onRemoved") },
    storage: { local: { get: async (k) => Object.assign({}, k, env.storage), set: async (o) => Object.assign(env.storage, o) } },
    contextMenus: { removeAll: (cb) => cb && cb(), create: () => {}, onClicked: listener("menus.onClicked") },
    alarms: { create: () => {}, onAlarm: listener("alarms.onAlarm") },
  };
  const ctx = { chrome, console, setTimeout: (fn, ms) => { env.timers.push([fn, ms]); return env.timers.length; }, clearTimeout: () => {},
                Date: { now: () => env.now }, URL, Promise };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  env.chrome = chrome;
  env.port = () => env.ports[env.ports.length - 1];
  env.sentTypes = () => env.port().sent.map((m) => m.type);
  env.fromHost = (type, payload = {}) => env.port().onMsg.forEach((f) => f({ v: 1, type, id: "", payload }));
  env.fromTab = (msg, tabId = 7) => new Promise((res) => env.listeners["runtime.onMessage"][0](msg, { tab: { id: tabId } }, res));
  env.state = (tabId, paused, extra = {}) => env.fromTab({ kind: "send", msg: { type: "companion_state", payload: Object.assign({ video_id: "dQw4w9WgXcQ", current_time: 5, paused }, extra) } }, tabId);
  env.connect = () => { env.fromHost("host_connected"); env.fromHost("hello_ack", { app_version: "0.3.0", auto_send: true }); };
  return env;
}
const tick = () => new Promise((r) => setImmediate(r));
const ids = (list) => JSON.stringify(list);

(async () => {
  // 1) เริ่ม: ต่อ host ชื่อถูก, ไอคอนเทา
  let e = makeEnv();
  assert.strictEqual(e.port().host, "com.synclyrics.host");
  assert.ok(e.icons[e.icons.length - 1].includes("off-"), "เริ่มต้นต้องเป็นไอคอนเทา");

  // 2) host ต่อ pipe ติด -> ส่ง hello · hello_ack -> ไอคอนปกติ + แจ้งทุกแท็บ
  e.fromHost("host_connected");
  assert.strictEqual(e.port().sent[0].type, "hello");
  assert.strictEqual(e.port().sent[0].payload.ext_version, "9.9.9");
  e.fromHost("hello_ack", { app_version: "0.3.0", auto_send: true });
  await tick();
  assert.ok(e.icons[e.icons.length - 1].includes("on-"));
  assert.ok(e.tabMsgs.some(([id, m]) => id === 7 && m.kind === "app_state" && m.appConnected === true));

  // 3) แอปไม่เชื่อม = รายงานเวลาเล่นถูกทิ้ง (ไม่เปิดแอปเอง ไม่ส่ง launch_app)
  e = makeEnv();
  let r = await e.state(7, false);
  assert.strictEqual(r.result, "dropped");
  assert.ok(!e.sentTypes().includes("launch_app"));

  // 4) เชื่อมแล้ว: ส่งต่อเป็น companion_state เป็นข้อความ envelope ที่ถูกต้อง
  e.connect();
  r = await e.state(7, false);
  assert.strictEqual(r.result, "sent");
  const last = e.port().sent[e.port().sent.length - 1];
  assert.strictEqual(last.type, "companion_state");
  assert.strictEqual(last.v, 1);
  assert.strictEqual(last.payload.video_id, "dQw4w9WgXcQ");

  // 5) หลายแท็บ: แท็บที่กำลังเล่นยึดไว้ แท็บอื่นที่หยุดอยู่ถูกทิ้ง ไม่แย่งเนื้อเพลง
  e = makeEnv();
  e.connect();
  assert.strictEqual((await e.state(7, false)).result, "sent");   // แท็บ 7 เล่นอยู่
  assert.strictEqual((await e.state(8, true)).result, "dropped"); // แท็บ 8 หยุดอยู่ ห้ามแย่ง
  assert.strictEqual((await e.fromTab({ kind: "send", msg: { type: "companion_track", payload: { track: { video_id: "dQw4w9WgXcQ" } } } }, 8)).result, "dropped");
  assert.strictEqual((await e.state(8, false)).result, "sent");   // แท็บ 8 เริ่มเล่น = ย้ายต้นทางไปที่ 8
  e.tabMsgs.length = 0;
  e.fromHost("tab_control", { action: "seek", time: 30 });
  assert.strictEqual(ids(e.tabMsgs[0]), ids([8, { kind: "tab_control", action: "seek", time: 30 }]), "คำสั่งต้องไปที่แท็บที่เล่นอยู่");
  assert.strictEqual((await e.state(7, true)).result, "dropped"); // แท็บ 7 หยุดอยู่ ยังไม่แย่ง
  e.now += 3500;                                                   // แท็บ 8 เงียบนาน = ไม่ได้เล่นแล้ว
  assert.strictEqual((await e.state(7, true)).result, "sent");    // แท็บ 7 รับช่วงได้

  // 6) ปิดแท็บต้นทาง -> บอกแอปว่าหยุด (paused:true)
  e = makeEnv();
  e.connect();
  await e.state(7, false, { current_time: 42 });
  e.listeners["tabs.onRemoved"][0](7);
  const m = e.port().sent[e.port().sent.length - 1];
  assert.strictEqual(m.type, "companion_state");
  assert.strictEqual(m.payload.paused, true);
  assert.strictEqual(m.payload.current_time, 42);
  const n = e.port().sent.length;
  e.listeners["tabs.onRemoved"][0](99);   // แท็บอื่นปิด ไม่เกี่ยว
  assert.strictEqual(e.port().sent.length, n);

  // 7) กดไอคอนตอนแอปปิด: สั่ง launch_app แล้วรอ · พอเชื่อมค่อยส่ง focus · ตอนเชื่อมแล้วส่ง focus ทันที
  e = makeEnv();
  e.listeners["action.onClicked"][0]({ id: 7 });
  assert.ok(e.sentTypes().includes("launch_app"));
  assert.ok(!e.sentTypes().includes("command"));
  e.connect();
  const cmd = e.port().sent.find((x) => x.type === "command");
  assert.ok(cmd && cmd.payload.name === "focus", "เชื่อมต่อแล้วต้องดึงหน้าต่างขึ้น");
  e.port().sent.length = 0;
  e.listeners["action.onClicked"][0]({ id: 7 });
  assert.strictEqual(e.port().sent[0].type, "command");
  assert.ok(!e.sentTypes().includes("launch_app"));

  // 8) เมนูคลิกขวา: คำสั่งควบคุมไปที่แอป
  e = makeEnv();
  e.connect();
  for (const [id, name] of [["act_playpause", "play_pause"], ["act_prev", "prev"], ["act_next", "next"], ["act_settings", "open_settings"]]) {
    e.listeners["menus.onClicked"][0]({ menuItemId: id });
    const c = e.port().sent[e.port().sent.length - 1];
    assert.strictEqual(c.type, "command");
    assert.strictEqual(c.payload.name, name);
  }

  // 9) get_state: ค่าส่งอัตโนมัติจากแอปมาก่อน (แอปปิด = ส่วนขยายไม่ส่งอะไร)
  e = makeEnv();
  e.fromHost("hello_ack", { auto_send: false });
  r = await e.fromTab({ kind: "get_state" });
  assert.strictEqual(r.appConnected, true);
  assert.strictEqual(r.autoSend, false, "แอปปิดการส่งอัตโนมัติ ส่วนขยายต้องเคารพ");

  // 10) โปรแกรมปิด (host ยังอยู่) -> ไอคอนเทา, แท็บได้ app_state:false
  e.tabMsgs.length = 0;
  e.fromHost("status", { connected: false });
  await tick();
  assert.ok(e.icons[e.icons.length - 1].includes("off-"));
  assert.ok(e.tabMsgs.some(([, x]) => x.kind === "app_state" && x.appConnected === false));

  // 11) host ยังไม่ได้ลงทะเบียน -> จุดแดง + ต่อใหม่ใน 2 วิ
  e = makeEnv();
  e.timers.length = 0;
  e.chrome.runtime.lastError = { message: "Specified native messaging host not found." };
  e.port().onDisc.forEach((f) => f());
  e.chrome.runtime.lastError = null;
  assert.ok(e.icons[e.icons.length - 1].includes("error-"), "host หาไม่เจอต้องเป็นจุดแดง");
  const retry = e.timers.find(([, ms]) => ms === 2000);
  assert.ok(retry, "ต้องตั้งเวลาต่อใหม่ 2 วิ");
  retry[0]();
  assert.strictEqual(e.ports.length, 2, "ครบ 2 วิแล้วต้องต่อ host ใหม่");

  // 12) reload_extension จากแอป
  e = makeEnv();
  e.fromHost("reload_extension");
  assert.strictEqual(e.reloaded, true);

  console.log("background.test.js: ผ่านทั้งหมด");
})().catch((err) => { console.error("FAIL:", err.stack || err.message); process.exit(1); });
