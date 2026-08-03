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
 *   - the callout title must be in an element that is NOT inside a code block;
 *   - no code block anywhere may contain the parameter JSON;
 *   - and, in the other direction, an ordinary ```python block and a ```markdown
 *     block that merely QUOTES a radd fence must both still render as code.
 *
 * Usage: node scripts/page-extensions-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { resolve } from "node:path";
import { chromeArgs, findChrome, HOVER_CAPABLE_PROBE } from "./lib/chrome.mjs";

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);
const PORT = 9447;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-page-ext-proof");

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

/** Runs IN the page. Returns everything the assertions need, in one round trip. */
const PROBE = `(() => {
  const body = document.querySelector('[data-page-body]');
  if (!body) return { mounted: false };
  // A code block is a <pre> only until Crepe's CodeMirror mode finishes loading,
  // after which it is a .cm-editor with no <pre> at all. Asserting on <pre>
  // alone made this proof time-dependent: it passed when it happened to read
  // the page before the swap and failed after. Cover both.
  const CODE = 'pre, .cm-editor, .milkdown-code-block';
  const inPre = (el) => !!el.closest(CODE);
  const texts = (sel) => [...body.querySelectorAll(sel)].map((e) => e.textContent || "");
  const pres = texts(CODE);
  const callout = [...body.querySelectorAll('[data-extension="callout"]')];
  const tocs = [...body.querySelectorAll('[data-extension="toc"]')];
  const toc = tocs[0];
  // The second toc on the proof page carries {"subpages": true} (RADD-710).
  const tocSubpages = tocs[1];
  const children = body.querySelector('[data-extension="children"]');
  const unknown = body.querySelector('[data-extension-unknown]');
  const error = body.querySelector('[data-extension-error]');
  const headings = [...body.querySelectorAll('h1, h2, h3')].map((h) => ({
    tag: h.tagName, id: h.id, text: (h.textContent || "").trim(),
  }));
  return {
    mounted: true,
    codeBlockCount: pres.length,
    viewerCount: body.querySelectorAll(".radd-rich-viewer").length,
    fallbackCount: body.querySelectorAll(".whitespace-pre-wrap").length,
    // Extensions rendered as ELEMENTS, and provably not as source.
    calloutCount: callout.length,
    calloutTitleOutsidePre: callout.some(
      (c) => [...c.querySelectorAll('*')].some((e) => /Careful/.test(e.textContent || "") && !inPre(e)),
    ),
    calloutRendersMarkdown: callout.some((c) => !!c.querySelector('em, i')),
    tocPresent: !!toc,
    tocLinks: toc ? [...toc.querySelectorAll('a[href^="#"]')].map((a) => a.getAttribute('href')) : [],
    tocSubpageLinks: tocSubpages
      ? [...tocSubpages.querySelectorAll('a[href^="/pages/"]')].map((a) => a.textContent || "")
      : [],
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

  await send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${pageSlug}` }, sessionId);

  // Wait for EVERY piece, not just the first one to arrive. CodeMirror blocks
  // mount later than the extension cards, so breaking on "toc is present" left
  // the code-block assertions racing — they passed by luck until a rebuild
  // shifted the timing.
  let probe = { mounted: false };
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    probe = await evalInPage(sessionId, PROBE);
    if (
      probe.mounted &&
      probe.tocPresent &&
      probe.headings.length &&
      probe.childrenPresent &&
      probe.calloutCount === 3 &&
      probe.tocSubpageLinks?.length &&
      probe.pythonStillCode &&
      probe.quotedFenceStillCode
    ) {
      break;
    }
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

  // RADD-715: measure the callout's COMPUTED colours in each theme and compute
  // the contrast here, rather than trusting the values in the stylesheet.
  const CONTRAST = `(() => {
    const lum = (css) => {
      const [r, g, b] = css.match(/[0-9.]+/g).slice(0, 3).map(Number).map((v) => v / 255);
      const ch = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
      return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b);
    };
    const ratio = (a, b) => {
      const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
      return (x + 0.05) / (y + 0.05);
    };
    const out = {};
    for (const el of document.querySelectorAll('[data-callout-kind]')) {
      const panel = getComputedStyle(el);
      const title = el.querySelector("[data-callout-title]");
      if (!title) continue;
      out[el.dataset.calloutKind] = {
        ink: Math.round(ratio(getComputedStyle(title).color, panel.backgroundColor) * 100) / 100,
        border: Math.round(ratio(panel.borderTopColor, getComputedStyle(document.body).backgroundColor) * 100) / 100,
      };
    }
    return out;
  })()`;
  const contrastDark = await evalInPage(sessionId, CONTRAST);
  await evalInPage(sessionId, `document.documentElement.classList.add("light")`);
  await sleep(400);
  const contrastLight = await evalInPage(sessionId, CONTRAST);
  await evalInPage(sessionId, `document.documentElement.classList.remove("light")`);
  await sleep(300);

  const shot = await send("Page.captureScreenshot", { format: "png" }, sessionId);

  // RADD-757: assert the launch flag took. Headless Chrome reports
  // `(hover: none)` by default and Tailwind v4 gates every `hover:`/
  // `group-hover:` utility on `@media (hover: hover)`, so without it this
  // proof silently stops seeing hover-revealed UI at all.
  const hoverCapable = await evalInPage(sessionId, HOVER_CAPABLE_PROBE);
  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "page body mounted": probe.mounted === true,
    // Three callout blocks on the proof page: two valid, one deliberately malformed.
    "every callout block became an element": probe.calloutCount === 3,
    "callout title is NOT inside a code block": probe.calloutTitleOutsidePre === true,
    "callout body renders markdown (<em>)": probe.calloutRendersMarkdown === true,
    "no params JSON leaked into a code block": probe.paramsLeakedIntoCode === false,
    "toc rendered": probe.tocPresent === true,
    "toc has anchor links": (probe.tocLinks?.length ?? 0) >= 3,
    "toc with subpages:true lists the tree beneath it":
      (probe.tocSubpageLinks ?? []).some((t) => t.includes("A child page")),
    "headings carry ids": probe.headings.every((h) => !!h.id),
    "clicking a toc entry jumps to its heading": anchorWorks === true,
    "children extension lists the child page": probe.childrenText.includes("A child page"),
    "unknown extension degrades to a card": probe.unknownPresent === true,
    "malformed params render an error card": probe.errorPresent === true,
    "ordinary python block is still code": probe.pythonStillCode === true,
    "a quoted radd fence is still code": probe.quotedFenceStillCode === true,
    "callout ink clears 4.5:1 in DARK": Object.values(contrastDark).length > 0
      && Object.values(contrastDark).every((c) => c.ink >= 4.5),
    "callout ink clears 4.5:1 in LIGHT": Object.values(contrastLight).length > 0
      && Object.values(contrastLight).every((c) => c.ink >= 4.5),
    "callout border clears 3:1 in both themes":
      [...Object.values(contrastDark), ...Object.values(contrastLight)].every((c) => c.border >= 3),
    "no console errors": consoleErrors.length === 0,
  };

  console.log(JSON.stringify({ probe, anchorWorks, contrastDark, contrastLight, consoleErrors }, null, 2));
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
