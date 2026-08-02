/**
 * Proof for inline comments (RADD-726 and its subtasks).
 *
 * The four things the issue's done-when actually asks for:
 *   1. commenting on a selection puts a highlight on that sentence and a thread
 *      beside it;
 *   2. the thread stays put when an UNRELATED paragraph elsewhere is edited —
 *      the whole reason the anchor is a quote and not an offset;
 *   3. resolving clears the highlight and the rail entry but leaves it readable;
 *   4. editing the quoted sentence away leaves the comment visible and marked
 *      orphaned, rather than deleted or silently moved.
 *
 * Highlights are painted with the CSS Custom Highlight API, which puts nothing
 * in the DOM — so (1) and (3) are asserted against `CSS.highlights`, not against
 * markup.
 *
 * Usage: node scripts/inline-comments-proof.mjs <baseUrl> <spaceSlug> <email> <password>
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
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-inline-proof");

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

const QUOTE = "The cache is invalidated on write";
const BODY_V1 = `# Design\n\nIntro paragraph that stays put.\n\n${QUOTE} and never on read.\n\nA closing note.\n`;
// An edit ABOVE the anchor: the quoted sentence itself is untouched.
const BODY_V2 = `# Design\n\nIntro paragraph that stays put.\n\nAn entirely new section inserted above.\n\n${QUOTE} and never on read.\n\nA closing note.\n`;
// The quoted sentence rewritten away.
const BODY_V3 = `# Design\n\nIntro paragraph that stays put.\n\nWrites go straight through to storage.\n\nA closing note.\n`;

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
    { width: 1440, height: 1200, deviceScaleFactor: 1, mobile: false }, sessionId);

  await send("Page.navigate", { url: baseUrl + "/" }, sessionId);
  await sleep(1200);
  await evalInPage(sessionId,
    `(async()=>{await fetch("/api/v1/auth/login",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify({ email, password })})});})()`);

  const page = await evalInPage(sessionId, `(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    let row = pages.find((p) => p.slug === "inline-proof");
    if (!row) {
      row = await (await fetch("/api/v1/pages", { method: "POST", credentials: "include",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Inline proof", slug: "inline-proof",
                               body: ${JSON.stringify(BODY_V1)} }) })).json();
    } else {
      await fetch("/api/v1/pages/" + row.id, { method: "PATCH", credentials: "include",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ body: ${JSON.stringify(BODY_V1)} }) });
      // Clear comments left by an earlier run.
      const existing = await (await fetch("/api/v1/page/" + row.id + "/comments", {credentials:"include"})).json();
      for (const c of existing) {
        await fetch("/api/v1/comments/" + c.id, { method: "DELETE", credentials: "include" });
      }
    }
    return { id: row.id, slug: row.slug };
  })()`);

  const openPage = async () => {
    await send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${page.slug}` }, sessionId);
    for (let i = 0; i < 40; i++) {
      await sleep(500);
      const ready = await evalInPage(sessionId,
        `(() => { const b = document.querySelector('[data-page-body]'); return !!b && (b.textContent||"").includes("closing note"); })()`);
      if (ready) return;
    }
    throw new Error("page body never rendered");
  };

  const probe = async () => evalInPage(sessionId, `(() => {
    const rail = document.querySelector('[data-inline-comment-rail]');
    const highlight = CSS.highlights.get("radd-inline-comment");
    return {
      supported: "highlights" in CSS,
      highlighted: highlight ? highlight.size : 0,
      // The text each painted range actually covers — this is what proves the
      // highlight is on the right sentence rather than merely present.
      highlightedText: highlight ? [...highlight].map((r) => r.toString()) : [],
      threads: rail ? rail.querySelectorAll('[data-thread]').length : 0,
      railText: rail ? (rail.textContent || "").replace(/\\s+/g, " ") : "",
      orphanNotice: rail ? /no longer match the page text/.test(rail.textContent || "") : false,
      resolvedToggle: rail ? /Resolved \\(\\d+\\)/.test(rail.textContent || "") : false,
    };
  })()`);

  await openPage();

  // Post the inline comment through the API with an anchor built the same way
  // the selection popover builds one — the UI path for SELECTING text is
  // exercised separately below; this keeps the anchor deterministic.
  await evalInPage(sessionId, `(async () => {
    const body = document.querySelector('[data-page-body]');
    const text = body.textContent;
    const at = text.indexOf(${JSON.stringify(QUOTE)});
    await fetch("/api/v1/page/${page.id}/comments", {
      method: "POST", credentials: "include", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        body: "Is this still true after the rewrite?",
        anchor: { quote: ${JSON.stringify(QUOTE)},
                  prefix: text.slice(Math.max(0, at - 32), at),
                  suffix: text.slice(at + ${QUOTE.length}, at + ${QUOTE.length} + 32) },
      }),
    });
  })()`);

  await openPage();
  const afterPost = await probe();

  // (2) Edit an UNRELATED paragraph above it.
  await evalInPage(sessionId, `(async () => {
    await fetch("/api/v1/pages/${page.id}", { method: "PATCH", credentials: "include",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ body: ${JSON.stringify(BODY_V2)} }) });
  })()`);
  await openPage();
  const afterEditAbove = await probe();

  // (3) Resolve it.
  await evalInPage(sessionId, `(async () => {
    const list = await (await fetch("/api/v1/page/${page.id}/comments", {credentials:"include"})).json();
    await fetch("/api/v1/comments/" + list[0].id + "/resolve", {method:"POST", credentials:"include"});
  })()`);
  await openPage();
  const afterResolve = await probe();

  // Reopen, then (4) edit the quoted sentence away.
  await evalInPage(sessionId, `(async () => {
    const list = await (await fetch("/api/v1/page/${page.id}/comments", {credentials:"include"})).json();
    await fetch("/api/v1/comments/" + list[0].id + "/reopen", {method:"POST", credentials:"include"});
    await fetch("/api/v1/pages/${page.id}", { method: "PATCH", credentials: "include",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ body: ${JSON.stringify(BODY_V3)} }) });
  })()`);
  await openPage();
  const afterOrphan = await probe();

  // RADD-731: selecting text in the body offers a Comment affordance.
  const selection = await evalInPage(sessionId, `(() => {
    const body = document.querySelector('[data-page-body]');
    // Whatever element Crepe rendered that line into — asserting on <p> made
    // this throw rather than fail, which hides the real result.
    const node = [...body.querySelectorAll('*')]
      .filter((e) => (e.textContent || "").includes("closing note"))
      .pop();
    if (!node) return false;
    const range = document.createRange();
    range.selectNodeContents(node);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    return true;
  })()`);
  await sleep(500);
  const popover = await evalInPage(sessionId,
    `!![...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Comment")`);

  const checks = {
    "the highlight API is available": afterPost.supported === true,
    "commenting highlights the quoted sentence": afterPost.highlighted === 1,
    "and the highlight covers the right words":
      (afterPost.highlightedText[0] || "").includes(QUOTE),
    "a thread appears beside it": afterPost.railText.includes("Is this still true"),
    // The reason the anchor is a quote and not an offset.
    "an edit ABOVE leaves it anchored": afterEditAbove.highlighted === 1,
    "still on the same sentence":
      (afterEditAbove.highlightedText[0] || "").includes(QUOTE),
    "resolving clears the highlight": afterResolve.highlighted === 0,
    "and leaves it readable behind a toggle": afterResolve.resolvedToggle === true,
    "editing the sentence away does not delete the comment":
      afterOrphan.railText.includes("Is this still true"),
    "the orphan is not re-anchored somewhere else": afterOrphan.highlighted === 0,
    "and it is marked as orphaned": afterOrphan.orphanNotice === true,
    "selecting text offers a Comment affordance": selection && popover === true,
    "no console errors": consoleErrors.length === 0,
  };

  console.log(JSON.stringify({ afterPost, afterEditAbove, afterResolve, afterOrphan, popover, consoleErrors }, null, 2));
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
