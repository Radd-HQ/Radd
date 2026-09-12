/**
 * README screenshots, taken from the LIVE instance (RADD-1138).
 *
 * The README's gallery has to show the product as it is, not as it was: the
 * wiki's screenshots age, and a picture of a two-releases-old board is a small
 * lie on the front page. So this drives project.radd-hq.com headless, signed
 * in with the owner key, and shoots the RADD project — the public demo, real
 * data, never invented — at 1600×1000 (1×: GitHub renders the README at ~900px, so this is already crisp). Re-run it after a release
 * and commit what changed.
 *
 * Signs in by HEADER: `Network.setExtraHTTPHeaders` puts the bearer token on
 * every request the SPA makes, so no password and no session cookie are
 * involved (the same PAT the tracker skill uses).
 *
 * Usage:
 *   RADD_API_TOKEN=… node scripts/readme-shots.mjs [baseUrl] [outDir]
 *   (defaults: https://project.radd-hq.com, ../docs/media)
 */
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { homedir } from "node:os";
import { openBrowser, sleep } from "./lib/cdp.mjs";

const baseUrl = process.argv[2] || "https://project.radd-hq.com";
const outDir = resolve(process.argv[3] || "../docs/media");
const PORT = 9461;
/** SHOTS_ONLY=ask,palette limits a run to those steps (fast iteration; the
 *  README refresh after a release runs everything). */
const only = new Set((process.env.SHOTS_ONLY || "").split(",").map((x) => x.trim()).filter(Boolean));
const want = (step) => only.size === 0 || only.has(step);
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-readme-shots");

// The RADD project on project.radd-hq.com. Ids rather than names: a renamed
// view should not silently swap what the README shows.
const RADD = {
  board: "9cf529b8-d8d0-4835-b3a9-e35b5477e948",
  list: "25d259ad-0bcc-41cd-b86d-aa968138662a",
  byEpic: "1b1261ac-fd49-449e-8a5a-c724386952cc",
  planning: "b7d2e6b6-6427-4a5a-a7bc-ac54f14decb4",
  roadmap: "388a25f0-a010-48b9-aa61-58bd6a1fa5a6",
  dashboard: "38d7eafd-fd79-4fb0-9be0-765cfd50acf8",
  issue: "RADD-1132",
  page: "radd/the-service-desk",
};

async function token() {
  const env = (process.env.RADD_API_TOKEN || "").trim();
  if (env) return env;
  return (await readFile(resolve(homedir(), ".radd-token"), "utf8")).trim();
}

/** Wait until nothing on the page says it is busy and the DOM has stopped changing. */
async function settle(session, ms = 2500) {
  const deadline = Date.now() + 15000;
  let last = "";
  while (Date.now() < deadline) {
    await sleep(600);
    const state = await session.eval(
      `JSON.stringify({busy: document.querySelectorAll('[aria-busy="true"]').length, n: document.body.querySelectorAll("*").length})`,
    );
    if (state === last && !JSON.parse(state).busy) break;
    last = state;
  }
  await sleep(ms);
}

async function setTheme(session, theme) {
  await session.eval(
    `localStorage.setItem("radd.theme", ${JSON.stringify(theme)}); document.documentElement.classList.toggle("light", ${theme === "light"}); "ok"`,
  );
  await sleep(300);
}

/** A UI screenshot quantises to 256 colours without visible loss and shrinks
 *  about 3×, which matters for a README that loads a dozen of them. Done with
 *  ImageMagick when it is on PATH; otherwise the raw PNG is kept. */
async function optimise(path) {
  const { execFile } = await import("node:child_process");
  await new Promise((done) =>
    execFile("magick", [path, "-dither", "None", "-colors", "256", "-strip", "-define", "png:compression-level=9", path], (err) => {
      if (err) console.log("  (magick not available — raw PNG kept)");
      done();
    }),
  );
}

async function shot(session, name, { theme = "dark" } = {}) {
  await setTheme(session, theme);
  await sleep(400);
  const path = resolve(outDir, `${name}-${theme}.png`);
  await session.screenshot(path);
  await optimise(path);
  console.log(`  ${name}-${theme}.png`);
}

async function main() {
  await mkdir(outDir, { recursive: true });
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1600, height: 1000, scale: 1 });
  await session.send("Network.setExtraHTTPHeaders", { headers: { Authorization: `Bearer ${await token()}` } });
  // The sidebar collapse state and pins are per-viewer; start every run the same.
  await session.navigate(baseUrl + "/login", 1000);
  await session.eval(`localStorage.clear(); "ok"`);

  const go = async (path, ms) => { await session.navigate(baseUrl + path, 500); await settle(session, ms); };

  if (want("home")) {
    console.log("home");
    await go("/", 1500);
    await shot(session, "my-work");
  }

  if (want("board")) {
    console.log("board");
    await go(`/p/RADD/v/${RADD.board}`, 2500);
    await shot(session, "board");
    await shot(session, "board", { theme: "light" });
  }

  if (want("list")) {
    console.log("list by epic");
    await go(`/p/RADD/v/${RADD.byEpic}`, 2500);
    await shot(session, "list");
  }

  if (want("ask")) {
    console.log("ask mode");
    // On the Board: a view's saved filter ANDs with the answer, and both list
    // views carry an `epic.category NOT IN (…)` clause that excludes items with
    // no epic at all — which is most fixed bugs. The board's filter is open.
    await go(`/p/RADD/v/${RADD.board}`, 2500);
    // Switch the query bar to Ask and let the LLM turn a sentence into SLQ.
    await session.click('[aria-label="Query mode"] button', "(t) => t.trim() === 'Ask'");
    await sleep(500);
    await session.eval(`(() => { const i = document.querySelector('input[aria-label="Ask AI for a query"]'); i.focus(); return Boolean(i); })()`);
    await session.send("Input.insertText", { text: "open bugs, highest priority first" });
    await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    // The LLM answers asynchronously; the bar says "Asking…" until the SLQ lands.
    for (let i = 0; i < 45; i++) {
      await sleep(1000);
      const asking = await session.eval(`/Asking…|Asking\\.\\.\\./.test(document.body.textContent || "")`);
      if (!asking && i > 2) break;
    }
    await settle(session, 3000);
    await shot(session, "ask");
  }

  if (want("planning")) {
    console.log("planning");
    await go(`/p/RADD/v/${RADD.planning}`, 2500);
    await shot(session, "planning");
  }

  if (want("roadmap")) {
    console.log("roadmap");
    await go(`/p/RADD/v/${RADD.roadmap}`, 2500);
    await shot(session, "roadmap");
  }

  if (want("issue")) {
    console.log("issue");
    await go(`/issues/${RADD.issue}`, 2500);
    await shot(session, "issue", { theme: "light" });
    await shot(session, "issue");
  }

  if (want("ai")) {
    console.log("ai summary");
    // The description's read-menu is hover-revealed (`hidden group-hover/desc:flex`):
    // hover the description first, or the trigger has no box to click.
    await session.hover(".group\\/desc");
    await sleep(400);
    await session.click('[aria-label="AI actions for the description"]');
    await sleep(500);
    await session.click("li > button", "(t) => t.includes('Summarize issue')");
    // Streamed: wait for the results panel, then for its text to stop growing.
    let lastLen = -1;
    for (let i = 0; i < 60; i++) {
      await sleep(1000);
      const len = await session.eval(`(document.querySelector('aside[aria-label^="AI results"]')?.textContent || "").length`);
      if (len > 200 && len === lastLen) break;
      lastLen = len;
    }
    await sleep(800);
    await shot(session, "ai-summary");
  }

  if (want("timesheet")) {
    console.log("timesheet");
    await go("/timesheet", 2500);
    await shot(session, "timesheet");
  }

  if (want("wiki")) {
    console.log("wiki");
    await go(`/pages/${RADD.page}`, 2500);
    await shot(session, "wiki", { theme: "light" });
  }

  if (want("dashboard")) {
    console.log("dashboard");
    await go(`/dashboards/${RADD.dashboard}`, 3500);
    await shot(session, "dashboard");
  }

  if (want("reports")) {
    console.log("reports");
    await go("/p/RADD/reports", 3500);
    await shot(session, "reports");
  }

  if (want("palette")) {
    console.log("command palette");
    await go("/", 1500);
    await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "k", code: "KeyK", modifiers: 2, windowsVirtualKeyCode: 75 });
    await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "k", code: "KeyK", modifiers: 2, windowsVirtualKeyCode: 75 });
    await sleep(600);
    await session.send("Input.insertText", { text: "release" });
    await settle(session, 1500);
    await shot(session, "palette");
  }

  close();
  console.log(`done → ${outDir}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
