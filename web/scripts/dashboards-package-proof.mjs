/**
 * Browser proof for RADD-1393 against the REAL backend: Dashboards is a core plugin whose UI is the
 * bundled dashboards package, and "Awaiting my approval" is the approvals remote's contribution.
 *
 *   1. /capabilities: dashboards is loaded with no remote (bundled); approvals contributes a
 *      PERSONAL widget type and ships a remote;
 *   2. a throwaway project whose issue awaits MY approval: My Work's suggested layout gains
 *      "Awaiting my approval" (approvals' `suggest`), the package canvas renders every widget, and
 *      the approvals remote (/plugins/approvals/) draws the row — its key links to the issue and a
 *      click opens it in the peek panel (the SDK's ItemKeyLink/ItemPeek bridges);
 *   3. My Work's Add widget offers the personal type; Customize → Cancel saves nothing;
 *   4. a throwaway dashboard is created from the sidebar, which lists it; it gets an Issue count
 *      widget through Customize → Add widget → Save, renders the same total as GET /items/count,
 *      does NOT offer the personal approvals type, draws a host report card at the plot height
 *      its widget grants, and is deleted from its page;
 *   5. no host chunk carries the dashboard components: web/src has none, and every built chunk
 *      holding the package's copy is named after a package module;
 *   6. no console errors; the project is deleted and My Work reads byte-for-byte as before (the
 *      person's layout is never written).
 *
 * Usage (from web/): node scripts/dashboards-package-proof.mjs <baseUrl> [email] [password]
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9513;
const TMP = process.env.TMPDIR || "/tmp";
const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PACKAGE = resolve(WEB, "../server/src/radd/modules/dashboards/ui/src");
const NAME = `Package proof ${Date.now().toString(36)}`;
const KEY = `DP${Date.now().toString(36).slice(-4).toUpperCase()}`;

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

async function waitFor(session, expression, attempts = 80) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.eval(expression);
    if (value) return value;
    await sleep(250);
  }
  return session.eval(expression);
}

const API = `const api = async (method, path, body) => { const r = await fetch("/api/v1" + path, { method,
  headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text(); return { status: r.status, body: text ? JSON.parse(text) : null, text }; };`;
const call = (session, method, path, body) =>
  session.eval(`(async () => { ${API} return api(${JSON.stringify(method)}, ${JSON.stringify(path)}, ${JSON.stringify(body)}); })()`);
const button = (text, within = "") => `[...document.querySelectorAll(${JSON.stringify(`${within} button`)})]
  .find((b) => b.textContent.trim() === ${JSON.stringify(text)} && !b.disabled)`;
async function clickButton(session, text, within = "") {
  const found = await waitFor(session, `Boolean(${button(text, within)})`);
  if (!found) throw new Error(`no enabled button "${text}" ${within}`);
  await session.eval(`${button(text, within)}.click()`);
}
/** Open the dialog's Type picker and read its options (the house Select, not a native one). */
async function typeOptions(session) {
  await session.click('[role="dialog"] button[aria-haspopup="listbox"]');
  const options = await waitFor(session, `(() => { const o = [...document.querySelectorAll('[role="option"]')].map((e) => e.textContent.trim()); return o.length ? o : null; })()`);
  return options ?? [];
}

const { session, close } = await openBrowser({ port: PORT, profile: resolve(TMP, "radd-dashboards-package-proof") });
let dashboardId = null;
let before = null;
let fixture = null;
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, String(status));

  // 1. The manifest.
  const caps = (await call(session, "GET", "/capabilities")).body;
  const awaiting = caps.widget_types.find((t) => t.key === "approvals");
  check("dashboards is loaded and bundled (no remote)", caps.plugins.includes("dashboards") && !caps.remotes.some((r) => r.name === "dashboards"),
    JSON.stringify(caps.remotes.map((r) => r.name)));
  check("approvals contributes a PERSONAL widget type, labelled", awaiting?.personal === true && awaiting.label === "Awaiting my approval", JSON.stringify(awaiting));
  check("approvals' UI is a remote under /plugins/approvals/", caps.remotes.some((r) => r.name === "approvals" && r.remote_entry.startsWith("/plugins/approvals/")));

  // 2. Something awaits MY approval: My Work suggests the widget, and the remote draws it.
  before = await call(session, "GET", "/dashboards/my-work/widgets");
  fixture = await session.eval(`(async () => { ${API}
    const me = (await api("GET", "/auth/me")).body;
    const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Dashboards package proof" });
    const id = project.body.id;
    const mode = await api("PUT", "/scoped-settings", { scope: "project", scope_id: id, key: "workflow_transition_mode", value: "guards" });
    const done = (await api("GET", "/states?project_id=" + id)).body.find((s) => s.name === "Done");
    const transition = await api("POST", "/transitions", { project_id: id, from_state_id: null, to_state_id: done.id,
      rules: [{ check: "require_approval", params: { approvers: [{ kind: "user", id: me.id }] } }] });
    const item = await api("POST", "/items", { project_id: id, title: "Decide on the package move" });
    const request = await api("POST", "/items/" + item.body.id + "/approvals", { to_state_id: done.id });
    return { projectId: id, key: item.body.key, status: [project.status, mode.status, transition.status, item.status, request.status] }; })()`);
  check("a throwaway project whose issue awaits MY approval", fixture.status.join() === "201,200,201,201,201", JSON.stringify(fixture.status));
  const suggested = await call(session, "GET", "/dashboards/my-work/widgets");
  // A person who saved their own layout gets no suggestions; then the widget goes on the draft.
  const savedLayout = suggested.text === before.text;
  check(savedLayout ? "My Work is a saved layout (suggestions do not apply)" : "the pending approval puts the widget on the suggested layout",
    savedLayout || suggested.body.some((w) => w.widget_type === "approvals" && w.title === "Awaiting my approval"), suggested.text.slice(0, 300));
  const layout = suggested.body.map((w) => w.id);
  await session.navigate(`${baseUrl}/`, 500);
  const rendered = await waitFor(session, `(() => { const ids = [...document.querySelectorAll(".widget-grid [data-widget-id]")].map((e) => e.dataset.widgetId);
    return ids.length === ${layout.length} ? ids : null; })()`);
  check("My Work renders every widget of the layout on the package canvas", JSON.stringify(rendered) === JSON.stringify(layout), `${JSON.stringify(rendered)} vs ${JSON.stringify(layout)}`);
  await clickButton(session, "Customize");
  await clickButton(session, "Add widget");
  const personalOptions = await typeOptions(session);
  check("My Work's picker offers the contributed personal type", personalOptions.includes("Awaiting my approval"), JSON.stringify(personalOptions));
  if (savedLayout) {
    await session.click('[role="option"]', (text) => text.trim() === "Awaiting my approval");
    await clickButton(session, "Add widget", '[role="dialog"]');
  } else {
    await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape" });
    await clickButton(session, "Cancel", '[role="dialog"]');
    await clickButton(session, "Cancel");
  }
  const row = `document.querySelector('.widget-grid [data-widget-type="approvals"] [data-approvals-awaiting]')`;
  const drawn = await waitFor(session, `(() => { const s = ${row}; if (!s) return null;
    const link = s.querySelector('a[href="/issues/${fixture.key}"]'); return link ? { text: s.textContent.slice(0, 120), link: link.textContent } : null; })()`);
  const loaded = await session.eval(`performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/plugins/approvals/"))`);
  check("the approvals remote draws the pending request, its key linking to the issue", drawn?.link === fixture.key, JSON.stringify(drawn));
  check("…fetched from /plugins/approvals/", loaded.some((n) => n.includes("/plugins/approvals/remoteEntry.js")), JSON.stringify(loaded));
  await session.click(`.widget-grid [data-widget-type="approvals"] [data-approvals-awaiting] [role="button"]`);
  const peeked = await waitFor(session, `new URLSearchParams(location.search).get("peek") === ${JSON.stringify(fixture.key)}`);
  check("a click opens the issue in the peek panel", peeked, await session.eval("location.search"));
  if (savedLayout) await clickButton(session, "Cancel");
  const untouched = await call(session, "GET", "/dashboards/my-work/widgets");
  check("Customize → Cancel saves nothing", untouched.text === suggested.text);
  await session.navigate(`${baseUrl}/`, 500);

  // 4. A throwaway dashboard: sidebar → create → widget → render → delete.
  if (!(await session.eval(`Boolean(${button("New dashboard", "aside")})`))) {
    await session.eval(`document.querySelector('aside button[aria-label="Expand Dashboards"]')?.click()`);
  }
  await clickButton(session, "New dashboard", "aside");
  await waitFor(session, `Boolean(document.querySelector('[role="dialog"] input'))`);
  await session.click('[role="dialog"] input');
  await session.send("Input.insertText", { text: NAME });
  await clickButton(session, "Create dashboard", '[role="dialog"]');
  dashboardId = await waitFor(session, `(location.pathname.match(/^\\/dashboards\\/([0-9a-f-]{36})$/) || [])[1] || null`);
  check("New dashboard opens the fresh dashboard", dashboardId, await session.eval("location.pathname"));
  const listed = await waitFor(session, `[...document.querySelectorAll('aside a[href="/dashboards/${dashboardId}"]')].some((a) => a.textContent.includes(${JSON.stringify(NAME)}))`);
  check("the sidebar lists it", listed);
  check("the page is the package's", await waitFor(session, `document.querySelector("[data-dashboard-page]")?.dataset.dashboardPage === ${JSON.stringify(dashboardId)}`));
  await clickButton(session, "Customize");
  await clickButton(session, "Add widget");
  const sharedOptions = await typeOptions(session);
  check("a shared dashboard does not offer the personal type", sharedOptions.includes("Issue count (SLQ)") && !sharedOptions.includes("Awaiting my approval"), JSON.stringify(sharedOptions));
  await session.click('[role="option"]', (text) => text.trim() === "Issue count (SLQ)");
  await clickButton(session, "Add widget", '[role="dialog"]');
  await waitFor(session, `!document.querySelector('[role="dialog"]')`);
  await clickButton(session, "Save");
  const saved = await waitFor(session, `(async () => { ${API} const d = await api("GET", "/dashboards/${dashboardId}");
    return d.body?.widgets?.length === 1 ? d.body.widgets[0] : null; })()`);
  check("the widget is saved", saved?.widget_type === "slq_count", JSON.stringify(saved));
  const total = (await call(session, "GET", "/items/count")).body.total;
  const shown = await waitFor(session, `(() => { const n = document.querySelector('.widget-grid [data-widget-type="slq_count"] p.text-3xl')?.textContent.trim();
    return n && n !== "…" ? n : null; })()`);
  check("it renders the same total as GET /items/count", shown === String(total), `${shown} vs ${total}`);
  // A report widget: the host's report card through the SDK bridge, sized by the package's grid
  // through the SDK's chart-height context (460px widget → 280px plot; the charts default to 200/220).
  // A project with something done in the window, so there IS a plot to measure.
  const project = await session.eval(`(async () => { ${API}
    const end = new Date().toISOString().slice(0, 10), start = new Date(Date.now() - 56 * 864e5).toISOString().slice(0, 10);
    const projects = (await api("GET", "/projects?limit=40")).body;
    for (const p of projects) {
      const t = await api("GET", "/reports/cumulative-flow?project_id=" + p.id + "&start=" + start + "&end=" + end + "&interval=week");
      if (t.status === 200 && t.body.some((b) => Object.values(b.counts).some((n) => n > 0))) return { ...p, plotted: true };
    }
    return { ...projects[0], plotted: false }; })()`);
  const report = await call(session, "POST", `/dashboards/${dashboardId}/widgets`, { widget_type: "report_cfd", width: 6, height: 460,
    position: 1, config: { project_id: project.id, interval: "week" } });
  check("a report widget is added (REST)", report.status === 201, report.text.slice(0, 200));
  await session.navigate(`${baseUrl}/dashboards/${dashboardId}`, 500);
  const card = await waitFor(session, `(() => { const s = document.querySelector('.widget-grid [data-widget-type="report_cfd"] section');
    if (!s || s.querySelector('[role="status"]') || s.textContent.includes("Loading")) return null; const svg = s.querySelector("svg[role=img]");
    return { dashboardFrame: !s.querySelector("h2"), plot: svg ? svg.getAttribute("height") : null, text: s.textContent.slice(0, 80) }; })()`, 240);
  check("the host's report card renders inside the widget, in its dashboard frame", card?.dashboardFrame, JSON.stringify(card));
  check(`…with the plot height the widget grants${project.plotted ? "" : " (no project had issues to plot)"}`,
    card && (project.plotted ? card.plot === "280" : card.plot === null), JSON.stringify({ ...card, project: project.key }));
  await clickButton(session, "Delete");
  await clickButton(session, "Delete", '[role="dialog"]');
  await waitFor(session, `location.pathname === "/"`);
  const gone = await call(session, "GET", `/dashboards/${dashboardId}`);
  check("Delete removes it", gone.status === 404, String(gone.status));
  if (gone.status === 404) dashboardId = null;

  // 5. Provenance.
  const hostDashboards = ["web/src/components/dashboards", "web/src/routes/dashboard.tsx"].filter((p) => existsSync(resolve(WEB, "..", p)));
  check("web/src carries no dashboard components", hostDashboards.length === 0, hostDashboards.join());
  const modules = new Set(readdirSync(PACKAGE).map((f) => f.replace(/\.(tsx?|css)$/, "")));
  const assets = resolve(WEB, "dist/assets");
  const carriers = readdirSync(assets).filter((f) => f.endsWith(".js"))
    .filter((f) => { const body = readFileSync(resolve(assets, f), "utf8"); return body.includes("Discard unsaved dashboard changes?") || body.includes("Filter every widget with SLQ"); });
  // Vite's content hash is 8 url-safe characters and may itself contain "-" (DashboardPage-DJt0-BsB.js).
  check("every chunk holding the dashboards UI is named after a package module",
    carriers.length > 0 && carriers.every((f) => modules.has(f.replace(/-[A-Za-z0-9_-]{8}\.js$/, ""))), JSON.stringify(carriers));
  const loadedChunks = await session.eval(`performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/assets/"))`);
  check("the page loaded the package's DashboardPage chunk and no host dashboard chunk",
    loadedChunks.some((n) => /\/assets\/DashboardPage-[^/]+\.js/.test(n)) && !loadedChunks.some((n) => /\/assets\/(?:dashboard|WidgetCard)-[^/]+\.js/.test(n)),
    JSON.stringify(loadedChunks.filter((n) => /ashboard|Widget/.test(n))));
  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
  const removed = await call(session, "DELETE", `/projects/${fixture.projectId}`);
  if (removed.status === 204) fixture = null;
  const now = await call(session, "GET", "/dashboards/my-work/widgets");
  check("the project is deleted and My Work reads byte-for-byte as before", removed.status === 204 && now.text === before.text,
    `${removed.status} ${now.text === before.text}`);
} finally {
  if (dashboardId) await call(session, "DELETE", `/dashboards/${dashboardId}`).catch(() => {});
  if (fixture?.projectId) await call(session, "DELETE", `/projects/${fixture.projectId}`).catch(() => {});
  await close();
}
const failed = report(Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])), { proof: "dashboards package" });
process.exit(failed ? 1 : 0);
