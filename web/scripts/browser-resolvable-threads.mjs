/** RADD-1282: browser contract for issue threads and workflow rule preservation. */
import assert from "node:assert/strict";
import http from "node:http";
import {readFileSync, existsSync, statSync} from "node:fs";
import {mkdtemp} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {openBrowser} from "./lib/cdp.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const user = {id: "admin", name: "Review Owner", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC"};
const project = {id: "project", key: "THR", name: "Thread review", permissions: ["*"], created_at: "2026-01-01"};
const states = ["Open", "Done"].map((name, i) => ({id: `state-${i}`, name, category: i ? "done" : "todo", category_key: i ? "done" : "todo", position: i, project_id: project.id}));
const item = {id: "issue", key: "THR-1", project_id: project.id, number: 1, title: "Review the delivery plan",
  description: "Discuss open questions before completing the work.", state: states[0],
  priority: "normal", kind: "issue", labels: [], custom_fields: {},
  capabilities: {can_update: true, can_comment: true, can_transition: true},
  links: {incoming: [], outgoing: []}, created_at: "2026-01-01", updated_at: "2026-01-01"};
let comments = [{id: "ordinary", body: "An informational comment with a reply", is_thread: false, reply_count: 1},
  {id: "thread", body: "Has the delivery been verified?", is_thread: true, reply_count: 1, can_resolve: true},
  // RADD-1283: the project's rule does not let this reader resolve this one.
  {id: "locked", body: "Managers sign this off", is_thread: true, reply_count: 1, can_resolve: false,
    resolved_at: "2026-09-20T09:00:00Z", resolver_name: "A Manager"}].map(row => ({...row, entity_type: "item", entity_id: item.id, author: user, visibility: "public", visible_to_teams: [], anchor: null, parent_comment_id: null, resolved_at: null, resolved_by: null, created_at: "2026-01-01", updated_at: "2026-01-01", ...row}));
const replies = [{...comments[0], id: "reply", parent_comment_id: "thread", body: "Checking the delivery now.", is_thread: false}];
let transition = {id: "transition", project_id: project.id, from_state_id: null, to_state_id: states[1].id, position: 0,
  applies_when: [], rules: [{check: "require_field", params: {kind: "builtin", key: "assignee", op: "set"}},
    {check: "require_approval", params: {approvers: [{kind: "user", id: user.id, name: user.name}]}},
    {check: "require_resolved_threads", params: {}}]};
const requests = [];
let threadPolicy = {default: "author", overrides: []};
const issueTypes = [{id: "type-bug", project_id: "project", name: "Bug", color: "#ff0000", position: 0, is_default: true},
  {id: "type-review", project_id: "project", name: "Review", color: "#00ff00", position: 1, is_default: false}];
let failResolve = false;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    requests.push({route, query: url.search, method: req.method, body});
    let data = [], status = 200;
    if (route === "/auth/me") data = user;
    else if (route.includes("capabilities")) data = {capabilities: [], nav: [], plugins: [], ui: []};
    else if (route === "/preferences") data = {};
    else if (route === "/projects/summary") data = {total: 1, related_count: 0, permissions: ["*"]};
    else if (route === "/page-spaces/summary") data = {total: 0, permissions: []};
    else if (route === "/projects/project" || route === "/projects/by-key/THR") data = project;
    else if (route === "/projects") data = [project];
    else if (route.startsWith("/items/by-key/") || route === "/items/issue") data = item;
    else if (route === "/fields/writable") data = {readonly_fields: []};
    else if (route === "/screens/effective") data = {fields: []};
    else if (route === "/states") data = states;
    else if (route.endsWith("/comments/feed")) data = {comments: url.searchParams.get("unresolved") === "true" ? comments.filter(c => c.is_thread && !c.resolved_at) : comments, older_cursor: null};
    else if (route === "/items/issue/comments" && req.method === "POST") {
      data = {...comments[0], ...body, id: `new-${comments.length}`, reply_count: 0, can_resolve: !!body.is_thread}; comments.push(data);
    }
    else if (/^\/comments\/[^/]+\/(resolve|reopen)$/.test(route)) {
      if (failResolve) {status = 403; data = {detail: "Thread resolution refused"};}
      else {
        const id = route.split("/")[2], resolve = route.endsWith("/resolve");
        comments = comments.map(c => c.id === id ? {...c, resolved_at: resolve ? "2026-09-23T12:00:00Z" : null, resolved_by: resolve ? user.id : null, resolver_name: resolve ? user.name : null} : c);
        data = comments.find(c => c.id === id);
      }
    }
    else if (route.endsWith("/replies") && req.method === "POST") {
      const id = route.split("/")[2];
      data = {...replies[0], id: `reply-${replies.length}`, body: body.body};
      replies.push(data);
      if (body.unresolve) comments = comments.map(c => c.id === id ? {...c, resolved_at: null, resolved_by: null, resolver_name: null} : c);
    }
    else if (route.endsWith("/replies")) data = {comments: replies, older_cursor: null};
    else if (route.endsWith("/allowed-transitions")) data = {mode: "guards", targets: states.map(s => ({state_id: s.id, allowed: s.id === states[0].id || !comments.some(c => c.is_thread && !c.resolved_at), failures: []}))};
    else if (route === "/projects/project/transitions") data = [transition];
    else if (route === "/projects/project/thread-resolution") data = threadPolicy = req.method === "PUT" ? body : threadPolicy;
    else if (route === "/issue-types") data = issueTypes;
    else if (route === "/transitions/transition" && req.method === "PATCH") data = transition = {...transition, ...body};
    else if (route === "/settings/scoped") data = [{key: "workflow_transition_mode", value: "guards", default: "off", set_here: true}];
    else if (route.endsWith("/sla")) data = {entries: []};
    else if (route.endsWith("/watchers")) data = {watching: false, watchers: []};
    else if (route.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (route === "/ai/status") data = {enabled: false, features: {}};
    else if (route === "/instance") data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (route.includes("/resolve")) data = {value: false};
    else if (route.endsWith("/timelogging")) data = {enabled: false};
    res.writeHead(status, {"content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0)});
    res.end(JSON.stringify(data)); return;
  }
  let file = path.resolve(dist, "." + url.pathname);
  if (!file.startsWith(dist) || !existsSync(file) || statSync(file).isDirectory()) file = path.join(dist, "index.html");
  const mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}[path.extname(file)] ?? "application/octet-stream";
  res.writeHead(200, {"content-type": mime}); res.end(readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const until = async (predicate, label) => {
  for (let i = 0; i < 150; i++) {if (await predicate()) return; await new Promise(resolve => setTimeout(resolve, 50));}
  throw Error(label);
};
let browser;
try {
  browser = await openBrowser({port: 18849, profile: await mkdtemp("/tmp/radd-resolvable-threads-"), scale: 1});
  const s = browser.session;
  const base = `http://127.0.0.1:${server.address().port}`;
  await s.navigate(base + "/issues/THR-1");
  await until(() => s.eval(`!!document.querySelector('[data-thread-resolution="thread"]')`), "thread lifecycle did not render");
  assert.equal(await s.eval(`!!document.querySelector('[data-thread-resolution="ordinary"]')`), false);
  // A thread is visibly a thread: a status chip and a framed card; an ordinary comment has neither.
  const look = await s.eval(`(() => {
    const card = (id) => document.querySelector('[data-comment-id="' + id + '"]');
    return {
      threadState: card("thread").dataset.thread,
      threadChip: card("thread").querySelector("[data-thread-state]")?.textContent.trim(),
      threadRule: getComputedStyle(card("thread")).borderLeftWidth,
      ordinaryState: card("ordinary").dataset.thread ?? null,
      ordinaryChip: !!card("ordinary").querySelector("[data-thread-state]"),
    };
  })()`);
  assert.deepEqual(look, {threadState: "unresolved", threadChip: "Unresolved thread", threadRule: "2px", ordinaryState: null, ordinaryChip: false});
  // A thread the rule keeps from this reader: marked, but no Resolve and no Reply and unresolve.
  assert.equal(await s.eval(`document.querySelector('[data-comment-id="locked"] [data-thread-state]').textContent.trim()`), "Resolved by A Manager");
  assert.equal(await s.eval(`!!document.querySelector('[data-thread-resolution="locked"]')`), false, "Resolve offered against the rule");
  await s.click('[data-thread-toggle="locked"]');
  await until(() => s.eval(`!!document.querySelector('[data-comment-replies="locked"] [contenteditable="true"]')`), "locked thread reply composer missing");
  assert.equal(await s.eval(`!!document.querySelector('[data-comment-replies="locked"] [data-reply-unresolve]')`), false, "Reply and unresolve offered against the rule");
  await s.click('[data-thread-toggle="locked"]');
  await s.click('[data-thread-toggle="thread"]');
  await until(() => s.eval(`document.body.innerText.includes('Checking the delivery now.')`), "reply history missing");
  failResolve = true;
  await s.click('[data-thread-resolution="thread"]');
  await until(() => s.eval(`document.body.innerText.includes('Thread resolution refused')`), "resolution error missing");
  assert.equal(comments[1].resolved_at, null);
  failResolve = false;
  const before = requests.filter(r => r.route.endsWith("/allowed-transitions")).length;
  await s.click('[data-thread-resolution="thread"]');
  await until(() => s.eval(`document.querySelector('[data-thread-resolution="thread"]').textContent.includes('Unresolve thread')
    && document.querySelector('[data-comment-id="thread"] [data-thread-state]').textContent.includes('Resolved by Review Owner')`), "resolution did not update controls");
  await until(() => requests.filter(r => r.route.endsWith("/allowed-transitions")).length > before, "resolution did not refresh transitions");
  assert(await s.eval(`document.body.innerText.includes('Checking the delivery now.')`));
  // A resolved thread still takes replies: Reply keeps it resolved, Reply and unresolve reopens it.
  await until(() => s.eval(`!!document.querySelector('[data-reply-unresolve]')`), "resolved thread offers no Reply and unresolve");
  assert.equal(await s.eval(`document.querySelector('[data-reply-unresolve]').disabled`), true, "Reply and unresolve lit before any text");
  await s.click('[data-reply-composer] [contenteditable="true"]');
  await s.send("Input.insertText", {text: "Late note"});
  await until(() => s.eval(`!document.querySelector('[data-reply-unresolve]').disabled`), "Reply and unresolve did not light up");
  await s.screenshot("/tmp/radd-thread-resolved.png");
  await s.click('[data-comment-replies="thread"] button[type="submit"]');
  await until(() => requests.some(r => r.method === "POST" && r.route === "/comments/thread/replies" && r.body.body.includes("Late note") && !r.body.unresolve), "plain reply not sent");
  await until(() => s.eval(`document.querySelector('[data-comment-id="thread"]').dataset.thread === "resolved"`), "plain reply reopened the thread");
  // Wait for the REMOUNT (composer key 0 → 1), not merely an editor: typing into the
  // outgoing one loses the text when the fresh editor replaces it.
  await until(() => s.eval(`document.querySelector('[data-reply-composer]')?.dataset.composerKey === "1"
    && !!document.querySelector('[data-reply-composer] [contenteditable="true"]')`), "reply composer did not reset");
  // A just-mounted editor can take focus before Milkdown's listener is attached,
  // so the first keystrokes never reach the draft; retry until the button lights.
  for (let attempt = 0; attempt < 5; attempt++) {
    await s.click('[data-reply-composer] [contenteditable="true"]');
    await s.send("Input.insertText", {text: "Not done after all"});
    if (await s.eval(`new Promise(r => setTimeout(() => r(!document.querySelector('[data-reply-unresolve]').disabled), 400))`)) break;
  }
  await until(() => s.eval(`!document.querySelector('[data-reply-unresolve]').disabled`), "second reply did not light up");
  await s.click('[data-reply-unresolve]');
  await until(() => requests.some(r => r.method === "POST" && r.route === "/comments/thread/replies" && r.body.unresolve === true), "reply-and-unresolve not sent");
  await until(() => s.eval(`document.querySelector('[data-comment-id="thread"]').dataset.thread === "unresolved"
    && !document.querySelector('[data-reply-unresolve]')`), "reply-and-unresolve did not reopen the thread");
  await s.click('[data-comment-filter="unresolved"]');
  await until(() => s.eval(`!document.querySelector('[data-comment-id="ordinary"]') && !!document.querySelector('[data-comment-id="thread"]')`), "unresolved filter incorrect");
  assert(requests.some(r => r.route.endsWith("/comments/feed") && r.query.includes("unresolved=true")));
  await s.click('[data-comment-filter="all"]');
  await until(() => s.eval(`!!document.querySelector('[data-comment-id="ordinary"]')`), "all comments not restored");
  // Close the reply composer so the issue composer is the sole editable editor.
  await s.click('[data-thread-toggle="thread"]');
  await until(() => s.eval(`!!document.querySelector('[contenteditable="true"]')`), "composer did not load");
  // No checkbox: Start thread sits beside Comment and lights up with the text, as Comment does.
  assert.equal(await s.eval(`!!document.querySelector('form input[type="checkbox"]')`), false, "composer still has a checkbox");
  assert.equal(await s.eval(`document.querySelector('[data-start-thread]').disabled`), true, "Start thread lit on an empty composer");
  await s.click('[contenteditable="true"]');
  await s.send("Input.insertText", {text: "Please verify the checklist"});
  await until(() => s.eval(`!document.querySelector('[data-start-thread]').disabled`), "Start thread did not light up");
  await s.click('[data-start-thread]');
  await until(() => comments.some(c => c.body.includes("Please verify") && c.is_thread), "composer did not create thread");
  await until(() => s.eval(`!!document.querySelector('[contenteditable="true"]') && document.querySelector('[data-start-thread]').disabled`), "fresh composer missing");
  await s.click('[contenteditable="true"]');
  await s.send("Input.insertText", {text: "An ordinary follow-up"});
  await until(() => s.eval(`Array.from(document.querySelectorAll("button")).some(b => b.textContent.trim() === "Comment" && !b.disabled)`), "comment submit did not enable");
  await s.click('button', text => text.trim() === "Comment");
  await until(() => comments.some(c => c.body.includes("ordinary follow-up") && !c.is_thread), "ordinary comment was marked as a thread");
  await s.screenshot("/tmp/radd-resolvable-threads.png");
  await s.navigate(base + "/p/THR/settings/workflow");
  await until(() => s.eval(`document.body.innerText.includes('All threads must be resolved')`), "workflow rule editor missing");
  // Wait for what the PAGE shows, not for the fixture to record the save: the
  // request lands before its response does, and a control is disabled until then —
  // a click in that window is (rightly) ignored.
  const box = (label) => `Array.from(document.querySelectorAll('label')).find(l => l.textContent.trim() === ${JSON.stringify(label)})?.querySelector('input')`;
  const shows = (label, checked) => until(() => s.eval(`(() => { const b = ${box(label)}; return !!b && !b.disabled && b.checked === ${checked}; })()`),
    `${label} did not settle ${checked ? "on" : "off"}`);
  await shows("All threads must be resolved", true);
  await s.click('label', text => text.trim() === "All threads must be resolved");
  await until(() => !transition.rules.some(r => r.check === "require_resolved_threads"), "rule toggle did not save");
  assert(transition.rules.some(r => r.check === "require_field"));
  assert(transition.rules.some(r => r.check === "require_approval"));
  await shows("All threads must be resolved", false);
  await s.click('label', text => text.trim() === "All threads must be resolved");
  await until(() => transition.rules.some(r => r.check === "require_resolved_threads"), "rule toggle did not re-enable");
  await shows("All threads must be resolved", true);
  await shows("Require approval", true);
  await s.click('label', text => text.trim() === "Require approval");
  await until(() => !transition.rules.some(r => r.check === "require_approval"), "approval toggle did not save");
  assert(transition.rules.some(r => r.check === "require_resolved_threads"), "approval edit dropped thread guard");
  await shows("Require approval", false);
  await until(() => s.eval(`!!document.querySelector('[aria-label="Remove condition"]:not([disabled])')`), "field condition not removable");
  await s.click('[aria-label="Remove condition"]');
  await until(() => !transition.rules.some(r => r.check === "require_field"), "field condition did not save");
  assert(transition.rules.some(r => r.check === "require_resolved_threads"), "field edit dropped thread guard");
  // RADD-1283: who can resolve — a default plus an issue-type rule, saved whole.
  await until(() => s.eval(`!!document.querySelector('[data-thread-resolution-settings]')`), "thread resolution settings missing");
  await s.click('[data-thread-resolution-settings] [data-add-thread-rule]');
  await until(() => threadPolicy.overrides.length === 1 && threadPolicy.overrides[0].issue_type_id === "type-bug", "issue-type rule not saved");
  await until(() => s.eval(`!!document.querySelector('[data-thread-rule="type-bug"]')`), "issue-type rule row missing");
  assert.equal(threadPolicy.default, "author");
  await s.screenshot("/tmp/radd-thread-workflow.png");
  console.log(JSON.stringify({passed: true, checks: ["ordinary comments have no lifecycle", "a thread looks like a thread", "the rule hides resolve controls", "reply keeps a resolved thread resolved", "reply and unresolve reopens", "replies persist", "resolution error", "resolve/reopen", "transition refresh", "unresolved filter", "composer creates explicit thread", "composer resets", "workflow preserves independent rules"], screenshots: ["/tmp/radd-thread-resolved.png", "/tmp/radd-resolvable-threads.png", "/tmp/radd-thread-workflow.png"]}));
} catch (error) {
  if (browser) {
    await browser.session.screenshot("/tmp/radd-threads-failure.png");
    console.error(await browser.session.eval("JSON.stringify({text:document.body.innerText,editors:Array.from(document.querySelectorAll(\"[contenteditable=true]\")).map(e=>e.outerHTML)})"));
    console.error(JSON.stringify(requests.filter(r => r.method !== "GET")));
  }
  throw error;
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
