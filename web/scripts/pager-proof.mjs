/**
 * RADD-687 proof: a board over a huge result set pages past 200 with a TRUE
 * total — no silent truncation, no "200+". Zero-dep CDP, chrome.mjs pattern.
 *
 *   node scripts/pager-proof.mjs <baseUrl> <email> <password> <boardPath> <minTotal>
 *
 * Asserts: a Pagination nav exists; its stated total >= minTotal; navigating
 * to page 2 changes the first rendered card key.
 */
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { chromeArgs, findChrome } from "./lib/chrome.mjs";

const [baseUrl, email, password, boardPath, minTotalArg] = process.argv.slice(2);
const minTotal = Number(minTotalArg || 201);
const PORT = 9448;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-pager-proof-profile");

const login = await fetch(`${baseUrl}/api/v1/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password }),
});
if (login.status >= 300) throw new Error(`login failed: ${login.status}`);
const m = (login.headers.get("set-cookie") || "").match(/radd_session=([^;]+)/);
if (!m) throw new Error("no session cookie");

const chrome = spawn(findChrome(), chromeArgs({ port: PORT, profile: PROFILE }), { stdio: "ignore" });
let ws;
let nextId = 1;
const pending = new Map();
function send(method, params = {}, sessionId) {
  const id = nextId++;
  ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}
async function evalIn(sessionId, expression) {
  const { result, exceptionDetails } = await send(
    "Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId,
  );
  if (exceptionDetails) throw new Error("eval threw: " + (exceptionDetails.text || ""));
  return result.value;
}

let failed = false;
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
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Network.enable", {}, sessionId);
  await send("Network.setCookie",
    { name: "radd_session", value: m[1], domain: new URL(baseUrl).hostname, path: "/" }, sessionId);
  await send("Page.enable", {}, sessionId);
  await send("Emulation.setDeviceMetricsOverride",
    { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false }, sessionId);
  await send("Page.navigate", { url: `${baseUrl}${boardPath}` }, sessionId);
  await sleep(6000);

  const probe = await evalIn(sessionId, `(() => {
    const nav = document.querySelector('nav[aria-label="Pagination"]');
    const firstKey =
      [...document.querySelectorAll('[class*="font-mono"]')]
        .map((el) => el.textContent.trim())
        .find((text) => /^[A-Z]+-\\d+$/.test(text)) ?? null;
    return { hasPager: Boolean(nav), pagerText: nav ? nav.textContent : null, firstKey };
  })()`);
  if (!probe.hasPager) { console.error("FAIL: no Pagination nav rendered"); failed = true; }
  const totalMatch = (probe.pagerText || "").replace(/[,\u202f\u00a0]/g, "").match(/(\d{3,})/g);
  const statedMax = totalMatch ? Math.max(...totalMatch.map(Number)) : 0;
  if (statedMax < minTotal) {
    console.error(`FAIL: pager states ${statedMax}, expected >= ${minTotal} (text: ${probe.pagerText})`);
    failed = true;
  } else {
    console.log(`ok: pager states a true total (${statedMax} >= ${minTotal})`);
  }
  console.log("first card key on page 1:", probe.firstKey);

  await evalIn(sessionId, `(() => {
    const nav = document.querySelector('nav[aria-label="Pagination"]');
    const two = [...nav.querySelectorAll("button")].find((b) => b.textContent.trim() === "2");
    two?.click();
    return Boolean(two);
  })()`);
  await sleep(4000);
  const page2 = await evalIn(sessionId, `(() => ({
    firstKey:
      [...document.querySelectorAll('[class*="font-mono"]')]
        .map((el) => el.textContent.trim())
        .find((text) => /^[A-Z]+-\\d+$/.test(text)) ?? null,
    url: location.search,
  }))()`);
  if (page2.firstKey && page2.firstKey !== probe.firstKey) {
    console.log(`ok: page 2 renders different items (${probe.firstKey} -> ${page2.firstKey}; url ${page2.url})`);
  } else {
    console.error(`FAIL: page 2 first key unchanged (${page2.firstKey})`);
    failed = true;
  }
} finally {
  chrome.kill("SIGKILL");
}
process.exit(failed ? 1 : 0);
