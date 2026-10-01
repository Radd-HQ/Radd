/**
 * RADD-1471: an existing issue is given an epic, and a subtask a new parent, from the UI — against
 * a stateful fixture API (RADD-1475):
 *
 *   - the issue rail's "Epic" row searches epics only, sets / changes / clears `parent_id`, and the
 *     header's parent tag follows each change; a server 409 shows the server's reason;
 *   - a subtask's "Parent issue" row searches issues only, moves it, and offers no clear;
 *   - the epic's "Add existing…" lists only issues WITHOUT a parent, sends ONE bulk update for every
 *     pick, reports a refused row by key and reason and keeps it picked for the retry;
 *   - the list's bulk bar offers "Epic…" for issues ("Parent issue…" for subtasks), disables it with
 *     the reason for a mixed selection or an epic, and parents three issues in one bulk update.
 *
 * CI's runner is slower than a workstation: every action WAITS for the state it depends on
 * (`until`) before the next key or click.
 */
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { openBrowser, outputPath, until } from "./lib/cdp.mjs";
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";
import { serveBuiltSpa } from "./lib/spa-server.mjs";

const user = { id: "admin", name: "Fixture Owner", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC" };
const project = { id: "project", key: "PM", name: "Parent management", permissions: ["*"], public: false, created_at: "2026-01-01" };
const states = ["Open", "Done"].map((name, i) => ({ id: `state-${i}`, name, category: i ? "done" : "todo", position: i, project_id: project.id }));
const view = { id: "view-list", project_id: project.id, name: "Everything", view_type: "list", query: "", group_by: null, swimlane_by: null,
  cycle_filter: null, quick_filters: [], wip_limits: null, columns: null, card_layout: null, column_order: null, swimlane_order: null,
  collapse_empty_columns: false, hidden_columns: null, owner_id: null, owner: null, global_access: "editor", shares: [], shared: true,
  can_edit: true, can_manage: true, position: 0, query_string: "project_id=project", created_at: "2026-01-01", updated_at: "2026-01-01" };

// The rows, by id; `parent_id` is the one field the proof changes.
const rows = new Map([
  ["epic-a", { number: 1, kind: "epic", title: "Epic Alpha", parent_id: null }],
  ["epic-b", { number: 2, kind: "epic", title: "Epic Beta", parent_id: null }],
  ["issue-1", { number: 3, kind: "issue", title: "Issue one", parent_id: null }],
  ["issue-2", { number: 4, kind: "issue", title: "Issue two", parent_id: null }],
  ["issue-3", { number: 5, kind: "issue", title: "Issue three", parent_id: null }],
  ["issue-4", { number: 6, kind: "issue", title: "Already in Beta", parent_id: "epic-b" }],
  ["subtask-1", { number: 7, kind: "subtask", title: "Step one", parent_id: "issue-1" }],
  ["issue-5", { number: 8, kind: "issue", title: "Other issue", parent_id: null }],
].map(([id, row]) => [id, { id, ...row }]));
const keyOf = (id) => `PM-${rows.get(id).number}`;
const ref = (id) => (id ? { id, key: keyOf(id), title: rows.get(id).title } : null);
const hydrate = (row) => ({
  id: row.id, project_id: project.id, key: keyOf(row.id), number: row.number, kind: row.kind, title: row.title, description: "",
  state: states[0], priority: "normal", labels: [], custom_fields: {}, parent: ref(row.parent_id),
  child_count: [...rows.values()].filter((r) => r.parent_id === row.id).length, comment_count: 0,
  assignee: null, reporter: null, team: null, type: null, cycle: null, release: null, flagged: false, starred: false,
  visibility: "public", estimate_points: null, rank: `0|${row.number}`,
  capabilities: { can_update: true, can_comment: true, can_transition: true }, links: { incoming: [], outgoing: [] },
  created_at: "2026-01-01", updated_at: "2026-01-01",
});
const REQUIRED_PARENT_KIND = { issue: "epic", subtask: "issue" };
/** The server's `_resolve_parent`, in miniature: the reason text, or null when the change is fine. */
function parentRefusal(row, parentId) {
  const required = REQUIRED_PARENT_KIND[row.kind];
  if (parentId === null) return row.kind === "subtask" ? `item: ${row.kind} requires a parent ${required}` : null;
  if (!required) return `item: ${row.kind} cannot have a parent`;
  const parent = rows.get(parentId);
  if (!parent) return `item ${parentId} not found`;
  if (parent.kind !== required) return `item: ${row.kind} parent must be of kind ${required}, not ${parent.kind}`;
  return null;
}

const requests = [];
let refusePatch = null; // a 409 detail the next PATCH answers with
let refuseBulk = new Map(); // item id → skipped row the next bulk update reports
const spa = await serveBuiltSpa(async (req, res, url) => {
  if (!url.pathname.startsWith("/api/")) return false;
  const route = url.pathname.replace("/api/v1", "");
  let raw = ""; for await (const chunk of req) raw += chunk;
  const body = raw ? JSON.parse(raw) : null;
  requests.push({ route, query: Object.fromEntries(url.searchParams), method: req.method, body });
  let data = [], status = 200;
  const byKey = route.match(/^\/items\/by-key\/(PM-\d+)$/);
  const byId = route.match(/^\/items\/([a-z]+-\d)$/);
  if (route === "/auth/me") data = user;
  else if (route.includes("capabilities")) data = { capabilities: [], nav: [], plugins: [...CORE_PLUGINS], remotes: [] };
  else if (route === "/projects/summary") data = { total: 1, related_count: 0, permissions: ["*"] };
  else if (route === "/page-spaces/summary") data = { total: 0, permissions: [] };
  else if (route === "/projects/project" || route === "/projects/by-key/PM") data = project;
  else if (route === "/projects") data = [project];
  else if (byKey) data = hydrate([...rows.values()].find((row) => keyOf(row.id) === byKey[1]));
  else if (byId && req.method === "PATCH") {
    const row = rows.get(byId[1]);
    const refusal = refusePatch ?? ("parent_id" in body ? parentRefusal(row, body.parent_id) : null);
    if (refusal) { status = 409; data = { detail: refusal }; }
    else { if ("parent_id" in body) row.parent_id = body.parent_id; data = hydrate(row); }
  }
  else if (byId) data = hydrate(rows.get(byId[1]));
  else if (route === "/items/link-search") {
    const { q = "", kind, unparented, exclude_id, limit = "8" } = Object.fromEntries(url.searchParams);
    data = [...rows.values()].filter((row) => (!kind || row.kind === kind) && (unparented !== "true" || row.parent_id === null)
      && row.id !== exclude_id && (q === "" || row.title.toLowerCase().includes(q.toLowerCase()) || keyOf(row.id) === q.toUpperCase()))
      .sort((a, b) => b.number - a.number).slice(0, Number(limit))
      .map((row) => ({ id: row.id, number: row.number, key: keyOf(row.id), title: row.title, kind: row.kind }));
  }
  else if (route === "/items/bulk-update") {
    const updated = [], skipped = [];
    for (const id of body.item_ids) {
      const row = rows.get(id);
      const forced = refuseBulk.get(id);
      const refusal = forced ? null : parentRefusal(row, body.patch.parent_id);
      if (forced) skipped.push({ item_id: id, key: keyOf(id), ...forced });
      else if (refusal) skipped.push({ item_id: id, key: keyOf(id), reason: "invalid_target", detail: refusal });
      else { row.parent_id = body.patch.parent_id; updated.push(id); }
    }
    data = { updated, skipped };
  }
  else if (route === "/items/ids") data = { ids: [...rows.keys()], total: rows.size };
  else if (route === "/items/count") data = { total: rows.size };
  else if (route === "/items/rollup") data = {};
  else if (route === "/items") {
    const parentId = url.searchParams.get("parent_id");
    data = [...rows.values()].filter((row) => (parentId ? row.parent_id === parentId : true)).map(hydrate);
  }
  else if (route === "/views/view-list") data = view;
  else if (route === "/views") data = [view];
  else if (route === "/fields/writable") data = { readonly_fields: [] };
  else if (route === "/screens/effective") data = { fields: [] };
  else if (route === "/states") data = states;
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
  res.writeHead(status, { "content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0), "X-Next-Cursor": "" });
  res.end(JSON.stringify(data));
  return true;
});

let browser;
const checks = [];
try {
  browser = await openBrowser({ port: 18871, profile: await mkdtemp("/tmp/radd-parent-management-"), scale: 1 });
  const s = browser.session;
  const base = spa.origin;
  assert(await s.hoverCapable(), "headless Chrome is not hover-capable");
  const has = (selector) => s.eval(`!!document.querySelector(${JSON.stringify(selector)})`);
  const text = (selector) => s.eval(`document.querySelector(${JSON.stringify(selector)})?.textContent?.trim() ?? null`);
  const attr = (selector, name) => s.eval(`document.querySelector(${JSON.stringify(selector)})?.getAttribute(${JSON.stringify(name)}) ?? null`);
  const bodyHas = (phrase) => s.eval(`document.body.innerText.includes(${JSON.stringify(phrase)})`);
  // The match runs in the page, so it is built from source rather than closing over `label`.
  const button = (label) => s.click("button", new Function("text", `return text.trim() === ${JSON.stringify(label)}`));
  const type = (value) => s.send("Input.insertText", { text: value });
  const patches = () => requests.filter((r) => r.method === "PATCH").map((r) => r.body);
  const bulkUpdates = () => requests.filter((r) => r.route === "/items/bulk-update").map((r) => r.body);
  const lastSearch = () => requests.filter((r) => r.route === "/items/link-search").at(-1)?.query;
  const pick = async (key) => {
    await until(s, async () => has(`[data-parent-candidate="${key}"]`), `candidate ${key} not offered`);
    await s.click(`[data-parent-candidate="${key}"]`);
  };

  // 1. The issue rail: "Epic", epics only, set → tag; change; clear.
  await s.navigate(`${base}/issues/PM-3`);
  await until(s, async () => has('[data-parent-field="epic"]'), "issue rail has no Epic row");
  assert.equal(await text('[data-parent-field="epic"] label'), "Epic");
  assert.equal(await has("[data-parent-current]"), false, "an unparented issue showed a current parent");
  await s.click("#parent-picker");
  await pick("PM-1");
  assert.equal(lastSearch().kind, "epic", "the issue's search did not ask for epics");
  assert.equal(await has('[data-parent-candidate="PM-3"]'), false, "an issue was offered as an epic");
  await until(s, async () => has('[data-parent-current="PM-1"]'), "picked epic not shown in the rail");
  await until(s, async () => has('a[aria-label="Open parent PM-1"]'), "header parent tag did not follow the pick");
  assert.deepEqual(patches().at(-1), { parent_id: "epic-a" });
  checks.push("issue rail sets the epic and the parent tag follows");
  await s.click('[aria-label="Change epic"]');
  await until(s, async () => has('[data-parent-search="epic"]'), "Change did not open the search");
  // RADD-1500: the cross-project search tells you a project key narrows it — the first thing
  // anyone types to reach another project's epics (the server owns the narrowing; its test is
  // tests/test_cross_project.py).
  assert.match(await s.eval(`document.querySelector('[data-parent-search="epic"]').placeholder`), /project key narrows/,
    "the epic search does not say a project key narrows it");
  await type("Beta");
  await pick("PM-2");
  await until(s, async () => has('[data-parent-current="PM-2"]') && has('a[aria-label="Open parent PM-2"]'), "changed epic not shown");
  checks.push("issue rail changes the epic");
  await s.screenshot(outputPath("radd-parent-management-rail.png"));
  await s.click('[aria-label="Clear epic"]');
  await until(s, async () => !(await has("[data-parent-current]")) && !(await has('a[aria-label^="Open parent"]')), "clear left a parent behind");
  assert.deepEqual(patches().at(-1), { parent_id: null });
  checks.push("issue rail clears the epic");

  // 2. A server refusal reads as the server's sentence, and the rail keeps the truth.
  refusePatch = "item: PM-3 cannot change epic while its release is frozen";
  await s.click("#parent-picker");
  await pick("PM-1");
  await until(s, async () => bodyHas(refusePatch), "the 409 reason never reached the person");
  assert.equal(await has("[data-parent-current]"), false, "a refused pick was shown as the parent");
  refusePatch = null;
  checks.push("a 409 shows the server's reason and sets nothing");

  // 3. The subtask rail: "Parent issue", issues only, a move, no clear.
  await s.navigate(`${base}/issues/PM-7`);
  await until(s, async () => has('[data-parent-field="issue"]'), "subtask rail has no Parent issue row");
  assert.equal(await text('[data-parent-field="issue"] label'), "Parent issue");
  assert(await has('[data-parent-current="PM-3"]'), "subtask's current parent missing");
  assert.equal(await has('[aria-label="Clear parent issue"]'), false, "a subtask offered a clear");
  assert(await bodyHas("A subtask always belongs to an issue"), "no hint says why there is no clear");
  await s.click('[aria-label="Change parent issue"]');
  await until(s, async () => has('[data-parent-search="issue"]'), "Change did not open the subtask's search");
  await type("Other");
  await pick("PM-8");
  assert.equal(lastSearch().kind, "issue", "the subtask's search did not ask for issues");
  await until(s, async () => has('[data-parent-current="PM-8"]'), "moved subtask does not show its new parent");
  assert.deepEqual(patches().at(-1), { parent_id: "issue-5" });
  checks.push("subtask rail moves it to another issue and offers no clear");

  // 4. The epic's "Add existing…": unparented issues only, one bulk update, refusals per row.
  await s.navigate(`${base}/issues/PM-2`);
  // The heading is uppercased by CSS, so innerText reads "EPIC PROGRESS" — match the source text.
  await until(s, async () => s.eval(`[...document.querySelectorAll('h3')].some((h) => h.textContent === 'Epic progress')`), "epic page has no children section");
  await s.click("section button[aria-expanded]", new Function("text", "return text.includes('Epic progress')"));
  await until(s, async () => bodyHas("Already in Beta"), "the epic's existing child never listed");
  await button("Add existing…");
  await until(s, async () => has("[data-add-existing-children]"), "Add existing modal did not open");
  await until(s, async () => has('[data-parent-candidate="PM-4"]'), "unparented issue not offered");
  assert.equal(lastSearch().unparented, "true", "the search did not ask for unparented issues");
  assert.equal(lastSearch().kind, "issue");
  assert.equal(await has('[data-parent-candidate="PM-6"]'), false, "an issue already in an epic was offered");
  assert.equal(await has('[data-parent-candidate="PM-1"]'), false, "an epic was offered as a child issue");
  await s.click('[data-parent-candidate="PM-4"]');
  await until(s, async () => has('[data-picked-child="PM-4"]'), "first pick not chipped");
  await s.click("#add-existing-search");
  await pick("PM-5");
  await until(s, async () => has('[data-picked-child="PM-5"]'), "second pick not chipped");
  refuseBulk = new Map([["issue-3", { reason: "invalid_target", detail: "item: PM-5 is frozen with its release" }]]);
  await button("Add 2 issues");
  await until(s, async () => has("[data-add-existing-skipped]"), "the refused row was not reported");
  assert.deepEqual(bulkUpdates().at(-1), { item_ids: ["issue-2", "issue-3"], patch: { parent_id: "epic-b" } });
  assert(await bodyHas("PM-5: item: PM-5 is frozen with its release"), "the refusal lacks key or reason");
  assert.equal(await has('[data-picked-child="PM-4"]'), false, "an adopted issue stayed picked");
  assert(await has('[data-picked-child="PM-5"]'), "the refused issue was dropped from the picks");
  await until(s, async () => bodyHas("Issue two"), "children list did not refresh with the adopted issue");
  checks.push("Add existing lists only unparented issues and sends one bulk update");
  checks.push("a refused row is reported by key and reason and stays picked");
  refuseBulk = new Map();
  await button("Add 1 issue");
  await until(s, async () => !(await has("[data-add-existing-children]")), "modal stayed open after a clean add");
  await until(s, async () => bodyHas("Issue three"), "retried issue not in the children list");
  checks.push("the retry adds the refused issue and closes the modal");
  await s.screenshot(outputPath("radd-parent-management-epic.png"));

  // 5. The list's bulk bar: "Epic…" for issues, reasons for a mix and for an epic, one bulk update.
  await s.navigate(`${base}/p/PM/v/view-list`);
  await until(s, async () => has('input[aria-label="Select PM-3"]'), "list rows not selectable");
  for (const key of ["PM-3", "PM-4", "PM-8"]) {
    await s.click(`input[aria-label="Select ${key}"]`);
    await until(s, async () => s.eval(`document.querySelector('input[aria-label="Select ${key}"]').checked`), `${key} not selected`);
  }
  await until(s, async () => has("[data-bulk-parent-action]"), "bulk bar has no parent action");
  assert.equal(await text("[data-bulk-parent-action]"), "Epic…");
  // The bar disables the action until the selected rows are loaded and their kinds known; on a slow
  // run that is later than the checkbox state, so wait for the enabled state instead of asserting it.
  await until(s, async () => (await attr("[data-bulk-parent-action]", "disabled")) === null, "Epic… disabled for three issues");
  await s.click('input[aria-label="Select PM-7"]');
  await until(s, async () => (await attr("[data-bulk-parent-action]", "disabled")) !== null, "a mixed selection kept Epic… enabled");
  assert.match(await attr("[data-bulk-parent-action]", "title"), /mixed selection/);
  checks.push("a mixed selection disables the action with the reason");
  await s.click('input[aria-label="Select PM-7"]');
  await until(s, async () => (await attr("[data-bulk-parent-action]", "disabled")) === null, "Epic… stayed disabled after unmixing",
    { describe: async () => `title=${await attr("[data-bulk-parent-action]", "title")}` });
  await s.click("[data-bulk-parent-action]");
  await until(s, async () => has("[data-bulk-parent-dialog]"), "bulk parent dialog did not open");
  assert(await bodyHas("Clear epic"), "issues were offered no Clear epic");
  await pick("PM-1");
  assert.equal(await has('[data-parent-candidate="PM-3"]'), false, "the bulk search offered an issue as an epic");
  await until(s, async () => has('[data-bulk-parent-pick="PM-1"]'), "bulk pick not shown");
  await button("Set epic");
  await until(s, async () => !(await has("[data-bulk-parent-dialog]")), "dialog stayed open after applying");
  assert.deepEqual(bulkUpdates().at(-1), { item_ids: ["issue-1", "issue-2", "issue-5"], patch: { parent_id: "epic-a" } });
  await until(s, async () => bodyHas("Updated 3"), "bulk result toast missing");
  assert.deepEqual(["issue-1", "issue-2", "issue-5"].map((id) => rows.get(id).parent_id), ["epic-a", "epic-a", "epic-a"]);
  checks.push("bulk Epic… parents three issues in one update");
  // A subtask-only selection speaks of its parent issue; an epic has none. The toast stack sits
  // bottom-right over the bar's Clear button, so it is let expire before the click.
  await until(s, async () => !(await bodyHas("Updated 3")), "result toast never expired");
  await s.click('[aria-label="Clear selection"]');
  await until(s, async () => !(await has("[data-bulk-parent-action]")), "selection did not clear");
  await s.click('input[aria-label="Select PM-7"]');
  await until(s, async () => (await text("[data-bulk-parent-action]")) === "Parent issue…", "subtask selection not labelled Parent issue…");
  await s.click('input[aria-label="Select PM-7"]');
  await until(s, async () => !(await has("[data-bulk-parent-action]")), "subtask selection did not clear");
  await s.click('input[aria-label="Select PM-1"]');
  await until(s, async () => (await attr("[data-bulk-parent-action]", "disabled")) !== null, "an epic selection kept the action enabled");
  assert.match(await attr("[data-bulk-parent-action]", "title"), /An epic has no parent/);
  checks.push("subtasks get Parent issue…, an epic is refused with the reason");
  await s.screenshot(outputPath("radd-parent-management-bulk.png"));

  console.log(JSON.stringify({ passed: true, checks }));
} catch (error) {
  if (browser) {
    await browser.session.screenshot(outputPath("radd-parent-management-failure.png"));
    console.error(await browser.session.eval("document.body.innerText"));
  }
  throw error;
} finally {
  await browser?.close();
  await spa.close();
}
