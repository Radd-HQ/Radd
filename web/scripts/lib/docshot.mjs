/**
 * Screenshot capture against a RUNNING Radd, for the documentation wave
 * (RADD-1001). Builds on `lib/cdp.mjs`; adds the two things a docs capture
 * needs and a proof does not: a way in without a password, and a guarantee
 * that the browser cannot write.
 *
 * ## Getting in without a password
 *
 * The SPA authenticates with the `radd_session` cookie that `POST /auth/login`
 * sets from an email and password. A PAT cannot be dropped into that cookie —
 * `resolve_session_users` looks the value up as a session row, so a token there
 * resolves to nobody.
 *
 * The way through is already in the server. `auth/deps.py::optional_user`
 * resolves the cookie and THEN falls back to an `Authorization: Bearer
 * radd_pat_…` header. So the unmodified SPA authenticates fine if every
 * same-origin `/api/` request carries that header, which is what the injected
 * wrapper below does. Nothing about the app is stubbed or mocked: it is the
 * real bundle talking to the real API as the real owner.
 *
 * ## Why the gate is here and not in the caller's discipline
 *
 * This browser holds an ADMIN token and points at production, and fan-out
 * agents navigate it. "Do not click Delete" is an instruction, not a safety
 * property, and it fails the first time a capture needs a menu that happens to
 * contain a destructive item.
 *
 * So the same wrapper that adds the header is a write gate: anything to `/api/`
 * that is not a read resolves as a synthetic 403 without touching the network.
 * The hazard is removed by construction. A capture that trips it produces a log
 * line, not a lost row — and the run report names every blocked call, so a
 * panel that failed to render because it needed a write is visible rather than
 * mysterious.
 *
 * `fetch`, `XMLHttpRequest` and `sendBeacon` are all gated. Gating only `fetch`
 * would be the same mistake as trusting the caller: react-query uses `fetch`
 * TODAY, and one upload control on one panel using XHR is enough to defeat it.
 */
import { openBrowser } from "./cdp.mjs";

/** Methods that only read. Everything else to `/api/` is refused. */
const READ_METHODS = ["GET", "HEAD", "OPTIONS"];

/**
 * Read-only endpoints that are POSTs anyway.
 *
 * Started EMPTY on purpose, and populated from evidence: run a capture, read
 * the blocked-call report, and add only the paths that turn out to be reads.
 * Guessing produces an allowlist that is both too wide (a write slips through)
 * and too narrow (a panel stays broken).
 *
 * Both entries below are batch READS that take an id list, which is why they
 * are POSTs — a GET cannot carry the body. They fire on an ordinary board or
 * item page load, so without them every such capture reported blocked writes
 * and lost its rollup and time-tracking chrome.
 */
const READ_ONLY_POSTS = [
  "^/api/v1/items/rollup$",
  "^/api/v1/items/timelog/batch$",
];

/**
 * The page-context gate. Installed with `Page.addScriptToEvaluateOnNewDocument`
 * so it is in place before the bundle boots and survives every navigation.
 *
 * Written as a function and stringified, rather than as a string, so it is
 * syntax-checked by the same tooling as the rest of the file.
 */
function gateSource(token, readMethods, readOnlyPosts) {
  return `(() => {
  const TOKEN = ${JSON.stringify(token)};
  const READ = new Set(${JSON.stringify(readMethods)});
  const ALLOW = ${JSON.stringify(readOnlyPosts)};
  const blocked = [];
  globalThis.__DOCSHOT__ = { blocked, version: 1 };

  const isApi = (url) => {
    try {
      const u = new URL(url, location.href);
      return u.origin === location.origin && u.pathname.startsWith("/api/");
    } catch { return false; }
  };
  const pathOf = (url) => {
    try { return new URL(url, location.href).pathname; } catch { return String(url); }
  };
  const permitted = (method, url) => {
    const m = String(method || "GET").toUpperCase();
    if (READ.has(m)) return true;
    const p = pathOf(url);
    return ALLOW.some((rx) => new RegExp(rx).test(p));
  };
  const refuse = (method, url) => {
    blocked.push({ method: String(method || "GET").toUpperCase(), path: pathOf(url), at: location.pathname });
  };

  // --- fetch -------------------------------------------------------------
  const realFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input, init = {}) => {
    const url = typeof input === "string" ? input : input && input.url ? input.url : String(input);
    const method = (init && init.method) || (input && input.method) || "GET";
    if (!isApi(url)) return realFetch(input, init);
    if (!permitted(method, url)) {
      refuse(method, url);
      return Promise.resolve(new Response(
        JSON.stringify({ detail: "docshot: writes are blocked in a documentation capture" }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ));
    }
    // A Request object carries its own headers; rebuild it rather than mutate.
    if (typeof input !== "string" && input && input.headers) {
      const headers = new Headers(input.headers);
      headers.set("Authorization", "Bearer " + TOKEN);
      return realFetch(new Request(input, { headers }), init);
    }
    const headers = new Headers((init && init.headers) || {});
    headers.set("Authorization", "Bearer " + TOKEN);
    return realFetch(input, { ...init, headers });
  };

  // --- XMLHttpRequest ----------------------------------------------------
  const RealXHR = globalThis.XMLHttpRequest;
  if (RealXHR) {
    const open = RealXHR.prototype.open;
    const send = RealXHR.prototype.send;
    RealXHR.prototype.open = function (method, url, ...rest) {
      this.__docshot = { method, url, api: isApi(url), ok: permitted(method, url) };
      return open.call(this, method, url, ...rest);
    };
    RealXHR.prototype.send = function (...args) {
      const meta = this.__docshot;
      if (meta && meta.api) {
        if (!meta.ok) {
          refuse(meta.method, meta.url);
          // Abort rather than reach the network. The caller sees a failed
          // request, which is the truthful outcome of a blocked write.
          this.abort();
          return;
        }
        this.setRequestHeader("Authorization", "Bearer " + TOKEN);
      }
      return send.apply(this, args);
    };
  }

  // --- sendBeacon --------------------------------------------------------
  if (navigator.sendBeacon) {
    const realBeacon = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = (url, data) => {
      if (isApi(url)) { refuse("POST", url); return false; }
      return realBeacon(url, data);
    };
  }
})();`;
}

/**
 * Suppress motion, caret blink and anything else that makes two captures of the
 * same panel differ. A screenshot taken mid-transition is not a documentation
 * image, and the difference is invisible until the page is published.
 */
const STILLNESS_CSS = `
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    caret-color: transparent !important;
  }
  html { scroll-behavior: auto !important; }
`;

/**
 * Open a browser that is authenticated as the token's owner and cannot write.
 *
 * `theme` and `density` are stamped into localStorage before the bundle boots,
 * so a run is not at the mercy of whatever the profile happened to keep.
 */
export async function openDocsBrowser({
  port,
  profile,
  baseUrl,
  token,
  width = 1600,
  height = 1000,
  scale = 2,
  theme = "dark",
  density = "normal",
}) {
  if (!token) throw new Error("openDocsBrowser needs a PAT (read ~/.radd-token)");
  if (!/^https?:\/\//.test(baseUrl || "")) throw new Error("openDocsBrowser needs an absolute baseUrl");

  const { session, close } = await openBrowser({ port, profile, width, height, scale });

  await session.send("Page.addScriptToEvaluateOnNewDocument", {
    source: gateSource(token, READ_METHODS, READ_ONLY_POSTS),
  });
  await session.send("Page.addScriptToEvaluateOnNewDocument", {
    source:
      `try { localStorage.setItem("radd.theme", ${JSON.stringify(theme)});` +
      ` localStorage.setItem("radd.density", ${JSON.stringify(density)}); } catch {}`,
  });
  // Honour reduced motion at the media-query level too, for the components that
  // ask rather than animate unconditionally.
  await session.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "reduce" }],
  });

  const docs = {
    ...session,
    baseUrl,
    /** Every write the page tried to make. Empty is the expected outcome. */
    blocked: () => session.eval(`(globalThis.__DOCSHOT__ ? globalThis.__DOCSHOT__.blocked : [])`),
    /** Prove the gate is installed — a wrapper that silently failed to attach
     *  would leave the run unauthenticated AND unguarded, and the only symptom
     *  would be login screens in the screenshots. */
    gateInstalled: () => session.eval(`!!(globalThis.__DOCSHOT__ && globalThis.__DOCSHOT__.version === 1)`),
  };

  return { session: docs, close };
}

/** Poll a selector until it exists, or give up. Returns whether it appeared. */
export async function waitForSelector(session, selector, { timeoutMs = 20000, stepMs = 250 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = await session.eval(`!!document.querySelector(${JSON.stringify(selector)})`);
    if (found) return true;
    await new Promise((r) => setTimeout(r, stepMs));
  }
  return false;
}

/** Wait until the page stops issuing requests, so a capture is not half-loaded. */
export async function waitForQuiet(session, { quietMs = 700, timeoutMs = 20000 } = {}) {
  await session.eval(`(() => {
    if (globalThis.__DOCSHOT_NET__) return true;
    const st = { last: Date.now() };
    globalThis.__DOCSHOT_NET__ = st;
    const f = globalThis.fetch;
    globalThis.fetch = (...a) => { st.last = Date.now(); const p = f(...a); p.finally(() => { st.last = Date.now(); }); return p; };
    return true;
  })()`);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const idle = await session.eval(`Date.now() - (globalThis.__DOCSHOT_NET__ ? globalThis.__DOCSHOT_NET__.last : 0)`);
    if (idle >= quietMs) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

/**
 * Capture one image.
 *
 * `clipTo` is the option that matters for documentation: a full-page shot of a
 * settings panel is mostly navigation chrome, and the reader has to hunt for
 * the thing the paragraph is about. Clipping to the panel's own element
 * produces an image that is the subject.
 */
export async function capture(session, { out, clipTo, fullPage = false, padding = 0 }) {
  await session.send("Runtime.evaluate", {
    expression: `(() => {
      let el = document.getElementById("__docshot_stillness");
      if (!el) { el = document.createElement("style"); el.id = "__docshot_stillness"; document.head.appendChild(el); }
      el.textContent = ${JSON.stringify(STILLNESS_CSS)};
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    })()`,
  });

  const params = { format: "png", captureBeyondViewport: fullPage };

  if (clipTo) {
    const box = await session.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(clipTo)});
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height };
    })()`);
    if (!box) throw new Error(`capture: clipTo selector matched nothing: ${clipTo}`);
    if (box.width < 2 || box.height < 2) {
      throw new Error(`capture: ${clipTo} is ${Math.round(box.width)}x${Math.round(box.height)} — nothing to photograph`);
    }
    params.clip = {
      x: Math.max(0, box.x - padding),
      y: Math.max(0, box.y - padding),
      width: box.width + padding * 2,
      height: box.height + padding * 2,
      scale: 1,
    };
    params.captureBeyondViewport = true;
  }

  const { data } = await session.send("Page.captureScreenshot", params);
  const { writeFile, mkdir } = await import("node:fs/promises");
  const { dirname } = await import("node:path");
  await mkdir(dirname(out), { recursive: true });
  const bytes = Buffer.from(data, "base64");
  await writeFile(out, bytes);

  // A clip aimed at an element BELOW THE FOLD captures a blank rectangle: the
  // element has a real bounding box, so nothing errors, the run says "ok", and
  // the file is a solid-colour PNG of the right size. It is the same failure
  // shape as a vacuous test — green, and describing nothing. A flat PNG
  // compresses to almost nothing, so size per pixel catches it cheaply.
  if (clipTo && params.clip) {
    const pixels = params.clip.width * params.clip.height;
    if (pixels > 10000 && bytes.length / pixels < 0.02) {
      throw new Error(
        `capture: ${clipTo} produced a blank image (${bytes.length} bytes for ` +
          `${Math.round(params.clip.width)}x${Math.round(params.clip.height)}). ` +
          `Scroll it into view first with a { "scrollTo": "<selector>" } action.`,
      );
    }
  }
  return out;
}

/** Navigate, settle, and report whether the app actually rendered. */
export async function goto(session, path, { waitFor, quietMs = 700, timeoutMs = 25000 } = {}) {
  const url = path.startsWith("http") ? path : session.baseUrl.replace(/\/$/, "") + path;
  await session.send("Page.navigate", { url });
  // Assert the gate HERE rather than at open time. The injected script runs on
  // document creation, so at `about:blank` it has not run yet and a check there
  // fails on a perfectly good browser. Checking on every navigation is also
  // stronger: it catches a gate that stopped applying part-way through a run,
  // which is the case where writes would actually reach production.
  if (!(await session.eval(`!!(globalThis.__DOCSHOT__ && globalThis.__DOCSHOT__.version === 1)`))) {
    throw new Error(`goto(${path}): the write gate is not installed — refusing to continue`);
  }
  await waitForQuiet(session, { quietMs, timeoutMs });
  if (waitFor) {
    const ok = await waitForSelector(session, waitFor, { timeoutMs });
    if (!ok) throw new Error(`goto(${path}): never saw ${waitFor}`);
  }
  // A capture of the login screen is the classic silent failure: the image is
  // real, the run is green, and every screenshot shows a password box.
  //
  // The test is the ROUTE, not the presence of a password input. "Any password
  // field means logged out" is wrong on the settings pages that legitimately
  // render one — /settings/directory has a bind-account password, /settings/email
  // an SMTP password — and it refused to capture them at all. A writer worked
  // around it by navigating in-app, which is one step from working around the
  // write gate too. A false alarm that trains people to route around the guard
  // is worse than no guard.
  const loggedOut = await session.eval(`location.pathname.startsWith("/login")`);
  if (loggedOut) throw new Error(`goto(${path}): landed on the login screen — the token did not authenticate`);
  return url;
}
