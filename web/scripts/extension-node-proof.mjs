/**
 * Proves RADD-746: a `radd:*` fence is a real editor NODE, not a code block.
 *
 * The insert proof already covers "picking an entry writes a fence". What it
 * cannot see is the thing this issue is about — that in EDIT mode the fence
 * renders as the block it describes, with chrome to reconfigure it, and that
 * saving a block nobody touched writes the markdown back unchanged.
 *
 * Four assertions carry the issue:
 *
 *  - the editor contains `[data-extension-editable]` and NO `radd:` code block
 *    (the fence was claimed at parse time, so the code-block view never saw it);
 *  - the rendered callout text is on screen while editing;
 *  - the hover chrome exists and its Configure button is what is PAINTED at its
 *    own coordinates (element.click() cannot see a z-index bug — RADD-742);
 *  - an untouched block round-trips byte-identically, and an edited one saves
 *    the new parameters.
 *
 * Usage: node scripts/extension-node-proof.mjs <baseUrl> <spaceSlug> <email> <password>
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

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9451;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ext-node-proof");

/** The seed body. Deliberately includes a fenced ```markdown example holding a
 *  `radd:toc` line: that is documentation, not an extension, and must stay a
 *  code block — the parse-time claim inspects the fence's own lang, so this is
 *  the case that tells a real transform from a regex sweep. */
const SEED = [
  "# Heading one",
  "",
  "```radd:callout",
  '{"kind": "warning", "title": "Mind the gap", "text": "Body text."}',
  "```",
  "",
  "````markdown",
  "```radd:toc",
  "```",
  "````",
  "",
  "tail prose",
  "",
].join("\n");

/**
 * Make headless Chrome admit it has a mouse.
 *
 * `--headless=new` reports `(hover: none)` and `(pointer: none)` at BASELINE —
 * before any emulation, and `Emulation.setEmulatedMedia` does not change it.
 * Tailwind v4 emits every `group-hover:` utility inside `@media (hover: hover)`,
 * so hover-revealed chrome is simply not styled in a headless proof: `:hover`
 * matches, the class is on the element, the selector matches, and the computed
 * style is still the un-hovered one. That reads exactly like a product bug.
 *
 * hover 2 = hover, pointer 4 = fine. This is a blind spot every proof in this
 * directory shares — anything gated on `group-hover:` is invisible without it.
 */
const HOVER_CAPABLE =
  "--blink-settings=primaryHoverType=2,availableHoverTypes=2," +
  "primaryPointerType=4,availablePointerTypes=4";

const chrome = spawn(
  findChrome(),
  ["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
   HOVER_CAPABLE,
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
  if (exceptionDetails) {
    const detail =
      exceptionDetails.exception?.description ||
      exceptionDetails.exception?.value ||
      exceptionDetails.text ||
      "";
    throw new Error("page eval threw: " + detail + "\n--- expression ---\n" + expression.slice(0, 600));
  }
  return result.value;
}

/** A real mouse click, at real coordinates, through the browser's input
 *  pipeline — so hit-testing applies. See extension-insert-proof for why. */
async function clickAt(sessionId, selector, match) {
  const box = await evalInPage(sessionId, `(() => {
    const nodes = [...document.querySelectorAll(${JSON.stringify(selector)})];
    const el = ${match ? `nodes.find((n) => (${match.toString()})(n.textContent || ""))` : "nodes[0]"};
    if (!el) return null;
    const target = el.closest("button") || el;
    const r = target.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const top = document.elementFromPoint(x, y);
    return {
      x, y,
      hitIsInsideTarget: target.contains(top),
      hitTag: top ? top.tagName : null,
      rect: { w: r.width, h: r.height },
      style: (() => { const s = getComputedStyle(target);
        return { opacity: s.opacity, pointerEvents: s.pointerEvents, display: s.display, zIndex: s.zIndex }; })(),
      // Every element painted at that point, outermost last — this is what
      // turns "the click missed" into "the click was intercepted by X".
      stack: [...document.elementsFromPoint(x, y)].slice(0, 5)
        .map((e) => e.tagName + "." + String(e.className).slice(0, 40)),
    };
  })()`);
  if (!box) throw new Error(`clickAt: nothing matched ${selector}`);
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", { type, x: box.x, y: box.y, button: "left", clickCount: 1 }, sessionId);
  }
  return box;
}

/** Move the pointer over an element so `group-hover` chrome actually appears —
 *  CSS hover does not respond to a synthesised event on the node. */
async function hoverOver(sessionId, selector) {
  const at = await evalInPage(sessionId, `(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + Math.min(12, r.height / 2) };
  })()`);
  if (!at) throw new Error(`hoverOver: nothing matched ${selector}`);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: at.x, y: at.y }, sessionId);
  return at;
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
  // A persistent profile happily serves the PREVIOUS bundle, which makes this
  // proof report on code that is not running. Always fetch fresh.
  await send("Network.enable", {}, sessionId);
  await send("Network.setCacheDisabled", { cacheDisabled: true }, sessionId);
  await send("Emulation.setDeviceMetricsOverride",
    { width: 1440, height: 1100, deviceScaleFactor: 2, mobile: false }, sessionId);

  await send("Page.navigate", { url: baseUrl + "/" }, sessionId);
  await sleep(1200);
  await evalInPage(sessionId,
    `(async()=>{const r=await fetch("/api/v1/auth/login",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify({ email, password })})});return r.status;})()`);

  const created = await evalInPage(sessionId, `(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "node-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Node proof", body }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  const before = await evalInPage(sessionId,
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  await send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${created.slug}` }, sessionId);
  await sleep(2500);

  await evalInPage(sessionId,
    `(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);

  // What the EDITOR contains. `.ProseMirror` scopes every query to editor-owned
  // DOM, so a read-mode block below cannot make this pass by accident.
  const inEditor = await evalInPage(sessionId, `(() => {
    const pm = [...document.querySelectorAll(".ProseMirror")];
    const q = (sel) => pm.flatMap((root) => [...root.querySelectorAll(sel)]);
    const nodes = q("[data-extension-editable]");
    // A code block is a <pre> only until CodeMirror's mode loads and then it is
    // a .cm-editor with no <pre> at all — so look for BOTH shapes, and for the
    // fence's own text, rather than for one of them.
    const codeish = [...q("pre"), ...q(".cm-editor")];
    return {
      nodeCount: nodes.length,
      names: nodes.map((n) => n.getAttribute("data-extension")),
      renderedText: nodes.map((n) => (n.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 80)),
      codeBlockCount: codeish.length,
      // The fenced markdown EXAMPLE must survive as code — its text is the tell.
      codeBlockText: codeish.map((n) => (n.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 40)),
      // No editor-owned element may still be showing the raw fence header.
      rawFenceVisible: pm.some((root) => (root.textContent || "").includes("radd:callout")),
      chromeButtons: q('button[aria-label^="Configure radd:"]').length,
    };
  })()`);

  // Hover, then click Configure — through the input pipeline, so a chrome row
  // painted under something else fails here rather than passing quietly.
  await hoverOver(sessionId, ".ProseMirror [data-extension-editable]");
  await sleep(400);
  // Read the CHROME ROW, not the button: opacity does not inherit, so
  // `getComputedStyle(button).opacity` is 1 whether or not the row is hidden —
  // an assertion on it passes against a chrome nobody can see.
  const configureVisible = await evalInPage(sessionId, `(() => {
    const b = document.querySelector('button[aria-label^="Configure radd:"]');
    if (!b) return null;
    const row = b.parentElement;
    const s = getComputedStyle(row);
    const r = b.getBoundingClientRect();
    return {
      rowOpacity: s.opacity,
      rowPointerEvents: s.pointerEvents,
      blockHovered: !!document.querySelector("[data-extension-editable]:hover"),
      rowInsideHoveredGroup: !!row.closest(".group:hover"),
      groupIsHovered: !!document.querySelector(".group:hover"),
      // Assert the emulation took: if this is false every hover assertion
      // below is meaningless, and should say so rather than reading as a bug.
      hoverCapable: matchMedia("(hover: hover)").matches,
      width: r.width, height: r.height,
      buttonPadding: getComputedStyle(b).padding,
      buttonClass: String(b.className).slice(0, 60),
    };
  })()`);
  const configureHit = await clickAt(sessionId, 'button[aria-label^="Configure radd:"]');
  await sleep(700);

  const dialog = await evalInPage(sessionId, `(() => {
    const d = document.querySelector('[role="dialog"]');
    if (!d) return null;
    const ta = d.querySelector("textarea");
    return {
      label: d.getAttribute("aria-label"),
      // The dialog must open on the block's ACTUAL parameters, not on defaults.
      value: ta ? ta.value : null,
      hasPreview: /Preview/.test(d.textContent || ""),
    };
  })()`);

  // Change a parameter and save the block. Defensive rather than throwing: a
  // missing textarea is a RESULT this proof should report, not a crash that
  // hides every assertion after it.
  const retyped = await evalInPage(sessionId, `(() => {
    const ta = document.querySelector('[role="dialog"] textarea');
    if (!ta) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(ta, JSON.stringify({ kind: "danger", title: "Mind the gap", text: "Body text.", unknown_param: 7 }));
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  await sleep(300);
  if (retyped) await clickAt(sessionId, '[role="dialog"] button', (t) => t.trim() === "Save");
  await sleep(700);

  const afterEdit = await evalInPage(sessionId, `(() => {
    const n = document.querySelector(".ProseMirror [data-extension-editable]");
    return n ? (n.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 80) : null;
  })()`);

  await evalInPage(sessionId, `(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);

  const saved = await evalInPage(sessionId,
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  // Round-trip with NOTHING touched: re-seed, open, save, compare.
  await evalInPage(sessionId, `(async () => {
    await fetch("/api/v1/pages/${created.id}", {
      method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ body: ${JSON.stringify(SEED)} }),
    });
  })()`);
  await send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${created.slug}` }, sessionId);
  await sleep(2500);
  await evalInPage(sessionId,
    `(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);
  await evalInPage(sessionId, `(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);
  const untouched = await evalInPage(sessionId,
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  const checks = {
    "the fence became an editor node": inEditor.nodeCount === 1 && inEditor.names[0] === "callout",
    "no editor element still shows the raw radd: fence": inEditor.rawFenceVisible === false,
    "the callout renders live while editing": /Mind the gap/.test(inEditor.renderedText.join(" ")),
    "a ```markdown example stays a code block":
      inEditor.codeBlockCount === 1 && inEditor.codeBlockText.join(" ").includes("radd:toc"),
    "hover chrome exists": inEditor.chromeButtons === 1,
    "the browser reports a hover-capable pointer": configureVisible?.hoverCapable === true,
    "hovering the block reveals the chrome":
      configureVisible?.blockHovered === true && configureVisible?.rowOpacity === "1",
    // Crepe's unlayered `.milkdown button { border: none; background: none }`
    // strips utility styling from any button inside the editor, and `p-1`
    // resolved to 0 there — the affordance was a 13x13 target before this.
    "the chrome buttons are a usable target":
      (configureVisible?.width ?? 0) >= 24 && (configureVisible?.height ?? 0) >= 24,
    "the Configure button is what is painted at its own coordinates":
      configureHit.hitIsInsideTarget === true,
    "the dialog opens on the block's actual parameters":
      dialog !== null && /Mind the gap/.test(dialog.value || ""),
    "the dialog previews the block": dialog?.hasPreview === true,
    "editing re-renders the block in place": afterEdit !== null && /Mind the gap/.test(afterEdit),
    "the edit is written back as a radd:callout fence": /```radd:callout/.test(saved || ""),
    "the edited parameter is persisted": /"kind":\s*"danger"/.test(saved || ""),
    "an unknown parameter is preserved, not dropped": /unknown_param/.test(saved || ""),
    "an untouched block round-trips byte-identically": untouched === before,
    "no console errors": consoleErrors.length === 0,
  };

  console.log(JSON.stringify({ inEditor, configureVisible, configureHit, dialog, retyped, afterEdit, saved, untouched, consoleErrors }, null, 2));
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
