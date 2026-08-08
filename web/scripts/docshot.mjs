/**
 * The documentation screenshot CLI (RADD-1001).
 *
 * Two modes:
 *
 *   node scripts/docshot.mjs shoot <manifest.json> [--port N]
 *   node scripts/docshot.mjs probe <route> [--port N] [--json]
 *
 * `shoot` runs a manifest of captures. `probe` dumps a route's landmarks —
 * headings, tabs, buttons, tables and testids — so a writer picks a real
 * selector instead of guessing one and getting an empty clip.
 *
 * Reads the base URL from $RADD_DOCS_URL and the PAT from $RADD_API_TOKEN or
 * ~/.radd-token. Every capture is read-only; see lib/docshot.mjs for why that
 * is a property of the harness rather than of the caller.
 *
 * ## Manifest shape
 *
 * {
 *   "outDir": "…/shots/settings",
 *   "viewport": { "width": 1600, "height": 1000 },   // optional
 *   "shots": [
 *     {
 *       "name": "settings-fields",                    // → <outDir>/<name>.png
 *       "path": "/settings/fields",
 *       "waitFor": "main h1",                         // optional, before actions
 *       "actions": [                                  // optional, in order
 *         { "click": "button:nth-of-type(2)" },
 *         { "waitFor": "[role=dialog]" },
 *         { "hover": ".row" },
 *         { "scrollTo": "#section" },
 *         { "eval": "window.scrollTo(0,0)" },
 *         { "wait": 400 }
 *       ],
 *       "clipTo": "main",                             // element to photograph
 *       "fullPage": false,
 *       "padding": 8
 *     }
 *   ]
 * }
 *
 * A shot that fails does not abort the run: it is reported and the rest carry
 * on, because one bad selector in a manifest of thirty should not cost the
 * other twenty-nine.
 */
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { homedir } from "node:os";
import { openDocsBrowser, capture, goto, waitForSelector } from "./lib/docshot.mjs";

const argv = process.argv.slice(2);
const mode = argv[0];
const target = argv[1];
const flag = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

if (!mode || !target || !["shoot", "probe"].includes(mode)) {
  console.error("usage: docshot.mjs shoot <manifest.json> [--port N]");
  console.error("       docshot.mjs probe <route> [--port N] [--json]");
  process.exit(2);
}

const baseUrl = process.env.RADD_DOCS_URL || "https://project.radd-hq.com";
const token =
  process.env.RADD_API_TOKEN ||
  (await readFile(resolve(homedir(), ".radd-token"), "utf8").catch(() => "")).trim();
if (!token) {
  console.error("no PAT: set $RADD_API_TOKEN or create ~/.radd-token");
  process.exit(2);
}

const port = Number(flag("port", "9480"));
const profile = resolve(process.env.TMPDIR || "/tmp", `radd-docshot-${port}`);

/** Run one manifest action. Kept small and explicit — a mini language here
 *  would be a framework nobody asked for. */
async function runAction(session, action) {
  if (action.wait) return new Promise((r) => setTimeout(r, action.wait));
  if (action.waitFor) {
    const ok = await waitForSelector(session, action.waitFor, { timeoutMs: action.timeoutMs || 15000 });
    if (!ok) throw new Error(`action waitFor: never saw ${action.waitFor}`);
    return;
  }
  if (action.click) return session.click(action.click, action.match);
  if (action.hover) return session.hover(action.hover);
  if (action.scrollTo) {
    return session.eval(
      `(()=>{const e=document.querySelector(${JSON.stringify(action.scrollTo)});` +
        `if(!e) throw new Error("scrollTo matched nothing");` +
        `e.scrollIntoView({block:"center",behavior:"instant"});return true;})()`,
    );
  }
  if (action.eval) return session.eval(action.eval);
  throw new Error(`unknown action: ${JSON.stringify(action)}`);
}

/** What a writer needs to aim a clip, gathered in one page eval. */
const PROBE_EXPRESSION = `(() => {
  const text = (e) => (e.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 90);
  const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1; };
  const take = (sel, limit) => Array.from(document.querySelectorAll(sel)).filter(visible).slice(0, limit);
  const box = (e) => { const r = e.getBoundingClientRect(); return Math.round(r.width) + "x" + Math.round(r.height); };
  return {
    url: location.pathname + location.search,
    title: document.title,
    headings: take("h1,h2,h3", 30).map((e) => e.tagName.toLowerCase() + ": " + text(e)),
    landmarks: take("main,aside,nav,section[aria-label],[role=tabpanel]", 20)
      .map((e) => e.tagName.toLowerCase()
        + (e.getAttribute("aria-label") ? "[aria-label='" + e.getAttribute("aria-label") + "']" : "")
        + " " + box(e)),
    testids: take("[data-testid]", 40).map((e) => "[data-testid='" + e.getAttribute("data-testid") + "'] " + box(e)),
    tabs: take("[role=tab]", 20).map(text),
    buttons: take("button", 40).map(text).filter(Boolean),
    tables: take("table", 10).map((e) => box(e) + " rows=" + e.querySelectorAll("tbody tr").length),
    dialogs: take("[role=dialog]", 5).map((e) => box(e) + " " + text(e).slice(0, 60)),
  };
})()`;

const { session, close } = await openDocsBrowser({
  port,
  profile,
  baseUrl,
  token,
  width: Number(flag("width", "1600")),
  height: Number(flag("height", "1000")),
  theme: flag("theme", "dark"),
});

let failures = 0;
try {
  // The gate is asserted inside every `goto`, where a document actually exists.
  if (mode === "probe") {
    await goto(session, target, { waitFor: "main" });
    const info = await session.eval(PROBE_EXPRESSION);
    if (argv.includes("--json")) {
      console.log(JSON.stringify(info, null, 2));
    } else {
      console.log(`\n${info.url}  —  ${info.title}\n`);
      for (const [key, value] of Object.entries(info)) {
        if (key === "url" || key === "title") continue;
        if (!value.length) continue;
        console.log(`${key}:`);
        for (const row of value) console.log(`  ${row}`);
        console.log("");
      }
    }
  } else {
    const manifest = JSON.parse(await readFile(target, "utf8"));
    const outDir = manifest.outDir || resolve(process.cwd(), "shots");
    for (const shot of manifest.shots) {
      const out = resolve(outDir, `${shot.name}.png`);
      try {
        await goto(session, shot.path, { waitFor: shot.waitFor });
        for (const action of shot.actions || []) await runAction(session, action);
        await capture(session, {
          out,
          clipTo: shot.clipTo,
          fullPage: !!shot.fullPage,
          padding: shot.padding ?? 0,
        });
        const { size } = await (await import("node:fs/promises")).stat(out);
        console.log(`ok    ${shot.name}  ${Math.round(size / 1024)} KB  ${shot.path}`);
      } catch (error) {
        failures++;
        console.log(`FAIL  ${shot.name}  ${shot.path}\n      ${error.message}`);
      }
    }
  }

  // The whole point of the gate is that this list stays empty. A non-empty one
  // is not a crash, so it has to be reported or it is invisible.
  const blocked = await session.blocked();
  if (blocked.length) {
    console.log(`\n${blocked.length} blocked write(s) — a capture tried to change live data:`);
    for (const b of blocked) console.log(`  ${b.method} ${b.path}  (on ${b.at})`);
  }
  const errors = session.consoleErrors.filter((e) => !/favicon|WebSocket|ws:|ResizeObserver/i.test(e));
  if (errors.length) {
    console.log(`\n${errors.length} console error(s):`);
    for (const e of errors.slice(0, 8)) console.log(`  ${e.slice(0, 200)}`);
  }
} finally {
  close();
}

process.exit(failures ? 1 : 0);
