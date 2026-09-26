/**
 * Screenshot capture against a RUNNING Radd for documentation (RADD-1001), on lib/cdp.mjs.
 * Two things a proof does not need:
 *  - Auth without a password: a PAT cannot go in `radd_session` (looked up as a session row),
 *    but `auth/deps.py::optional_user` accepts `Authorization: Bearer radd_pat_…`, so an
 *    injected wrapper adds that header to every same-origin `/api/` call.
 *  - A write gate by construction: this browser holds an ADMIN token against production, so the
 *    same wrapper answers every non-read `/api/` call with a synthetic 403 and records it.
 *    `fetch`, XHR and `sendBeacon` are all gated — one XHR upload control defeats a fetch-only gate.
 */
import { openBrowser, waitForSelector } from "./cdp.mjs";

/** Methods that only read. Everything else to `/api/` is refused. */
const READ_METHODS = ["GET", "HEAD", "OPTIONS"];

/** Read-only POSTs (batch reads that carry an id list). Grown only from the blocked-call
 *  report, never guessed; both fire on an ordinary board/item load. */
const READ_ONLY_POSTS = [
  "^/api/v1/items/rollup$",
  "^/api/v1/items/timelog/batch$",
];

/** Installed with addScriptToEvaluateOnNewDocument (before the bundle, every navigation);
 *  stringified from a function so it is syntax-checked. */
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
  // Checked per navigation, not at open (about:blank predates the injected script) — this also
  // catches a gate that stops applying mid-run.
  if (!(await session.gateInstalled())) {
    throw new Error(`goto(${path}): the write gate is not installed — refusing to continue`);
  }
  await waitForQuiet(session, { quietMs, timeoutMs });
  if (waitFor) {
    const ok = await waitForSelector(session, waitFor, { timeoutMs });
    if (!ok) throw new Error(`goto(${path}): never saw ${waitFor}`);
  }
  // Logged out = on the /login ROUTE, not "a password input exists": /settings/directory and
  // /settings/email render real password fields, and that false alarm taught writers to route
  // around the guard.
  const loggedOut = await session.eval(`location.pathname.startsWith("/login")`);
  if (loggedOut) throw new Error(`goto(${path}): landed on the login screen — the token did not authenticate`);
  return url;
}
