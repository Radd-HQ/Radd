/**
 * The Chrome DevTools Protocol plumbing every proof in this directory repeats
 * (RADD-757).
 *
 * These are not conveniences. Each function encodes a lesson that was paid for
 * once and then had to be copied by hand into the next proof — which is how
 * RADD-742's hit-testing fix ended up in one script while the others kept
 * calling `element.click()`. One module, so a lesson learned in the seventh
 * proof applies to the first.
 */
import { spawn } from "node:child_process";
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
export async function openBrowser({ port, profile, width = 1440, height = 1000, scale = 2 }) {
  // A browser already listening on this port is a LEFTOVER from a previous run,
  // and connecting to it is silent poison: it was launched from different code,
  // possibly with different flags, and every assertion then describes a browser
  // this run did not configure. It cost an hour once — a proof reported
  // `(hover: hover)` false while the flag that sets it was right there in the
  // launch arguments, because the flag went to a process nobody connected to.
  // Fail loudly instead of inheriting it.
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
  // The harness owns the browser's life, not the caller. A proof that throws
  // before its own cleanup used to leak a headless Chrome per run, and every
  // proof had to remember the same two `chrome.kill()` calls in its tail.
  process.on("exit", () => { try { chrome.kill(); } catch { /* already gone */ } });

  // 60 s, not 10 (RADD-1135): a FIRST launch of Google Chrome on a cold GitHub
  // runner — profile creation, font cache, sandbox setup, under load from a
  // sibling job — overran the old 40 x 250 ms budget twice in one day, on
  // commits whose identical smoke passed minutes later. Locally this loop exits
  // on the first successful poll, typically well under a second, so the budget
  // only ever costs time when something is actually wrong.
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
  await send("Emulation.setDeviceMetricsOverride",
    { width, height, deviceScaleFactor: scale, mobile: false });

  const session = {
    send,
    consoleErrors,
    sessionId,
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
  };

  return { session, close: () => chrome.kill() };
}

/**
 * Evaluate an expression in the page and return its value.
 *
 * The error path matters: CDP's `exceptionDetails.text` is usually the useless
 * string "Uncaught". Reporting the exception's own description plus the
 * expression that produced it is the difference between "page eval threw" and
 * knowing which selector came back null.
 */
/**
 * Page-eval expressions are built as TEMPLATE LITERALS, so a backtick anywhere
 * inside one — most easily in a comment, writing `foo` for emphasis — closes
 * the literal early. The result is a syntax error reported against the HARNESS
 * at some unrelated line, which reads as "my proof file is broken" rather than
 * "I typed a backtick". It cost two debugging rounds in one session, so the
 * check is here rather than in anybody's memory.
 */
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
 * Click an element the way a person does: real mouse events at its centre,
 * dispatched through the browser's input pipeline so HIT-TESTING applies.
 *
 * This is the whole reason proofs are written this way (RADD-742). The first
 * version called `element.click()`, which delivers the event straight to the
 * node and ignores what is painted on top of it. That passed against a menu
 * sitting UNDER its own click-away overlay — a real click closed the menu and
 * inserted nothing, and the proof said "all passed". `element.click()` cannot
 * see a z-index bug; `Input.dispatchMouseEvent` can.
 *
 * Returns what was actually hit, including the full paint stack, so a
 * mis-targeted click reports "intercepted by X" rather than "did nothing".
 */
export async function clickAt(send, selector, match) {
  const box = await evalInPage(send, `(() => {
    const nodes = [...document.querySelectorAll(${JSON.stringify(selector)})];
    const el = ${match ? `nodes.find((n) => (${match.toString()})(n.textContent || ""))` : "nodes[0]"};
    if (!el) return null;
    const target = el.closest("button") || el;
    // Scroll it into view first, as a person would. An element inside a scrolling
    // container still reports a rect when it is below the fold, so clicking its
    // centre lands wherever that point happens to be — usually on a click-away
    // overlay, which then reads as the z-index bug of RADD-742 rather than as
    // "the list scrolled". The extension picker's max-h-80 list hit exactly this
    // once it grew past four entries.
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

/** Print the checks and return the failure count, so every proof reports alike. */
export function report(checks, context) {
  if (context) console.log(JSON.stringify(context, null, 2) + "\n");
  let failed = 0;
  for (const [label, ok] of Object.entries(checks)) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}`);
    if (!ok) failed++;
  }
  console.log(failed ? `\n${failed} FAILED` : "\nall passed");
  return failed;
}

export { sleep };
