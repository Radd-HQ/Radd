/**
 * Browser proof for RADD-1382: Settings → Import → Confluence is the confluenceimport
 * plugin's own remote, against the REAL backend. Read-only: it never saves, checks,
 * downloads or imports — it records every non-GET request the page makes and
 * requires there to be none.
 *
 *   1. the settings sidebar lists "Confluence" under an "Import" group, once;
 *   2. the page's code came from /plugins/confluenceimport/, not the host bundle,
 *      and it renders its title, description and sections with no hub back-link;
 *   3. if the instance holds a saved plan, the plan editor opens on it and every
 *      mapping tab renders (a table, or its empty line) with its destinations;
 *   4. no console errors.
 *
 * Usage: node scripts/confluence-import-page-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9506;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-confluence-page-proof-profile");
const SHOT = resolve(process.env.PROOF_OUT || TMP, "confluence-import-page-proof.png");
const TABS = ["Spaces", "Macros", "People", "Restrictions", "Labels", "Jira links"];

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

async function waitFor(session, expression, attempts = 60) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.eval(expression);
    if (value) return value;
    await sleep(250);
  }
  return session.eval(expression);
}

// Every write the page makes, recorded before any of its code runs.
const RECORD_WRITES = `(() => {
  window.__proofWrites = [];
  const original = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const method = (init.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    if (method !== "GET" && method !== "HEAD") window.__proofWrites.push(method + " " + String(input.url ?? input));
    return original(input, init);
  };
})();`;

const { session, close } = await openBrowser({ port: PORT, profile: PROFILE });
let context = {};
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);
  check("headless chrome reports a real pointer", await session.hoverCapable());
  await session.send("Page.addScriptToEvaluateOnNewDocument", { source: RECORD_WRITES });

  // 1–2. the page and its nav entry.
  await session.navigate(`${baseUrl}/settings/confluence-import`, 1500);
  const mounted = await waitFor(session, `Boolean(document.querySelector("[data-confluence-import]"))`);
  check("the plugin's page mounts at /settings/confluence-import", mounted);
  const nav = await session.eval(`(() => {
    const links = [...document.querySelectorAll('nav[aria-label="Settings sections"] a')];
    const mine = links.filter((a) => a.getAttribute("href") === "/settings/confluence-import");
    const group = mine[0]?.closest("section")?.getAttribute("aria-label") ?? null;
    return { count: mine.length, label: mine[0]?.textContent.trim() ?? null, group };
  })()`);
  check('the sidebar lists "Confluence" under "Import", once',
    nav.count === 1 && nav.label === "Confluence" && nav.group === "Import", JSON.stringify(nav));
  const origin = await session.eval(`(() => ({
    remote: performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/plugins/confluenceimport/")),
  }))()`);
  check("the page's code was loaded from /plugins/confluenceimport/",
    origin.remote.some((name) => name.includes("/plugins/confluenceimport/remoteEntry.js")), JSON.stringify(origin));
  const page = await waitFor(session, `(() => {
    const text = document.body.innerText;
    const outsideNav = [...document.querySelectorAll("a")].filter((a) => !a.closest('nav[aria-label="Settings sections"]'));
    const connections = document.querySelector("[data-confluence-connections]");
    const downloads = document.querySelector("[data-confluence-downloads]");
    if (!connections || !downloads) return null;
    return {
      title: [...document.querySelectorAll("h1, h2")].some((h) => h.textContent.trim() === "Import from Confluence"),
      procedure: text.includes("download spaces or pages once") && text.includes("Review the run report"),
      backLink: outsideNav.some((a) => a.textContent.includes("Import data")),
      connections: connections.textContent.includes("Connections"),
      downloads: downloads.textContent.includes("Downloads"),
      plans: document.querySelectorAll("[data-confluence-plans] li button").length,
      runs: Boolean(document.querySelector("[data-confluence-runs]")),
    };
  })()`);
  context.page = page;
  check("the title and the procedure description render", page?.title && page?.procedure, JSON.stringify(page));
  check('no "← Import data" back-link on the page', page && !page.backLink);
  check("the Connections and Downloads sections render", page?.connections && page?.downloads);

  // 3. a saved plan opens in the editor, read-only.
  if (page?.plans > 0) {
    await session.click("[data-confluence-plans] li button");
    const editor = await waitFor(session, `(() => {
      const root = document.getElementById("confluence-mappings");
      if (!root || !root.querySelector('button[aria-pressed="true"]')) return null;
      return { tabs: [...root.querySelectorAll("button[aria-pressed]")].map((b) => b.textContent.replace(/\\d+$/, "").trim()) };
    })()`);
    check("the plan editor opens on a saved plan", editor && TABS.every((t) => editor.tabs.includes(t)), JSON.stringify(editor));
    const tabs = {};
    for (const tab of TABS) {
      await session.click("#confluence-mappings button[aria-pressed]", new Function("text", `return text.replace(/\\d+$/, "").trim() === ${JSON.stringify(tab)}`));
      tabs[tab] = await waitFor(session, `(() => {
        const root = document.getElementById("confluence-mappings");
        const active = root.querySelector('button[aria-pressed="true"]')?.textContent.replace(/\\d+$/, "").trim();
        if (active !== ${JSON.stringify(tab)}) return null;
        const rows = root.querySelectorAll(":scope > div table tbody tr").length;
        const empty = root.textContent.includes("Nothing of this kind in the download.");
        const loading = root.textContent.includes("Loading choice");
        return rows > 0 || empty ? { rows, empty, loading, actions: root.querySelectorAll(":scope > div table tbody tr td:nth-child(3) button").length } : null;
      })()`, 20);
    }
    context.tabs = tabs;
    check("every mapping tab renders its rows or its empty line", TABS.every((t) => tabs[t]), JSON.stringify(tabs));
    check("each rendered row carries its action control",
      TABS.every((t) => !tabs[t] || tabs[t].rows === 0 || tabs[t].actions === tabs[t].rows), JSON.stringify(tabs));
    check("the Options fieldset renders", await session.eval(`[...document.querySelectorAll("#confluence-mappings legend")].some((l) => l.textContent.trim() === "Options")`));
  } else {
    context.plans = "none on this instance — the plan editor was not exercised";
  }
  await sleep(500);
  await session.screenshot(SHOT, { fullPage: true });

  // 4. nothing was written, nothing complained.
  const writes = await session.eval("window.__proofWrites ?? null");
  check("the proof wrote nothing (no non-GET request)", Array.isArray(writes) && writes.length === 0, JSON.stringify(writes));
  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors));
} finally {
  await close();
}
const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "confluence import page", screenshot: SHOT, ...context },
);
process.exit(failed ? 1 : 0);
