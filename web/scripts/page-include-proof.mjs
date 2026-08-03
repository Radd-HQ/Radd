/**
 * Proof for `radd:include` (RADD-716): transclusion renders the source's CURRENT
 * body, edits to the source propagate, and a cycle is refused rather than
 * recursing until the tab dies.
 *
 * The cycle case is why this is a browser proof and not a unit test: the guard
 * lives in the render stack, and "A includes B, B includes A" is only a loop
 * once you are already inside A.
 *
 * Usage: node scripts/page-include-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { resolve } from "node:path";
import { chromeArgs, findChrome, HOVER_CAPABLE_PROBE } from "./lib/chrome.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9449;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-include-proof");

const chrome = spawn(
  findChrome(),
  chromeArgs({ port: PORT, profile: PROFILE }),
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
    { width: 1440, height: 1000, deviceScaleFactor: 2, mobile: false }, sessionId);

  await send("Page.navigate", { url: baseUrl + "/" }, sessionId);
  await sleep(1200);
  await evalInPage(sessionId,
    `(async()=>{await fetch("/api/v1/auth/login",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify({ email, password })})});})()`);

  // Three pages: `fragment` (the shared content), `host` (includes it), and
  // `loop-a` / `loop-b` which include each other.
  const built = await evalInPage(sessionId, `(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const list = async () => (await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json());
    const upsert = async (title, slug, body) => {
      const pages = await list();
      const found = pages.find((p) => p.slug === slug);
      if (found) {
        await fetch("/api/v1/pages/" + found.id, { method: "PATCH", credentials: "include",
          headers: {"Content-Type":"application/json"}, body: JSON.stringify({ body }) });
        return found;
      }
      return await (await fetch("/api/v1/pages", { method: "POST", credentials: "include",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ space_id: space.id, title, slug, body }) })).json();
    };
    const fragment = await upsert("Fragment", "inc-fragment", "ORIGINAL FRAGMENT TEXT");
    const host = await upsert("Host", "inc-host", "Before.\\n\\n\`\`\`radd:include\\n{\\"page\\": \\"inc-fragment\\"}\\n\`\`\`\\n\\nAfter.");
    const a = await upsert("Loop A", "inc-loop-a", "\`\`\`radd:include\\n{\\"page\\": \\"inc-loop-b\\"}\\n\`\`\`");
    const b = await upsert("Loop B", "inc-loop-b", "\`\`\`radd:include\\n{\\"page\\": \\"inc-loop-a\\"}\\n\`\`\`");
    return { fragmentId: fragment.id, hostSlug: host.slug, aSlug: a.slug };
  })()`);

  const readBody = async (slug) => {
    await send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${slug}` }, sessionId);
    for (let i = 0; i < 40; i++) {
      await sleep(500);
      const text = await evalInPage(sessionId,
        `(() => { const b = document.querySelector('[data-page-body]'); return b ? b.textContent : ""; })()`);
      if (text && text.length > 10) return text;
    }
    return "";
  };

  const hostText = await readBody(built.hostSlug);

  // Edit the SOURCE, reload the host: the change must appear.
  await evalInPage(sessionId, `(async () => {
    await fetch("/api/v1/pages/${built.fragmentId}", { method: "PATCH", credentials: "include",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ body: "EDITED FRAGMENT TEXT" }) });
  })()`);
  const hostAfterEdit = await readBody(built.hostSlug);

  // The cycle. If the guard is missing this never settles — so bound it.
  const start = Date.now();
  const loopText = await readBody(built.aSlug);
  const loopMs = Date.now() - start;

  // RADD-757: assert the launch flag took. Headless Chrome reports
  // `(hover: none)` by default and Tailwind v4 gates every `hover:`/
  // `group-hover:` utility on `@media (hover: hover)`, so without it this
  // proof silently stops seeing hover-revealed UI at all.
  const hoverCapable = await evalInPage(sessionId, HOVER_CAPABLE_PROBE);
  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the included body renders inside the host": hostText.includes("ORIGINAL FRAGMENT TEXT"),
    "the host's own content still renders": hostText.includes("Before.") && hostText.includes("After."),
    "the include is labelled with its source": hostText.includes("Included from"),
    "editing the source updates the includer": hostAfterEdit.includes("EDITED FRAGMENT TEXT"),
    "the stale text is gone": !hostAfterEdit.includes("ORIGINAL FRAGMENT TEXT"),
    "a cycle renders a message instead of recursing": /loop forever/i.test(loopText),
    "and it settles quickly": loopMs < 25000,
    "no console errors": consoleErrors.length === 0,
  };

  console.log(JSON.stringify({ hostText: hostText.slice(0, 220), loopText: loopText.slice(0, 220), loopMs, consoleErrors }, null, 2));
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
