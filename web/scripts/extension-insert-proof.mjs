/**
 * Proves the RADD-709 insert menu: the toolbar button opens a picker built from
 * `GET /pages/extensions`, and choosing an entry inserts a real ```radd:<name>
 * fence into the editor — pre-filled from the spec's schema defaults.
 *
 * The assertion that matters is the LAST one: after picking, the page's saved
 * markdown must contain the fence. A menu that opens and inserts nothing would
 * pass every other check.
 *
 * Usage: node scripts/extension-insert-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { existsSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";

function findChrome() {
  if (process.env.RADD_CHROME && existsSync(process.env.RADD_CHROME)) return process.env.RADD_CHROME;
  const base = resolve(homedir(), ".cache/ms-playwright");
  if (existsSync(base)) {
    for (const dir of readdirSync(base)) {
      for (const leaf of ["chrome-linux64/chrome", "chrome-linux/chrome"]) {
        const p = resolve(base, dir, leaf);
        if (existsSync(p)) return p;
      }
    }
  }
  for (const p of ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]) {
    if (existsSync(p)) return p;
  }
  throw new Error("no Chrome/Chromium found (set $RADD_CHROME)");
}

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);
const PORT = 9448;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ext-insert-proof");

const chrome = spawn(
  findChrome(),
  ["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
   `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, "about:blank"],
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
  await send("Emulation.setDeviceMetricsOverride",
    { width: 1440, height: 1000, deviceScaleFactor: 2, mobile: false }, sessionId);

  await send("Page.navigate", { url: baseUrl + "/" }, sessionId);
  await sleep(1200);
  await evalInPage(sessionId,
    `(async()=>{const r=await fetch("/api/v1/auth/login",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify({ email, password })})});return r.status;})()`);

  // A scratch page of its own, so the proof never edits the render-proof page.
  const created = await evalInPage(sessionId, `(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    let page = pages.find((p) => p.slug === "insert-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Insert proof", body: "seed\\n" }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body: "seed\\n" }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  await send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${created.slug}` }, sessionId);
  await sleep(2500);

  // Enter edit mode.
  const enteredEdit = await evalInPage(sessionId, `(() => {
    const btn = document.querySelector('button[aria-label="Edit page"]');
    if (!btn) return false;
    btn.click();
    return true;
  })()`);
  await sleep(2500);

  const toolbarButtonPresent = await evalInPage(sessionId,
    `!!document.querySelector("svg.radd-extension-toolbar-icon")`);

  // A bare .click() does NOT open it: Crepe's toolbar items act on mousedown,
  // so the first version of this proof reported an empty menu against working
  // code. Fire the whole pointer sequence.
  await evalInPage(sessionId, `(() => {
    const b = document.querySelector("svg.radd-extension-toolbar-icon")?.closest("button");
    if (!b) return;
    for (const type of ["pointerdown", "mousedown", "mouseup", "click"]) {
      b.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
  })()`);
  await sleep(900);

  const menu = await evalInPage(sessionId, `(() => {
    const items = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')];
    return { count: items.length, labels: items.map((i) => i.textContent.trim().slice(0, 40)) };
  })()`);

  // Pick "Callout" — it has a schema with defaults, so the inserted block must
  // arrive pre-filled rather than empty.
  await evalInPage(sessionId, `(() => {
    const item = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')]
      .find((i) => i.textContent.includes("Callout"));
    item && item.click();
  })()`);
  await sleep(900);

  // Save, then read the persisted markdown back from the API — the only proof
  // that survives the round trip.
  await evalInPage(sessionId, `(() => {
    const save = [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save");
    save && save.click();
  })()`);
  await sleep(2000);

  const saved = await evalInPage(sessionId,
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  const checks = {
    "entered edit mode": enteredEdit === true,
    "extension toolbar button is present": toolbarButtonPresent === true,
    "picker lists the registry": menu.count >= 7,
    "picker shows the Callout entry": menu.labels.some((l) => l.includes("Callout")),
    "a radd:callout fence was inserted and saved": /```radd:callout/.test(saved || ""),
    "the block arrived pre-filled from the schema defaults": /"kind":\s*"info"/.test(saved || ""),
    "no console errors": consoleErrors.length === 0,
  };

  console.log(JSON.stringify({ menu, saved, consoleErrors }, null, 2));
  console.log("");
  let failed = 0;
  for (const [label, ok] of Object.entries(checks)) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}`);
    if (!ok) failed++;
  }
  console.log(failed ? `\n${failed} FAILED` : "\nall passed");
  return failed;
}

main()
  .then((failed) => { chrome.kill(); process.exit(failed ? 1 : 0); })
  .catch((err) => { console.error(err); chrome.kill(); process.exit(2); });
