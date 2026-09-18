/** Built SPA regression: coherent initial controls, deferred choices, authoritative PATCH.
 * Uses synthetic HTTP fixtures only; never writes to a real instance. */
import assert from "node:assert/strict";
import http from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser } from "./lib/cdp.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const project = {id: "project", key: "PRF", name: "Performance fixture", permissions: ["*"], created_at: "2026-01-01"};
const state = {id: "state", name: "Open", category: "todo", category_key: "todo", position: 0, project_id: project.id};
let item = {id: "issue", key: "PRF-1", project_id: project.id, number: 1, title: "Performance fixture issue",
  description: "## A rendered heading\n\nReadable **content** while the renderer starts.", state,
  priority: "normal", kind: "issue", labels: [], custom_fields: {},
  assignee: {id: "selected", name: "Selected Person"}, reporter: {id: "reporter", name: "Original Reporter"},
  capabilities: {can_update: true, can_comment: true, can_transition: true},
  links: {incoming: [], outgoing: []}, created_at: "2026-01-01", updated_at: "2026-01-01"};
const people = [{id: "selected", name: "Selected Person", active: true, has_access: true},
  {id: "replacement", name: "Replacement Person", active: true, has_access: true},
  {id: "reporter", name: "Original Reporter", active: true, has_access: true}];
const requests = [];
let releasePermissions;
const permissionGate = new Promise(resolve => { releasePermissions = resolve; });
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    requests.push({route, query: url.search, method: req.method});
    let data = [];
    if (route === "/auth/me") data = {id: "admin", name: "Fixture Admin", email: "fixture@example.test", instance_role: "admin", permissions: ["*"], timezone: "UTC"};
    else if (route.includes("capabilities")) data = {capabilities: [], nav: [], plugins: [], ui: []};
    else if (route === "/preferences") data = {};
    else if (route === "/projects/summary") data = {total: 1, related_count: 0, permissions: ["*"]};
    else if (route === "/page-spaces/summary") data = {total: 0, permissions: []};
    else if (route === "/projects/project") data = project;
    else if (route === "/projects") data = [project];
    else if (route.startsWith("/items/by-key/")) data = item;
    else if (route === "/fields/writable") { await permissionGate; data = {readonly_fields: []}; }
    else if (route === "/screens/effective") data = {fields: ["assignee", "reporter"].map(field => ({field, placement: "primary", custom: false}))};
    else if (route === "/states") data = [state];
    else if (route.endsWith("/comments/feed")) data = {comments: [], older_cursor: null};
    else if (route.endsWith("/allowed-transitions")) data = {mode: "off", targets: []};
    else if (route.endsWith("/sla")) data = {entries: []};
    else if (route.endsWith("/watchers")) data = {watching: false, watchers: []};
    else if (route.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (route === "/ai/status") data = {enabled: false, features: {}};
    else if (route === "/instance") data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (route.includes("/resolve")) data = {value: false};
    else if (route.endsWith("/timelogging")) data = {enabled: false};
    else if (route === "/users/directory") data = people;
    else if (route === "/items/issue" && req.method === "PATCH") {
      let body = "";
      for await (const chunk of req) body += chunk;
      const patch = JSON.parse(body);
      item = {...item, ...patch, assignee: "assignee_id" in patch
        ? people.find(person => person.id === patch.assignee_id) ?? null : item.assignee};
      data = item;
    }
    res.writeHead(200, {"content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0)});
    res.end(JSON.stringify(data));
    return;
  }
  let file = path.resolve(dist, "." + url.pathname);
  if (!file.startsWith(dist) || !existsSync(file) || statSync(file).isDirectory()) file = path.join(dist, "index.html");
  const mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}[path.extname(file)] ?? "application/octet-stream";
  res.writeHead(200, {"content-type": mime}); res.end(readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
let browser;
const until = async (predicate, label) => {
  for (let i = 0; i < 150; i++) {
    if (await predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 40));
  }
  throw Error(label);
};
try {
  browser = await openBrowser({port: 18843, profile: await mkdtemp("/tmp/radd-issue-performance-"), scale: 1});
  const s = browser.session;
  await s.send("Page.addScriptToEvaluateOnNewDocument", {source: `
    window.emptyViewerFrames = 0;
    function check() {
      for (const el of document.querySelectorAll('[aria-busy="true"]')) {
        if (el.querySelector('.radd-rich-viewer') && !el.innerText.trim()) window.emptyViewerFrames++;
      }
      requestAnimationFrame(check);
    }
    requestAnimationFrame(check);
  `});
  await s.navigate(`http://127.0.0.1:${server.address().port}/issues/PRF-1`);
  assert(requests.some(request => request.route === "/fields/writable"));
  assert(!(await s.eval(`document.body.innerText.includes('Selected Person')`)), "controls mounted before permissions");
  releasePermissions();
  await until(() => s.eval(`document.body.innerText.includes('Selected Person') && !!document.querySelector('.radd-rich-viewer .ProseMirror')`), "issue did not finish rendering");
  assert.equal(requests.filter(request => request.route === "/users/directory").length, 0, "eager directory request");
  assert.equal(await s.eval("window.emptyViewerFrames"), 0, "rich renderer removed its fallback too early");
  assert.equal(requests.filter(request => request.route === "/projects/summary").length, 1);
  assert.equal(requests.filter(request => request.route === "/page-spaces/summary").length, 1);
  const assigneeId = await s.eval(`Array.from(document.querySelectorAll('label')).find(el => el.textContent === 'Assignee').htmlFor`);
  await s.click(`#${CSSescape(assigneeId)}`);
  await until(() => requests.some(request => request.route === "/users/directory"), "opening picker did not request choices");
  await until(() => s.eval(`Array.from(document.querySelectorAll('[role="option"]')).some(el => el.textContent.includes('Replacement Person'))`), "picker options missing");
  await s.click('[role="option"]', text => text.includes("Replacement Person"));
  await until(() => requests.some(request => request.method === "PATCH"), "selection did not save");
  await until(() => s.eval(`document.getElementById(${JSON.stringify(assigneeId)}).textContent.includes('Replacement Person')`), "saved selection did not display");
  await until(() => requests.filter(request => request.route.startsWith("/items/by-key/")).length === 2,
    "assignment must recheck read access");
  await s.click('input[aria-label="Title"]');
  await s.eval(`document.querySelector('input[aria-label="Title"]').select()`);
  await s.send("Input.insertText", {text: "Updated title"});
  await s.send("Input.dispatchKeyEvent", {type: "keyDown", key: "Enter", code: "Enter"});
  await until(() => item.title === "Updated title", "title did not save");
  await new Promise(resolve => setTimeout(resolve, 200));
  assert.equal(requests.filter(request => request.route.startsWith("/items/by-key/")).length, 2, "title PATCH refetched the record it supplied");
  const reporterId = await s.eval(`Array.from(document.querySelectorAll('label')).find(el => el.textContent === 'Reporter').htmlFor`);
  await s.eval(`document.getElementById(${JSON.stringify(reporterId)}).focus()`);
  await s.send("Input.dispatchKeyEvent", {type: "keyDown", key: "ArrowDown", code: "ArrowDown"});
  await until(() => requests.some(request => request.route === "/users/directory" && request.query.includes("include_requesters=true")),
    "keyboard opening did not request reporter choices");
  assert.equal(s.consoleErrors.length, 0, s.consoleErrors.join("\n"));
  console.log("Issue rendering: coherent controls, selected names, deferred choices, no blank rich-text frames, and PATCH cache reconciliation passed.");
} catch (error) {
  console.error(JSON.stringify({requests, errors: browser?.session.consoleErrors,
    body: await browser?.session.eval("document.body.innerText")}, null, 2));
  throw error;
} finally {
  releasePermissions();
  await browser?.close();
  server.closeAllConnections();
  server.close();
}

function CSSescape(value) { return value.replace(/[^a-zA-Z0-9_-]/g, character => `\\${character}`); }
