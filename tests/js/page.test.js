// ทดสอบ extension/page.js (สคริปต์ปรับเสียงในโลกของหน้าเว็บ) ด้วยหน้าเว็บจำลอง — ไม่ต้องมี Chrome
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const assert = require("assert");

function run({ withPlayer }) {
  const posts = [];
  const listeners = {};
  const calls = [];
  const player = {
    vol: 50, muted: false,
    setVolume(v) { calls.push(["setVolume", v]); this.vol = v; },
    getVolume() { return this.vol; },
    isMuted() { return this.muted; },
    mute() { calls.push(["mute"]); this.muted = true; },
    unMute() { calls.push(["unMute"]); this.muted = false; },
  };
  const video = { volume: 0.5, muted: false };
  const win = {
    postMessage: (d) => posts.push(d),
    addEventListener: (n, f) => { listeners[n] = f; },
  };
  win.window = win;
  const sandbox = {
    window: win,
    document: {
      getElementById: (id) => (withPlayer && id === "movie_player" ? player : null),
      querySelector: (s) => (s === "video" ? video : null),
    },
    setInterval: () => 0,
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "..", "extension", "page.js"), "utf8"), sandbox);
  const send = (m) => listeners.message({ source: win, data: { target: "synclyrics", ...m } });
  return { send, calls, posts, player, video };
}

// มีตัวเล่น YouTube: ต้องเรียก setVolume (0-100) ของตัวเล่น ไม่ใช่ตั้ง <video>.volume ตรงๆ
{
  const t = run({ withPlayer: true });
  t.send({ type: "volume", value: 0.3 });
  assert.deepStrictEqual(t.calls[0], ["setVolume", 30]);
  assert.strictEqual(t.video.volume, 0.5);
  const last = t.posts[t.posts.length - 1];
  assert.strictEqual(last.type, "volume_state");
  assert.strictEqual(last.volume, 0.3);
  t.send({ type: "mute", value: true });
  assert.strictEqual(t.player.muted, true);
  t.send({ type: "volume", value: 0.8 });          // ลากเสียงขึ้นตอนปิดเสียง = เลิกปิดเสียง
  assert.strictEqual(t.player.muted, false);
  assert.strictEqual(t.posts[t.posts.length - 1].volume, 0.8);
}
// ไม่มีตัวเล่น (เช่น embed): ตั้งที่ <video> โดยตรง
{
  const t = run({ withPlayer: false });
  t.send({ type: "volume", value: 0.2 });
  assert.strictEqual(t.video.volume, 0.2);
  t.send({ type: "mute", value: true });
  assert.strictEqual(t.video.muted, true);
}
// ข้อความจากที่อื่น (ไม่ใช่ของเรา) ถูกเมิน
{
  const t = run({ withPlayer: true });
  t.send({ target: "other", type: "volume", value: 0.1 });
  assert.strictEqual(t.calls.length, 0);
}
console.log("page.js ok");
