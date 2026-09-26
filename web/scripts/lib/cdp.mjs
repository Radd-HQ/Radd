/** CDP plumbing shared by every proof (RADD-757). Each helper encodes a lesson paid for once
 *  (e.g. RADD-742's hit-tested clicks), so a fix here reaches every proof. */
import { spawn } from "node:child_process";
import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve as resolvePath, sep } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { chromeArgs, findChrome, HOVER_CAPABLE_PROBE } from "./chrome.mjs";

export { HOVER_CAPABLE_PROBE };

/**
 * Launch Chrome, connect to it, and open a page target.
 *
 * Returns `{ session, close }`, where `session` carries every helper below
 * already bound to the browser and session id — so a proof never threads
 * `sessionId` through its own code.
 */
export async function openBrowser({ port: basePort, profile, width = 1440, height = 1000, scale = 2 }) {
  // Proofs hard-code their debug ports; RADD_PROOF_PORT_OFFSET shifts them all, so two runs (two
  // agents, a CI job beside a developer) can use disjoint ranges without editing any proof.
  const port = basePort + (Number(process.env.RADD_PROOF_PORT_OFFSET) || 0);
  // A browser already on this port leaked from an earlier run (other code, other flags);
  // attaching would make every assertion describe the wrong browser. Fail loudly.
  try {
    const stale = await fetch(`http://127.0.0.1:${port}/json/version`);
    if (stale.ok) {
      throw new Error(
        `a browser is already listening on ${port} — a previous run leaked one. ` +
          `Kill it (pkill -f "remote-debugging-port=${port}") and try again.`,
      );
    }
  } catch (error) {
    if (error instanceof Error && error.message.includes("already listening")) throw error;
    // Connection refused is the good case: nothing there.
  }

  // stderr is KEPT (RADD-1135): with it ignored, a Chrome that crashed and a
  // Chrome that was merely slow produced the same one-line failure, and the CI
  // log had nothing from the browser itself to say which.
  const chrome = spawn(findChrome(), chromeArgs({ port, profile }), {
    stdio: ["ignore", "ignore", "pipe"],
  });
  const stderr = [];
  chrome.stderr.on("data", (chunk) => {
    stderr.push(String(chunk));
    if (stderr.length > 200) stderr.shift();
  });
  let exited = null;
  chrome.on("exit", (code, signal) => { exited = { code, signal }; });
  // The harness owns the browser: killed on exit even if the proof throws, and a temp-dir
  // profile removed with it (~50 MB/run once filled /tmp).
  const scratch = resolvePath(profile).startsWith(resolvePath(tmpdir()) + sep);
  const dispose = () => {
    try { chrome.kill(); } catch { /* already gone */ }
    if (scratch) { try { rmSync(profile, { recursive: true, force: true, maxRetries: 3 }); } catch { /* best effort */ } }
  };
  process.on("exit", dispose);

  // 60 s (RADD-1135): a cold first launch on a GitHub runner overran 10 s; locally this exits
  // on the first poll.
  let version;
  const deadline = Date.now() + 60_000;
  while (!version && Date.now() < deadline && !exited) {
    try { version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); }
    catch { await sleep(250); }
  }
  if (!version) {
    chrome.kill();
    const tail = stderr.join("").trim().split("\n").slice(-40).join("\n");
    const why = exited
      ? `Chrome exited (code ${exited.code}, signal ${exited.signal}) before its DevTools port opened`
      : "Chrome CDP did not come up within 60 s";
    throw new Error(tail ? `${why}\n--- chrome stderr (tail) ---\n${tail}` : why);
  }

  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true });
    ws.addEventListener("error", rej, { once: true });
  });

  const consoleErrors = [];
  const pending = new Map();
  let nextId = 1;
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

  const rawSend = (method, params = {}, sessionId) => {
    const id = nextId++;
    ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
    return new Promise((res, rej) => pending.set(id, { res, rej }));
  };

  const { targetId } = await rawSend("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await rawSend("Target.attachToTarget", { targetId, flatten: true });
  const send = (method, params = {}) => rawSend(method, params, sessionId);

  await send("Page.enable");
  await send("Runtime.enable");
  // A persistent profile happily serves the PREVIOUS bundle, which makes a proof
  // report on code that is not running — passing against broken code or failing
  // against fixed code, depending on what was cached. Always fetch fresh.
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  // Chrome keeps 250 resource-timing entries and then DROPS the rest. A plain home-page load now
  // fetches ~210 script chunks, so any request after that went unrecorded — and every "X was not
  // loaded" check read an empty list and passed without looking (RADD-1392 merge). Raise the cap on
  // every document before its first script runs.
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: "performance.setResourceTimingBufferSize(100000);",
  });
  await send("Emulation.setDeviceMetricsOverride",
    { width, height, deviceScaleFactor: scale, mobile: false });

  const session = {
    /** Raw CDP for what the helpers do not cover (extra headers, emulation). */
    send,
    consoleErrors,
    eval: (expression) => evalInPage(send, expression),
    click: (selector, match) => clickAt(send, selector, match),
    hover: (selector) => hoverOver(send, selector),
    navigate: async (url, settleMs = 2000) => {
      await send("Page.navigate", { url });
      await sleep(settleMs);
    },
    login: (baseUrl, email, password) =>
      evalInPage(send, `(async()=>{const r=await fetch("/api/v1/auth/login",{method:"POST",` +
        `credentials:"include",headers:{"Content-Type":"application/json"},` +
        `body:JSON.stringify(${JSON.stringify({ email, password })})});return r.status;})()`),
    hoverCapable: () => evalInPage(send, HOVER_CAPABLE_PROBE),
    /** PNG screenshot of the viewport (or the full page) to `path`. */
    screenshot: async (path, { fullPage = false } = {}) => {
      const { writeFile } = await import("node:fs/promises");
      const params = { format: "png", captureBeyondViewport: fullPage };
      if (fullPage) {
        const { contentSize } = await send("Page.getLayoutMetrics");
        params.clip = { x: 0, y: 0, width: contentSize.width, height: contentSize.height, scale: 1 };
      }
      const { data } = await send("Page.captureScreenshot", params);
      await writeFile(path, Buffer.from(data, "base64"));
    },
  };

  return {
    session,
    // Wait for Chrome to exit before removing its profile, or it may still be writing into it.
    close: () => new Promise((done) => {
      if (chrome.exitCode !== null || chrome.signalCode !== null) { dispose(); done(); return; }
      chrome.once("exit", () => { dispose(); done(); });
      try { chrome.kill(); } catch { dispose(); done(); }
    }),
  };
}

/** A `//` comment containing a backtick inside a page-eval template literal ends the literal and
 *  surfaces as a syntax error in the harness. */
function assertNoStrayBacktick(expression) {
  for (const line of expression.split("\n")) {
    const code = line.trim();
    if (code.startsWith("//") && code.includes("`")) {
      throw new Error(
        "BACKTICK in a page-eval comment terminates the template literal: " + code,
      );
    }
  }
}

/** Evaluate in the page; errors carry the exception's description and the expression, not CDP's
 *  bare "Uncaught". */
export async function evalInPage(send, expression) {
  assertNoStrayBacktick(expression);
  const { result, exceptionDetails } = await send(
    "Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true },
  );
  if (exceptionDetails) {
    const detail =
      exceptionDetails.exception?.description ||
      exceptionDetails.exception?.value ||
      exceptionDetails.text || "";
    throw new Error("page eval threw: " + detail +
      "\n--- expression ---\n" + expression.slice(0, 600));
  }
  return result.value;
}

/**
 * Click like a person: real mouse events at the centre through the input pipeline, so
 * hit-testing applies (`element.click()` passed against a menu under its own click-away
 * overlay — RADD-742). Returns what was hit, with the paint stack.
 */
export async function clickAt(send, selector, match) {
  const box = await evalInPage(send, `(() => {
    const nodes = [...document.querySelectorAll(${JSON.stringify(selector)})];
    const el = ${match ? `nodes.find((n) => (${match.toString()})(n.textContent || ""))` : "nodes[0]"};
    if (!el) return null;
    const target = el.closest("button") || el;
    // Scroll into view first: an off-screen element's centre lands on whatever overlays it.
    target.scrollIntoView({ block: "nearest", inline: "nearest" });
    const r = target.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const top = document.elementFromPoint(x, y);
    const s = getComputedStyle(target);
    return {
      x, y,
      hitIsInsideTarget: target.contains(top),
      hitTag: top ? top.tagName : null,
      rect: { w: r.width, h: r.height },
      style: { opacity: s.opacity, pointerEvents: s.pointerEvents, display: s.display, zIndex: s.zIndex },
      stack: [...document.elementsFromPoint(x, y)].slice(0, 5)
        .map((e) => e.tagName + "." + String(e.className).slice(0, 40)),
    };
  })()`);
  if (!box) throw new Error(`clickAt: nothing matched ${selector}`);
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", { type, x: box.x, y: box.y, button: "left", clickCount: 1 });
  }
  return box;
}

/**
 * Move the pointer over an element so hover-revealed chrome actually appears.
 *
 * A synthesised `mouseover` on the node does not change CSS `:hover` — only a
 * real pointer move does. Aims near the element's TOP edge, because chrome is
 * conventionally there and the pointer must not land on the thing it reveals.
 */
export async function hoverOver(send, selector) {
  const at = await evalInPage(send, `(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + Math.min(12, r.height / 2) };
  })()`);
  if (!at) throw new Error(`hoverOver: nothing matched ${selector}`);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: at.x, y: at.y });
  return at;
}

/** Poll a page expression until it is truthy; returns that value, or the last (falsy) one. */
export async function waitFor(session, expression, { attempts = 60, every = 250 } = {}) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.eval(expression);
    if (value) return value;
    await sleep(every);
  }
  return session.eval(expression);
}

/** Poll a selector until it exists, or give up. Returns whether it appeared. */
export async function waitForSelector(session, selector, { timeoutMs = 20000, stepMs = 250 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = await session.eval(`!!document.querySelector(${JSON.stringify(selector)})`);
    if (found) return true;
    await sleep(stepMs);
  }
  return false;
}

/**
 * Wait for `test` (a function, or a page expression) to hold, or throw `label` with what the page
 * showed. `describe` adds proof-specific context to the failure.
 */
export async function until(session, test, label = "condition", { timeoutMs = 30_000, every = 40, describe } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await (typeof test === "function" ? test() : session.eval(test))) return;
    await sleep(every);
  }
  const page = await session.eval(`location.pathname + " :: " + (document.body?.innerText ?? "").slice(0, 800)`)
    .catch(() => "(page unreadable)");
  const extra = describe ? `\n  ${await describe()}` : "";
  throw new Error(`${label}\n  page: ${page}\n  console: ${JSON.stringify(session.consoleErrors.slice(0, 5))}${extra}`);
}

/** In-page source defining `api(method, path, body)` → `{ status, body }` (parsed JSON or null),
 *  as the signed-in page. Splice it into an eval: `(async () => { ${PAGE_API} return … })()`. */
export const PAGE_API = `const api = async (method, path, body) => {
  const r = await fetch("/api/v1" + path, { method, headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  return { status: r.status, body: text ? JSON.parse(text) : null };
};`;

/** A page expression calling the API as the signed-in page; resolves `{ status, body }` with the
 *  body as raw TEXT (see `parsed`). */
export const pageFetch = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},credentials:"include",` +
  `headers:{"Content-Type":"application/json"}${body === undefined ? "" : `,body:JSON.stringify(${JSON.stringify(body)})`}});` +
  `return {status:r.status, body: await r.text()};})()`;

/** The JSON body of a `pageFetch` result, or null when it failed. */
export const parsed = (result) => (result.status < 300 ? JSON.parse(result.body) : null);

/** Where a proof writes a screenshot or other output: `$RADD_PROOF_OUTPUT_DIR`, else the temp dir
 *  — never the source tree. */
export const outputPath = (name) => resolvePath(process.env.RADD_PROOF_OUTPUT_DIR || tmpdir(), name);

/**
 * Print the checks and return the failure count, so every proof reports alike. `checks` is
 * `{ label: ok }` or `[{ name, ok, detail }]` (a failing entry prints its detail).
 */
export function report(checks, context) {
  if (context) console.log(JSON.stringify(context, null, 2) + "\n");
  const rows = Array.isArray(checks)
    ? checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])
    : Object.entries(checks);
  let failed = 0;
  for (const [label, ok] of rows) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}`);
    if (!ok) failed++;
  }
  console.log(failed ? `\n${failed} FAILED` : "\nall passed");
  return failed;
}

export { sleep };
