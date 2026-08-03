/**
 * Headless render proof for the frontend module-federation platform (spec 94, LOCKED-3).
 * ZERO npm deps: drives Chrome via the DevTools Protocol using Node 22's built-in WebSocket + fetch.
 *
 * Proves the whole chain in a REAL browser:
 *   1. host boots, reads /capabilities, imports the participants REMOTE bundle at runtime;
 *   2. the remote's activate() registers into the host's shared slot registry (one singleton);
 *   3. the issue view's <Slot> RENDERS the remote's Participants section into the DOM;
 *   4. the ui_api_version gate accepts a compatible major and refuses an incompatible one;
 *   5. LIVE enable/disable: disabling the plugin removes its section from the DOM without a reload,
 *      re-enabling brings it back.
 *
 * Requires a running Radd server (serving the built web/dist) with the participants plugin enabled
 * and a reachable issue. Usage:
 *   node scripts/render-proof.mjs <baseUrl> <issueKey> <email> <password> [pluginId]
 * Chrome is discovered from $RADD_CHROME or the ms-playwright cache.
 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { resolve } from "node:path";
import { chromeArgs, findChrome, HOVER_CAPABLE_PROBE } from "./lib/chrome.mjs";

const [baseUrl, issueKey, email, password, pluginId = "participants"] = process.argv.slice(2);
const PORT = 9444;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-render-proof-profile");

const chrome = spawn(
  findChrome(),
  chromeArgs({ port: PORT, profile: PROFILE }),
  { stdio: "ignore" },
);

const consoleErrors = [];
let ws;
let nextId = 1;
const pending = new Map();

function send(method, params = {}, sessionId) {
  const id = nextId++;
  ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}
async function evalInPage(sessionId, expression) {
  const { result, exceptionDetails } = await send(
    "Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId,
  );
  if (exceptionDetails) throw new Error("page eval threw: " + (exceptionDetails.text || ""));
  return result.value;
}
const sectionSel = `'[data-plugin-section="participants"]'`;

async function main() {
  let version;
  for (let i = 0; i < 40 && !version; i++) {
    try { version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); }
    catch { await sleep(250); }
  }
  if (!version) throw new Error("Chrome CDP did not come up");

  ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true });
    ws.addEventListener("error", rej, { once: true });
  });
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? rej(new Error(m.error.message)) : res(m.result);
    } else if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
      consoleErrors.push(m.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
    } else if (m.method === "Runtime.exceptionThrown") {
      consoleErrors.push("EXCEPTION: " + (m.params.exceptionDetails?.exception?.description || ""));
    }
  });

  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sessionId);
  await send("Runtime.enable", {}, sessionId);

  await send("Page.navigate", { url: baseUrl + "/" }, sessionId);
  await sleep(1200);
  const loginStatus = await evalInPage(sessionId,
    `(async()=>{const r=await fetch("/api/v1/auth/login",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify({ email, password })})});return r.status;})()`);
  const manifestRemotes = await evalInPage(sessionId,
    `(async()=>(await (await fetch("/api/v1/capabilities",{credentials:"include"})).json()).remotes)()`);

  await send("Page.navigate", { url: `${baseUrl}/issues/${issueKey}` }, sessionId);
  let domFound = false, activePlugins = [], importMap = false;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    const p = await evalInPage(sessionId,
      `(()=>({dom:!!document.querySelector(${sectionSel}),active:(globalThis.__RADD_SLOT_REGISTRY__&&globalThis.__RADD_SLOT_REGISTRY__.activePlugins)?globalThis.__RADD_SLOT_REGISTRY__.activePlugins():[],importMap:!!document.querySelector('script[type="importmap"]')}))()`);
    activePlugins = p.active; importMap = p.importMap;
    if (p.dom) { domFound = true; break; }
  }

  const uiApiVersionGate = await evalInPage(sessionId,
    `(()=>{const m=globalThis.__RADD_SHARED__&&globalThis.__RADD_SHARED__["@radd/plugin-sdk"];return m?{compatible_1:m.isUiApiCompatible("1.4.0"),incompatible_2:m.isUiApiCompatible("2.0.0"),version:m.UI_API_VERSION}:null;})()`);

  // LIVE disable → the section must vanish without a reload; then re-enable → it returns.
  async function toggle(action) {
    await evalInPage(sessionId,
      `(async()=>{await fetch("/api/v1/plugins/${pluginId}/${action}",{method:"POST",credentials:"include"});globalThis.__RADD_QUERY_CLIENT__&&globalThis.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:["capabilities"]});})()`);
  }
  async function waitDom(want) {
    for (let i = 0; i < 30; i++) {
      await sleep(400);
      const present = await evalInPage(sessionId, `!!document.querySelector(${sectionSel})`);
      if (present === want) return true;
    }
    return false;
  }
  await toggle("disable");
  const disappearedOnDisable = await waitDom(false);
  await toggle("enable");
  const reappearedOnEnable = await waitDom(true);

  const result = {
    loginStatus, manifestRemotes, slotRegistryActivePlugins: activePlugins,
    participantsSectionRenderedInDom: domFound, importMapPresent: importMap,
    uiApiVersionGate, liveDisableRemovedSection: disappearedOnDisable,
    liveEnableRestoredSection: reappearedOnEnable, consoleErrors,
  };
  console.log(JSON.stringify(result, null, 2));

  await send("Target.closeTarget", { targetId });
  ws.close(); chrome.kill();
  const ok = loginStatus === 204 &&
    Array.isArray(manifestRemotes) && manifestRemotes.some((r) => r.name === "participants") &&
    activePlugins.includes("participants") && domFound && importMap &&
    uiApiVersionGate && uiApiVersionGate.compatible_1 === true && uiApiVersionGate.incompatible_2 === false &&
    disappearedOnDisable && reappearedOnEnable;
  process.exit(ok ? 0 : 1);
}
main().catch((e) => { console.error("PROOF ERROR:", e); try { chrome.kill(); } catch {} process.exit(2); });
