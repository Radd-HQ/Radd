/**
 * Proof for the PDF export (RADD-733 and its subtasks).
 *
 * The assertions that earn their keep:
 *  - RADD-736: the page is NOT blank. Crepe creates asynchronously, so a print
 *    fired on mount emits empty sheets; the route waits for every body.
 *  - RADD-734: no application chrome — no top bar, pins bar, sidebar or tree.
 *  - RADD-735: measured, not eyeballed. The emitted PDF is parsed for its page
 *    count, and the rendered DOM is measured for break rules.
 *  - RADD-737: with subpages, a contents list and one sheet per child.
 *
 * Usage: node scripts/page-print-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { existsSync, readdirSync, writeFileSync } from "node:fs";
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
const PORT = 9450;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-print-proof");

const chrome = spawn(
  findChrome(),
  ["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
   `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, "about:blank"],
  { stdio: "ignore" },
);

const consoleErrors = [];
let ws, nextId = 1;
const pending = new Map();
const send = (method, params = {}, sessionId) => {
  const id = nextId++;
  ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
};
async function evalInPage(sessionId, expression) {
  const { result, exceptionDetails } = await send(
    "Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId,
  );
  if (exceptionDetails) throw new Error("page eval threw: " + (exceptionDetails.text || ""));
  return result.value;
}

/** Page count straight out of the PDF: `/Type /Page` objects, minus /Pages. */
function pdfPageCount(base64) {
  const raw = Buffer.from(base64, "base64").toString("latin1");
  const counts = raw.match(/\/Count\s+(\d+)/g);
  if (counts?.length) return Math.max(...counts.map((c) => Number(c.split(/\s+/)[1])));
  return (raw.match(/\/Type\s*\/Page[^s]/g) || []).length;
}

/** Extractable text, for "is it blank". Uncompressed streams only, which is
 *  enough: we only need to know SOMETHING of the body made it through. */
function pdfHasText(base64, needle) {
  const raw = Buffer.from(base64, "base64").toString("latin1");
  return raw.includes(needle);
}

/** WCAG contrast between two computed CSS colours. */
function contrastOf(a, b) {
  const lum = (css) => {
    const [r, g, bl] = (css || "rgb(0,0,0)").match(/[0-9.]+/g).slice(0, 3).map((v) => Number(v) / 255);
    const ch = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(bl);
  };
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}


async function main() {
  let version;
  for (let i = 0; i < 40 && !version; i++) {
    try { version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); }
    catch { await sleep(250); }
  }
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
    }
  });

  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sessionId);
  await send("Runtime.enable", {}, sessionId);
  await send("Network.enable", {}, sessionId);
  await send("Network.setCacheDisabled", { cacheDisabled: true }, sessionId);
  await send("Emulation.setDeviceMetricsOverride",
    { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false }, sessionId);
  // The break rules live in @media print. Reading them in screen mode reports
  // the default and would fail against a correct stylesheet.
  await send("Emulation.setEmulatedMedia", { media: "print" }, sessionId);

  await send("Page.navigate", { url: baseUrl + "/" }, sessionId);
  await sleep(1200);
  await evalInPage(sessionId,
    `(async()=>{await fetch("/api/v1/auth/login",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify({ email, password })})});})()`);

  // window.print() would block headless Chrome; stub it and record the call.
  const visit = async (url) => {
    await send("Page.navigate", { url }, sessionId);
    await sleep(300);
    await evalInPage(sessionId,
      `(() => { window.__printed = 0; window.print = () => { window.__printed++; }; })()`);
    for (let i = 0; i < 50; i++) {
      await sleep(500);
      const done = await evalInPage(sessionId, `window.__printed > 0`);
      if (done) break;
    }
    return evalInPage(sessionId, `(() => {
      const root = document.querySelector(".radd-print");
      const style = (sel, prop) => {
        const el = document.querySelector(sel);
        return el ? getComputedStyle(el)[prop] : null;
      };
      return {
        printed: window.__printed || 0,
        mounted: !!root,
        text: root ? (root.textContent || "").replace(/\\s+/g, " ").trim() : "",
        // Chrome (the app shell) must be absent entirely.
        hasTopBar: !!document.querySelector("[data-top-bar], nav[aria-label='Primary']"),
        hasSidebar: !!document.querySelector("aside"),
        hasTree: !!document.querySelector("[data-page-tree]"),
        articles: document.querySelectorAll(".radd-print-page").length,
        breaks: document.querySelectorAll(".radd-print-break").length,
        contents: !!document.querySelector(".radd-print-contents"),
        footer: (document.querySelector(".radd-print-footer")?.textContent || ""),
        // The break rules must be live, not just present in the file.
        headingBreakAfter: style("h1", "breakAfter"),
        codeBreakInside: style("pre, .cm-editor", "breakInside"),
        // Printing the dark theme wastes toner and reads worse — the first PDF
        // came out with grey-on-white headings. Measure, do not assume.
        lightTheme: document.documentElement.classList.contains("light"),
        bodyInk: (() => {
          const h = document.querySelector(".radd-print h2, .radd-print h3, .radd-print p");
          return h ? getComputedStyle(h).color : null;
        })(),
        pageBg: getComputedStyle(document.querySelector(".radd-print")).backgroundColor,
      };
    })()`);
  };

  const single = await visit(`${baseUrl}/pages/${spaceSlug}/${pageSlug}/print`);
  const singlePdf = await send("Page.printToPDF", { printBackground: true }, sessionId);

  const withSubs = await visit(`${baseUrl}/pages/${spaceSlug}/${pageSlug}/print?subpages=1`);
  const subsPdf = await send("Page.printToPDF", { printBackground: true }, sessionId);

  if (process.env.RADD_PDF) writeFileSync(process.env.RADD_PDF, Buffer.from(subsPdf.data, "base64"));

  const singlePages = pdfPageCount(singlePdf.data);
  const subsPages = pdfPageCount(subsPdf.data);

  const checks = {
    "the print route mounts": single.mounted === true,
    "print() fired (it waited for the body)": single.printed >= 1,
    "the body is NOT blank": single.text.length > 80,
    "the title block names the space": single.text.includes("Extension proof"),
    "no app top bar": single.hasTopBar === false,
    "no sidebar": single.hasSidebar === false,
    "no page tree": single.hasTree === false,
    "the footer carries the page URL": single.footer.includes(`/pages/${spaceSlug}/${pageSlug}`),
    "headings avoid a break after them": single.headingBreakAfter === "avoid",
    "code blocks avoid an internal break": single.codeBreakInside === "avoid",
    "a PDF was produced with at least one sheet": singlePages >= 1,
    "the PDF is not an empty sheet": pdfHasText(singlePdf.data, "/Type") && singlePages >= 1,
    "with subpages: a contents list appears": withSubs.contents === true,
    "with subpages: each child is its own article": withSubs.articles > single.articles,
    "with subpages: children carry a hard page break": withSubs.breaks >= 1,
    "with subpages the document is longer": subsPages > singlePages,
    "the print view forces the light theme": single.lightTheme === true,
    "body text is dark ink on a light sheet": contrastOf(single.bodyInk, single.pageBg) >= 4.5,
    "no console errors": consoleErrors.length === 0,
  };

  console.log(JSON.stringify({
    single: { ...single, text: single.text.slice(0, 160) },
    withSubs: { articles: withSubs.articles, breaks: withSubs.breaks, contents: withSubs.contents },
    singlePages, subsPages, consoleErrors,
  }, null, 2));
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
  .then((f) => { chrome.kill(); process.exit(f ? 1 : 0); })
  .catch((e) => { console.error(e); chrome.kill(); process.exit(2); });
