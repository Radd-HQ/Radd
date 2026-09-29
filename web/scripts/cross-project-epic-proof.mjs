/**
 * RADD-1493 (+ RADD-1491): a cross-project epic shows its whole picture, and a parent you
 * cannot read is shown as hidden — against a stateful fixture API:
 *
 *   - an issue whose parent was withheld renders "In an epic you cannot see" in the rail with NO
 *     picker, and a matching header tag;
 *   - the epic page's children header says how many children live in other projects and how many
 *     the viewer may not read, and "Open as board" lands on /e/KEY/board;
 *   - the epic board is an all-projects board: state categories across, projects down, the epic
 *     itself absent, and the grouped request carries no project_id;
 *   - a project board grouped by epic shows "N more in TD" on the epic's group header (linking to
 *     the epic board), asked the rollup for the group's epic without a progress slot, and files a
 *     row whose epic is withheld under "Epic you cannot see".
 */
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { openBrowser, outputPath, until } from "./lib/cdp.mjs";
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";
import { serveBuiltSpa } from "./lib/spa-server.mjs";

const user = { id: "admin", name: "Fixture Owner", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC" };
const projects = {
  dev: { id: "dev", key: "DEV", name: "Development", permissions: ["*"], public: false, created_at: "2026-01-01" },
  td: { id: "td", key: "TD", name: "Technical direction", permissions: ["*"], public: false, created_at: "2026-01-01" },
};
const states = [
  { id: "todo", name: "To do", category: "todo", category_key: "todo", position: 0, project_id: "dev" },
  { id: "doing", name: "In progress", category: "in_progress", category_key: "in_progress", position: 1, project_id: "dev" },
  { id: "done", name: "Done", category: "done", category_key: "done", position: 2, project_id: "dev" },
];
const stateOf = (id) => states.find((s) => s.id === id);
const baseView = { cycle_filter: null, quick_filters: [], wip_limits: null, columns: null, card_layout: null, column_order: null, swimlane_order: null,
  collapse_empty_columns: false, hidden_columns: null, owner_id: null, owner: null, global_access: "editor", shares: [], shared: true,
  can_edit: true, can_manage: true, position: 0, created_at: "2026-01-01", updated_at: "2026-01-01" };
const epicView = { ...baseView, id: "board-epic", project_id: "dev", name: "By epic", view_type: "board", query: "", group_by: "epic", swimlane_by: null, query_string: "project_id=dev" };

// Rows by id. `epic` is the server-resolved nearest epic; `hidden` marks a withheld parent/epic.
const rows = new Map([
  ["epic-a", { project: "dev", number: 1, kind: "epic", title: "Epic Alpha", parent: null, state: "doing" }],
  ["dev-2", { project: "dev", number: 2, kind: "issue", title: "Dev half", parent: "epic-a", state: "todo" }],
  ["dev-3", { project: "dev", number: 3, kind: "issue", title: "Loose dev issue", parent: null, state: "todo" }],
  ["dev-4", { project: "dev", number: 4, kind: "issue", title: "Under a TD epic you cannot see", parent: null, hidden: true, state: "todo" }],
  ["td-1", { project: "td", number: 1, kind: "issue", title: "TD half, part one", parent: "epic-a", state: "todo" }],
  ["td-2", { project: "td", number: 2, kind: "issue", title: "TD half, part two", parent: "epic-a", state: "doing" }],
  ["td-3", { project: "td", number: 3, kind: "issue", title: "In an epic you cannot see", parent: null, hidden: true, state: "todo" }],
].map(([id, row]) => [id, { id, ...row }]));
const keyOf = (id) => `${projects[rows.get(id).project].key}-${rows.get(id).number}`;
const ref = (id) => (id ? { id, key: keyOf(id), title: rows.get(id).title } : null);
const epicOf = (row) => (row.kind === "epic" ? row.id : row.parent && rows.get(row.parent).kind === "epic" ? row.parent : null);
const hydrate = (row) => ({
  id: row.id, project_id: row.project, key: keyOf(row.id), number: row.number, kind: row.kind, title: row.title, description: "",
  state: stateOf(row.state), priority: "normal", labels: [], custom_fields: {},
  parent: ref(row.parent), parent_hidden: Boolean(row.hidden), epic: ref(epicOf(row)), epic_hidden: Boolean(row.hidden),
  child_count: [...rows.values()].filter((r) => r.parent === row.id).length, comment_count: 0,
  assignee: null, reporter: null, team: null, type: null, cycle: null, release: null, flagged: false, starred: false,
  visibility: "public", estimate_points: null, rank: `0|${row.number}`,
  capabilities: { can_update: true, can_comment: true, can_transition: true }, links: { incoming: [], outgoing: [] },
  created_at: "2026-01-01", updated_at: "2026-01-01",
});
// The server's rollup for Epic Alpha: three readable descendants (one in DEV, two in TD), one withheld.
const rollupAlpha = { total: 3, done: 1, in_progress: 1, points_total: 0, points_done: 0, by_project: { DEV: 1, TD: 2 }, withheld: 1, estimate_seconds: 0, logged_seconds: 0 };

const requests = [];
const spa = await serveBuiltSpa(async (req, res, url) => {
  if (!url.pathname.startsWith("/api/")) return false;
  const route = url.pathname.replace("/api/v1", "");
  let raw = ""; for await (const chunk of req) raw += chunk;
  const body = raw ? JSON.parse(raw) : null;
  const query = Object.fromEntries(url.searchParams);
  requests.push({ route, query, method: req.method, body });
  let data = [];
  const byKey = route.match(/^\/items\/by-key\/([A-Z]+-\d+)$/);
  const byId = route.match(/^\/items\/([a-z]+-[a-z0-9]+)$/);
  const projectByKey = route.match(/^\/projects\/by-key\/([A-Z]+)$/);
  const projectById = route.match(/^\/projects\/(dev|td)$/);
  if (route === "/auth/me") data = user;
  else if (route.includes("capabilities")) data = { capabilities: [], nav: [], plugins: [...CORE_PLUGINS], remotes: [] };
  else if (route === "/projects/summary") data = { total: 2, related_count: 0, permissions: ["*"] };
  else if (route === "/page-spaces/summary") data = { total: 0, permissions: [] };
  else if (projectByKey) data = Object.values(projects).find((p) => p.key === projectByKey[1]);
  else if (projectById) data = projects[projectById[1]];
  else if (route === "/projects") data = Object.values(projects);
  else if (byKey) data = hydrate([...rows.values()].find((row) => keyOf(row.id) === byKey[1]));
  else if (byId) data = hydrate(rows.get(byId[1]));
  else if (route === "/items/rollup") data = body.item_ids.includes("epic-a") ? { "epic-a": rollupAlpha } : {};
  else if (route === "/items/grouped") {
    const { axis, lane, column_key, lane_key, rows_only, project_id } = query;
    const pool = [...rows.values()].filter((row) => !project_id || row.project === project_id);
    // `q` is applied the way the server would for the two boards this proof opens.
    const scoped = query.q?.includes("epic = DEV-1") ? pool.filter((row) => epicOf(row) === "epic-a" && row.kind !== "epic") : pool;
    const colOf = (row) => axis === "epic" ? (row.hidden ? "__hidden_epic__" : epicOf(row) ?? "__no_epic__") : axis === "state_category" ? stateOf(row.state).category : "__all__";
    const laneOf = (row) => lane === "project" ? row.project : "__all__";
    const column_totals = {}, lane_totals = {};
    for (const row of scoped) { column_totals[colOf(row)] = (column_totals[colOf(row)] ?? 0) + 1; lane_totals[laneOf(row)] = (lane_totals[laneOf(row)] ?? 0) + 1; }
    const column_labels = axis === "epic" ? { "epic-a": "DEV-1 · Epic Alpha", __hidden_epic__: "Epic you cannot see" } : {};
    const lane_labels = lane === "project" ? { dev: "DEV · Development", td: "TD · Technical direction" } : {};
    const epic_refs = axis === "epic" ? { "epic-a": { id: "epic-a", key: "DEV-1", title: "Epic Alpha", kind: "epic" } } : {};
    data = { cells: [], total_groups: Object.keys(column_totals).length, column_totals, lane_totals, column_points: {}, column_labels, lane_labels, epic_refs };
    if (rows_only === "true") {
      const items = scoped.filter((row) => colOf(row) === column_key && (!lane || laneOf(row) === lane_key)).map(hydrate);
      data = { ...data, cells: [{ column: column_key, lane: lane_key ?? "__all__", total: null, items, next_cursor: null }], column_totals: {}, lane_totals: {}, column_points: {} };
    }
  }
  else if (route === "/items/ids") data = { ids: [...rows.keys()], total: rows.size };
  else if (route === "/items/count") data = { total: rows.size };
  else if (route === "/items") {
    const parentId = url.searchParams.get("parent_id");
    data = [...rows.values()].filter((row) => (parentId ? row.parent === parentId : true)).map(hydrate);
  }
  else if (route === "/views/board-epic") data = epicView;
  else if (route === "/views") data = [epicView];
  else if (route === "/fields/writable") data = { readonly_fields: [] };
  else if (route === "/screens/effective") data = { fields: [] };
  else if (route === "/states") data = states;
  else if (route === "/state-categories") data = [];
  else if (route.endsWith("/comments/feed")) data = { comments: [], older_cursor: null };
  else if (route.endsWith("/allowed-transitions")) data = { mode: "off", targets: [] };
  else if (route.endsWith("/sla")) data = { entries: [] };
  else if (route.endsWith("/watchers")) data = { watching: false, watchers: [] };
  else if (route.includes("/notifications")) data = { items: [], notifications: [], unread_count: 0, total: 0 };
  else if (route === "/ai/status") data = { enabled: false, features: {} };
  else if (route === "/instance") data = { work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5 };
  else if (route.includes("/resolve")) data = { value: false };
  else if (route.endsWith("/timelogging")) data = { enabled: false };
  else if (route.includes("preferences") || route.includes("contribution-settings")) data = {};
  res.writeHead(200, { "content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0), "X-Next-Cursor": "" });
  res.end(JSON.stringify(data));
  return true;
});

let browser;
const checks = [];
try {
  browser = await openBrowser({ port: 18873, profile: await mkdtemp("/tmp/radd-cross-project-epic-"), scale: 1 });
  const s = browser.session;
  const base = spa.origin;
  assert(await s.hoverCapable(), "headless Chrome is not hover-capable");
  const has = (selector) => s.eval(`!!document.querySelector(${JSON.stringify(selector)})`);
  const text = (selector) => s.eval(`document.querySelector(${JSON.stringify(selector)})?.textContent?.trim() ?? null`);
  const attr = (selector, name) => s.eval(`document.querySelector(${JSON.stringify(selector)})?.getAttribute(${JSON.stringify(name)}) ?? null`);
  const bodyHas = (phrase) => s.eval(`document.body.innerText.includes(${JSON.stringify(phrase)})`);
  const rect = (selector) => s.eval(`(() => { const r = document.querySelector(${JSON.stringify(selector)})?.getBoundingClientRect(); return r ? { w: r.width, h: r.height } : null; })()`);
  const grouped = () => requests.filter((r) => r.route === "/items/grouped");
  const rollups = () => requests.filter((r) => r.route === "/items/rollup").map((r) => r.body.item_ids);

  // 1. A withheld parent: hidden, not absent — no picker to replace it with.
  await s.navigate(`${base}/issues/TD-3`);
  await until(s, async () => has("[data-parent-hidden]"), "rail has no hidden-parent row");
  assert.equal(await has("#parent-picker"), false, "a hidden parent still offered a picker");
  assert(await bodyHas("In an epic you cannot see"), "hidden row lacks its sentence");
  assert(await has("[data-parent-hidden-tag]"), "header has no hidden-parent tag");
  checks.push("a withheld parent renders as hidden with no picker, and the header tags it");
  await s.screenshot(outputPath("radd-cross-project-hidden-parent.png"));

  // 2. The epic page: how much lives elsewhere, how much is withheld, and Open as board.
  await s.navigate(`${base}/issues/DEV-1`);
  await until(s, async () => has('[data-foreign-children="2"]'), "children header never said what lives in TD");
  assert.equal(await text('[data-foreign-children="2"]'), "2 in TD");
  assert.equal(await text('[data-withheld="1"]'), "1 you cannot see");
  assert(await has("[data-open-epic-board]"), "no Open as board");
  await s.screenshot(outputPath("radd-cross-project-epic-page.png"));
  await s.click("[data-open-epic-board]");
  await until(s, async () => (await s.eval("location.pathname")) === "/e/DEV-1/board", "Open as board did not land on the epic board",
    { describe: async () => `pathname=${await s.eval("location.pathname")}` });
  checks.push("the epic page counts children elsewhere and withheld, and opens the epic board");

  // 3. The epic board: categories across, projects down, the epic itself absent, no project scope.
  await until(s, async () => bodyHas("TD · Technical direction") && bodyHas("DEV · Development"), "epic board lanes not labelled by project");
  await until(s, async () => bodyHas("TD half, part one") && bodyHas("Dev half"), "epic board cards from both projects not drawn");
  assert.equal(await bodyHas("Loose dev issue"), false, "an issue outside the epic reached the epic board");
  const summary = grouped().find((r) => r.query.summary_only === "true" && r.query.axis === "state_category");
  assert(summary, "no summary request for the epic board");
  assert.equal(summary.query.lane, "project", "the epic board is not laned by project");
  assert.equal(summary.query.project_id, undefined, "the epic board was scoped to one project");
  assert.match(summary.query.q, /epic = DEV-1 AND kind != epic/);
  assert.equal(await bodyHas("DEV-1 · Epic Alpha"), true, "the epic board is not named after the epic");
  checks.push("the epic board spans projects: state categories across, projects down, epic absent");
  await s.screenshot(outputPath("radd-cross-project-epic-board.png"));

  // 4. A project board grouped by epic: the chip on the group header, and the hidden bucket.
  await s.navigate(`${base}/p/DEV/v/board-epic`);
  await until(s, async () => has('[data-foreign-children="2"] a'), "epic group header has no chip");
  assert.equal(await text('[data-foreign-children="2"] a'), "2 more in TD");
  assert.equal(await attr('[data-foreign-children="2"] a', "href"), "/e/DEV-1/board");
  const chip = await rect('[data-foreign-children="2"] a');
  assert(chip && chip.w > 40 && chip.h > 10, `chip has no size: ${JSON.stringify(chip)}`);
  assert.equal(await text('[data-foreign-children="2"] [title="Children in projects you cannot see"]'), "1 you cannot see");
  assert(rollups().some((ids) => ids.includes("epic-a")), "the board never asked the rollup for the group's epic");
  await until(s, async () => bodyHas("Epic you cannot see"), "the hidden-epic bucket is not labelled");
  await until(s, async () => bodyHas("Under a TD epic you cannot see"), "the hidden-epic bucket has no card");
  checks.push("a project board's epic header says what lives elsewhere and links to the epic board");
  checks.push("a row whose epic is withheld sits under 'Epic you cannot see'");
  await s.screenshot(outputPath("radd-cross-project-board-chip.png"));

  console.log(JSON.stringify({ passed: true, checks }));
} catch (error) {
  if (browser) {
    await browser.session.screenshot(outputPath("radd-cross-project-failure.png"));
    console.error(await browser.session.eval("document.body.innerText"));
  }
  throw error;
} finally {
  await browser?.close();
  await spa.close();
}
