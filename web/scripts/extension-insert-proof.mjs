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
import { resolve } from "node:path";
import { chromeArgs, findChrome, HOVER_CAPABLE_PROBE } from "./lib/chrome.mjs";

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);
const PORT = 9448;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ext-insert-proof");

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

/**
 * Click an element the way a person does: real mouse events at its centre,
 * dispatched through the browser's input pipeline so HIT-TESTING applies.
 *
 * This is the whole reason the proof is written this way. The first version
 * called `element.click()`, which delivers the event straight to the node and
 * ignores what is painted on top of it. That passed against a menu sitting
 * UNDER its own click-away overlay — a real click closed the menu and inserted
 * nothing, and the proof said "all passed". Element.click() cannot see a
 * z-index bug; Input.dispatchMouseEvent can.
 *
 * Returns what was actually hit, so a mis-targeted click fails loudly rather
 * than silently doing nothing.
 */
async function clickAt(sessionId, selector, match) {
  const box = await evalInPage(sessionId, `(() => {
    const nodes = [...document.querySelectorAll(${JSON.stringify(selector)})];
    const el = ${match ? `nodes.find((n) => (${match.toString()})(n.textContent || ""))` : "nodes[0]"};
    if (!el) return null;
    const target = el.closest("button") || el;
    const r = target.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    // What is actually painted at that point — the hit-test the DOM .click()
    // method skips.
    const top = document.elementFromPoint(x, y);
    return { x, y, hitIsInsideTarget: target.contains(top), hitTag: top ? top.tagName : null,
             hitClass: top ? String(top.className).slice(0, 60) : null };
  })()`);
  if (!box) throw new Error(`clickAt: nothing matched ${selector}`);
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", {
      type, x: box.x, y: box.y, button: "left", clickCount: 1,
    }, sessionId);
  }
  return box;
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
  // The profile dir persists between runs, so Chrome happily serves the PREVIOUS
  // bundle — which made this proof report failures against fixed code and passes
  // against broken code, depending on what was cached. Always fetch fresh.
  await send("Network.enable", {}, sessionId);
  await send("Network.setCacheDisabled", { cacheDisabled: true }, sessionId);
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

  await clickAt(sessionId, "svg.radd-extension-toolbar-icon");
  await sleep(900);

  // Compare against what the SERVER offers rather than a number baked in here —
  // the registry grows as extensions land, and a hardcoded threshold just goes
  // stale and starts failing correct code.
  const menu = await evalInPage(sessionId, `(async () => {
    const items = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')];
    const declared = await (await fetch("/api/v1/pages/extensions", {credentials:"include"})).json();
    return {
      count: items.length,
      declared: declared.length,
      labels: items.map((i) => i.textContent.trim().slice(0, 40)),
    };
  })()`);

  // Pick "Callout" — it has a schema with defaults, so the inserted block must
  // arrive pre-filled rather than empty. Real input, at real coordinates.
  const picked = await clickAt(
    sessionId,
    '[role="menu"] [role="menuitem"]',
    (t) => t.includes("Callout"),
  );
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

  // RADD-757: assert the launch flag took. Headless Chrome reports
  // `(hover: none)` by default and Tailwind v4 gates every `hover:`/
  // `group-hover:` utility on `@media (hover: hover)`, so without it this
  // proof silently stops seeing hover-revealed UI at all.
  const hoverCapable = await evalInPage(sessionId, HOVER_CAPABLE_PROBE);
  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "entered edit mode": enteredEdit === true,
    "extension toolbar button is present": toolbarButtonPresent === true,
    "the picker lists exactly what the registry declares":
      menu.declared > 0 && menu.count === menu.declared,
    "picker shows the Callout entry": menu.labels.some((l) => l.includes("Callout")),
    // The assertion that would have caught the overlay bug: what is PAINTED at
    // the click point has to be the menu item itself.
    "the menu item is what is painted at the click point": picked.hitIsInsideTarget === true,
    "a radd:callout fence was inserted and saved": /```radd:callout/.test(saved || ""),
    "the block arrived pre-filled from the schema defaults": /"kind":\s*"info"/.test(saved || ""),
    "no console errors": consoleErrors.length === 0,
  };

  console.log(JSON.stringify({ menu, picked, saved, consoleErrors }, null, 2));
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
