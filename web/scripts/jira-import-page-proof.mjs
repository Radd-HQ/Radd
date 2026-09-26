/**
 * Browser proof for RADD-1382: Settings → Import → Jira is the jiraimport
 * plugin's own remote, and the host's Import data hub is gone — against the
 * REAL backend and whatever the dev database already holds.
 *
 *   1. the settings sidebar has an "Import" group (after Server) holding "Jira",
 *      and no "Import data" entry;
 *   2. /settings/import-data renders the catch-all's "unavailable" notice, not a hub;
 *   3. /settings/jira-import is rendered by /plugins/jiraimport/remoteEntry.js,
 *      carries the procedure line and no back-link, and shows its connections,
 *      downloads, plans and runs;
 *   4. when a saved plan exists, its editor opens and three mapping tables render.
 *
 * READ-ONLY: it never saves a plan, starts a download or a run, or touches a
 * connection — a fetch wrapper records every non-GET request and the proof
 * fails if one reaches /jira/.
 *
 * Usage: node scripts/jira-import-page-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { openBrowser, outputPath, report, waitFor } from "./lib/cdp.mjs";
import { proofArgs } from "./lib/proof.mjs";

const { baseUrl, email, password } = proofArgs();
const SHOT = outputPath("jira-import-page-proof.png");
const PROCEDURE = "Connect your source → download once → review mappings → check and dry run → import.";

let writes = [];

// Every non-GET the page sends, recorded before any app code runs and kept in
// sessionStorage so the record survives the proof's full-page navigations.
const RECORD_WRITES = `(() => {
  const original = window.fetch;
  window.fetch = (input, init = {}) => {
    const method = (init.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    if (method !== "GET") {
      const seen = JSON.parse(sessionStorage.getItem("__writes") || "[]");
      seen.push(method + " " + (input instanceof Request ? input.url : String(input)));
      sessionStorage.setItem("__writes", JSON.stringify(seen));
    }
    return original(input, init);
  };
})();`;

const NAV = `[...document.querySelectorAll('nav[aria-label="Settings sections"] section')]`;

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

const { session, close } = await openBrowser({
  port: 9505, profile: resolve(process.env.TMPDIR || "/tmp", "radd-jira-import-proof-profile"),
});
let data = null;
try {
  await session.send("Page.addScriptToEvaluateOnNewDocument", { source: RECORD_WRITES });
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);
  check("the browser reports hover capability", await session.hoverCapable());

  // What the dev database holds, read through the same API the page uses.
  data = await session.eval(`(async () => {
    const get = async (p) => (await fetch("/api/v1" + p)).json();
    const [connections, snapshots, plans, runs] = await Promise.all(
      ["/jira/connections", "/jira/snapshots", "/jira/plans", "/jira/runs"].map(get));
    return { connections: connections.map((c) => c.name), snapshots: snapshots.map((s) => s.name),
      plans: plans.map((p) => ({ id: p.id, name: p.name })), runs: runs.length };
  })()`);

  // 1. the sidebar.
  await session.navigate(`${baseUrl}/settings/jira-import`, 1500);
  const nav = await waitFor(session, `(() => {
    const groups = ${NAV}.map((s) => ({ label: s.getAttribute("aria-label"),
      links: [...s.querySelectorAll("a")].map((a) => ({ text: a.textContent.trim(), href: a.getAttribute("href") })) }));
    return groups.some((g) => g.label === "Import") ? groups : null;
  })()`);
  const labels = (nav ?? []).map((g) => g.label);
  const importGroup = (nav ?? []).find((g) => g.label === "Import");
  check("the sidebar has an Import group holding Jira → /settings/jira-import",
    importGroup?.links.some((l) => l.text === "Jira" && l.href === "/settings/jira-import"), JSON.stringify(importGroup));
  check("the Import group comes after Server", labels.indexOf("Import") > labels.indexOf("Server") && labels.includes("Server"),
    JSON.stringify(labels));
  check("no sidebar entry is called Import data",
    !(nav ?? []).some((g) => g.links.some((l) => l.text === "Import data" || l.href === "/settings/import-data")));

  // 3. the page, from the remote.
  const page = await waitFor(session, `(() => {
    const root = document.querySelector("[data-jira-import]");
    if (!root) return null;
    const sections = [...root.querySelectorAll("[data-jira-section]")].map((s) => s.dataset.jiraSection);
    return { sections, text: document.querySelector("main")?.innerText ?? document.body.innerText,
      remote: performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/plugins/jiraimport/")),
      backLink: [...document.querySelectorAll("a")].some((a) => a.textContent.includes("Import data")) };
  })()`);
  check("the page is rendered by the jiraimport remote", page?.remote?.some((n) => n.includes("/plugins/jiraimport/remoteEntry.js")),
    JSON.stringify(page?.remote));
  check("connections, downloads, plans and runs render",
    ["connections", "downloads", "plans", "runs"].every((s) => page?.sections?.includes(s)), JSON.stringify(page?.sections));
  check("the description carries the import procedure", page?.text?.includes(PROCEDURE));
  check("there is no back-link to an Import data hub", page && !page.backLink);
  const rows = await waitFor(session, `(() => {
    const text = (s) => document.querySelector('[data-jira-section="' + s + '"]')?.innerText ?? "";
    const ok = ${JSON.stringify(data.connections)}.every((n) => text("connections").includes(n))
      && ${JSON.stringify(data.plans.map((p) => p.name))}.every((n) => text("plans").includes(n))
      && ${JSON.stringify(data.snapshots)}.every((n) => text("downloads").includes(n));
    const runs = document.querySelectorAll('[data-jira-section="runs"] tbody > tr').length;
    return ok && runs >= Math.min(1, ${data.runs}) ? { runs } : null;
  })()`);
  check(`every connection (${data.connections.length}), download (${data.snapshots.length}) and plan (${data.plans.length}) is listed, and runs render`,
    Boolean(rows), JSON.stringify({ data, rows }));

  // 4. a saved plan opens in the editor (look only — nothing is saved).
  if (data.plans.length > 0) {
    const plan = data.plans[0];
    await session.click('[data-jira-section="plans"] button', new Function("text", `return text.trim() === ${JSON.stringify(plan.name)}`));
    const editor = await waitFor(session, `(() => {
      const section = document.querySelector('[data-jira-section="mappings"]');
      const tabs = section ? [...section.querySelectorAll('[aria-label="Mapping tables"] button')] : [];
      return tabs.length ? { tabs: tabs.map((t) => t.firstChild?.textContent), pressed: tabs.find((t) => t.getAttribute("aria-pressed") === "true")?.firstChild?.textContent,
        text: section.innerText } : null;
    })()`);
    check(`plan "${plan.name}" opens with its nine mapping tabs`, editor?.tabs?.length === 9, JSON.stringify(editor?.tabs));
    check("the Fields table renders its bands", editor?.pressed === "Fields"
      && /Fields with data|Unused|Not worth mapping|Handled natively/.test(editor.text), editor?.text?.slice(0, 300));
    for (const [tab, marker] of [["Statuses", /Statuses in use|Not used by this project/], ["People", /Needs a decision|Already matched|Nobody is referenced/]]) {
      await session.click('[aria-label="Mapping tables"] button', new Function("text", `return text.startsWith(${JSON.stringify(tab)})`));
      const shown = await waitFor(session, `(() => { const t = document.querySelector('[data-jira-section="mappings"]')?.innerText ?? "";
        return ${marker}.test(t) ? t.slice(0, 200) : null; })()`, { attempts: 20 });
      check(`the ${tab} table renders`, Boolean(shown));
    }
    await session.screenshot(SHOT);
  } else {
    check("a saved plan exists to open (none on this database — editor not exercised)", true);
  }

  // 2. the hub is gone.
  await session.navigate(`${baseUrl}/settings/import-data`, 1500);
  const hub = await waitFor(session, `(() => {
    const text = document.body.innerText;
    return document.querySelector('[data-plugin-missing="page"]') || text.includes("Open Jira importer") ? { missing: Boolean(document.querySelector('[data-plugin-missing="page"]')),
      hub: text.includes("Open Jira importer") || text.includes("Bring existing work and documentation into Radd.") } : null;
  })()`);
  check("/settings/import-data renders no hub, only the unavailable notice", hub?.missing && !hub.hub, JSON.stringify(hub));

  writes = await session.eval(`JSON.parse(sessionStorage.getItem("__writes") || "[]")`);
  // Not vacuous: the same recorder saw the sign-in POST.
  check("the write recorder saw the sign-in", writes.some((w) => w.includes("/auth/login")), JSON.stringify(writes));
  check("nothing was written to the importer", !writes.some((w) => w.includes("/jira/")), JSON.stringify(writes));
  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors));
} finally {
  await close();
}
const failed = report(checks, { proof: "jira import page", data, writes, screenshot: SHOT });
process.exit(failed ? 1 : 0);
