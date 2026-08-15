/**
 * README screenshots (RADD-1080): real UI, real (synthetic) data, both themes.
 * Zero npm deps — the same CDP pattern as render-proof.mjs.
 *
 * Usage:
 *   node scripts/readme-shots.mjs <baseUrl> <email> <password> <boardPath> <issuePath> <outDir>
 *
 * Logs in over HTTP to mint a session cookie, plants it in the browser, then
 * captures: the board view in dark (the default theme) and the issue page in
 * light. 1440x900 @2x.
 */
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { chromeArgs, findChrome } from "./lib/chrome.mjs";

const [baseUrl, email, password, boardPath, issuePath, outDir = "shots"] = process.argv.slice(2);
if (!baseUrl || !email || !password || !boardPath || !issuePath) {
  console.error("usage: readme-shots.mjs <baseUrl> <email> <password> <boardPath> <issuePath> [outDir]");
  process.exit(2);
}
const PORT = 9447;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-readme-shots-profile");

// --- session cookie over plain HTTP ------------------------------------------
const login = await fetch(`${baseUrl}/api/v1/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password }),
});
if (login.status >= 300) throw new Error(`login failed: ${login.status}`);
const setCookie = login.headers.get("set-cookie") || "";
const m = setCookie.match(/radd_session=([^;]+)/);
if (!m) throw new Error("no radd_session cookie in login response");
const sessionValue = m[1];
const host = new URL(baseUrl).hostname;

// --- drive Chrome -------------------------------------------------------------
const chrome = spawn(findChrome(), chromeArgs({ port: PORT, profile: PROFILE }), { stdio: "ignore" });
let ws;
let nextId = 1;
const pending = new Map();
function send(method, params = {}, sessionId) {
  const id = nextId++;
  ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}

try {
  let version;
  for (let i = 0; i < 50; i++) {
    try { version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); break; }
    catch { await sleep(200); }
  }
  ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { res, rej } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
    }
  };

  mkdirSync(outDir, { recursive: true });

  async function shot(path, { light, file, settle = 3500 }) {
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    await send("Network.enable", {}, sessionId);
    await send("Network.setCookie", { name: "radd_session", value: sessionValue, domain: host, path: "/" }, sessionId);
    await send("Emulation.setDeviceMetricsOverride",
      { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false }, sessionId);
    await send("Page.enable", {}, sessionId);
    await send("Page.navigate", { url: `${baseUrl}${path}` }, sessionId);
    await sleep(settle);
    if (light) {
      await send("Runtime.evaluate",
        { expression: "document.documentElement.classList.add('light')" }, sessionId);
      await sleep(600);
    }
    const { data } = await send("Page.captureScreenshot", { format: "png" }, sessionId);
    const out = resolve(outDir, file);
    writeFileSync(out, Buffer.from(data, "base64"));
    console.log(`wrote ${out}`);
    await send("Target.closeTarget", { targetId });
  }

  await shot(boardPath, { light: false, file: "board-dark.png" });
  await shot(issuePath, { light: true, file: "issue-light.png" });
} finally {
  chrome.kill("SIGKILL");
}
