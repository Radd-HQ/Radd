/**
 * Render proof for page extensions (RADD-709/710/715), over the DevTools Protocol.
 * Zero npm deps — same pattern as `render-proof.mjs`.
 *
 * Why this script exists at all: page bodies render through Crepe, not
 * react-markdown, and an earlier attempt wired the extension registry into the
 * wrong renderer. Worse, the check written to catch that PASSED on the failure,
 * because it looked for the callout's title text — which also appears verbatim
 * in the unrendered JSON of the block. So every assertion here is written to
 * fail when a block is left as source:
 *
 *   - the callout title must be in an element that is NOT inside a <pre>;
 *   - no <pre> anywhere may contain the parameter JSON;
 *   - and, in the other direction, an ordinary ```python block and a ```markdown
 *     block that merely QUOTES a radd fence must both still be <pre> code.
 *
 * Usage: node scripts/page-extensions-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
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
const PORT = 9447;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-page-ext-proof");

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

/** Runs IN the page. Returns everything the assertions need, in one round trip. */
const PROBE = `(() => {
  const body = document.querySelector('[data-page-body]');
  if (!body) return { mounted: false };
  const inPre = (el) => !!el.closest('pre');
  const texts = (sel) => [...body.querySelectorAll(sel)].map((e) => e.textContent || "");
  const pres = texts('pre');
  const callout = [...body.querySelectorAll('[data-extension="callout"]')];
  const toc = body.querySelector('[data-extension="toc"]');
  const children = body.querySelector('[data-extension="children"]');
  const unknown = body.querySelector('[data-extension-unknown]');
  const error = body.querySelector('[data-extension-error]');
  const headings = [...body.querySelectorAll('h1, h2, h3')].map((h) => ({
    tag: h.tagName, id: h.id, text: (h.textContent || "").trim(),
  }));
  return {
    mounted: true,
    // Extensions rendered as ELEMENTS, and provably not as source.
    calloutCount: callout.length,
    calloutTitleOutsidePre: callout.some(
      (c) => [...c.querySelectorAll('*')].some((e) => /Careful/.test(e.textContent || "") && !inPre(e)),
    ),
    calloutRendersMarkdown: callout.some((c) => !!c.querySelector('em, i')),
    tocPresent: !!toc,
    tocLinks: toc ? [...toc.querySelectorAll('a[href^="#"]')].map((a) => a.getAttribute('href')) : [],
    childrenPresent: !!children,
    childrenText: children ? (children.textContent || "") : "",
    unknownPresent: !!unknown,
    errorPresent: !!error,
    errorText: error ? (error.textContent || "") : "",
    // Params JSON must appear NOWHERE as code. This is the assertion that would
    // have caught the original mistake.
    paramsLeakedIntoCode: pres.some((t) => /"kind"\\s*:\\s*"warning"/.test(t)),
    // The other direction: real code blocks must survive untouched.
    pythonStillCode: pres.some((t) => t.includes('print("still code")')),
    quotedFenceStillCode: pres.some((t) => t.includes('radd:toc')),
    headings,
  };
})()`;

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

  await send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${pageSlug}` }, sessionId);

  let probe = { mounted: false };
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    probe = await evalInPage(sessionId, PROBE);
    if (probe.mounted && probe.tocPresent && probe.headings.length) break;
  }

  // The ToC's first link must actually move the page to its heading.
  let anchorWorks = false;
  if (probe.tocLinks?.length) {
    anchorWorks = await evalInPage(sessionId, `(() => {
      const body = document.querySelector('[data-page-body]');
      const link = body.querySelector('[data-extension="toc"] a[href^="#"]');
      const id = link.getAttribute('href').slice(1);
      const target = document.getElementById(id);
      if (!target) return false;
      link.click();
      return decodeURIComponent(location.hash) === '#' + id;
    })()`);
  }

  const shot = await send("Page.captureScreenshot", { format: "png" }, sessionId);

  const checks = {
    "page body mounted": probe.mounted === true,
    // Three callout blocks on the proof page: two valid, one deliberately malformed.
    "every callout block became an element": probe.calloutCount === 3,
    "callout title is NOT inside a <pre>": probe.calloutTitleOutsidePre === true,
    "callout body renders markdown (<em>)": probe.calloutRendersMarkdown === true,
    "no params JSON leaked into a code block": probe.paramsLeakedIntoCode === false,
    "toc rendered": probe.tocPresent === true,
    "toc has anchor links": (probe.tocLinks?.length ?? 0) >= 3,
    "headings carry ids": probe.headings.every((h) => !!h.id),
    "clicking a toc entry jumps to its heading": anchorWorks === true,
    "children extension lists the child page": probe.childrenText.includes("A child page"),
    "unknown extension degrades to a card": probe.unknownPresent === true,
    "malformed params render an error card": probe.errorPresent === true,
    "ordinary python block is still code": probe.pythonStillCode === true,
    "a quoted radd fence is still code": probe.quotedFenceStillCode === true,
    "no console errors": consoleErrors.length === 0,
  };

  console.log(JSON.stringify({ probe, anchorWorks, consoleErrors }, null, 2));
  console.log("");
  let failed = 0;
  for (const [label, ok] of Object.entries(checks)) {
    console.log(`${ok ? "ok  " : "FAIL"} ${label}`);
    if (!ok) failed++;
  }
  if (process.env.RADD_SHOT) {
    const { writeFileSync } = await import("node:fs");
    writeFileSync(process.env.RADD_SHOT, Buffer.from(shot.data, "base64"));
    console.log(`\nscreenshot -> ${process.env.RADD_SHOT}`);
  }
  console.log(failed ? `\n${failed} FAILED` : "\nall passed");
  return failed;
}

main()
  .then((failed) => { chrome.kill(); process.exit(failed ? 1 : 0); })
  .catch((err) => { console.error(err); chrome.kill(); process.exit(2); });
