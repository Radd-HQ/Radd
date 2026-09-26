/** RADD-1282: browser contract for issue threads and workflow rule preservation. */
import assert from "node:assert/strict";
import http from "node:http";
import {readFileSync, existsSync, statSync} from "node:fs";
import {mkdtemp} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {openBrowser} from "./lib/cdp.mjs";
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
// RADD-1401: a mailed body's signature is folded by the mailintake remote's `content.body` claim.
const mailDist = fileURLToPath(new URL("../../server/src/radd/modules/mailintake/ui/dist/", import.meta.url));
const user = {id: "admin", name: "Review Owner", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC"};
const project = {id: "project", key: "THR", name: "Thread review", permissions: ["*"], created_at: "2026-01-01"};
const states = ["Open", "Done"].map((name, i) => ({id: `state-${i}`, name, category: i ? "done" : "todo", category_key: i ? "done" : "todo", position: i, project_id: project.id}));
const item = {id: "issue", key: "THR-1", project_id: project.id, number: 1, title: "Review the delivery plan",
  description: "Discuss open questions before completing the work.\n\nBest regards,\nSam\n\nSender authentication warning", email_signature: "Best regards,\nSam", state: states[0],
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
const defaultWidgets = [{id:"w1", widget_type:"slq_count", title:"My open issues", width:7, height:360, collapsed:false, position:0, config:{q:"assignee = me"}}, {id:"w2", widget_type:"slq_count", title:"Another count", width:5, height:280, collapsed:false, position:1, config:{q:""}}];
let workWidgets = structuredClone(defaultWidgets);

let threadPolicy = {default: "author", overrides: []};
const issueTypes = [{id: "type-bug", project_id: "project", name: "Bug", color: "#ff0000", position: 0, is_default: true},
  {id: "type-review", project_id: "project", name: "Review", color: "#00ff00", position: 1, is_default: false}];
let failResolve = false;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname.startsWith("/plugins/mailintake/")) {
    const file = path.join(mailDist, url.pathname.slice("/plugins/mailintake/".length));
    if (!existsSync(file)) {res.writeHead(404); res.end(); return;}
    res.writeHead(200, {"content-type": "text/javascript"}); res.end(readFileSync(file)); return;
  }
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    requests.push({route, query: url.search, method: req.method, body});
    let data = [], status = 200;
    if (route === "/dashboards/my-work/widgets") { if (req.method === "PUT") workWidgets = body.widgets; data = workWidgets; }
    else if (route === "/dashboards/my-work/defaults") data = defaultWidgets;
    else if (route === "/mail/signatures/item/issue/restore") { item.email_signature=null; data={}; }
    else if (route === "/items/count") data = {count:3};
    else if (route === "/comments/reply/locate") data = {id:"reply", root_id:"thread", entity_type:"item", entity_id:"issue", anchored:false};
    else if (route === "/auth/me") data = user;
    else if (route.includes("capabilities")) data = {capabilities: [], nav: [], plugins: [...CORE_PLUGINS, "mailintake"],
      remotes: [{name: "mailintake", remote_entry: "/plugins/mailintake/remoteEntry.js", ui_api_version: "1.19.0"}]};
    else if (route.endsWith("/mail-contacts")) data = [];
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
  browser = await openBrowser({port: 18859, profile: await mkdtemp("/tmp/radd-issue-features-"), scale: 1});
  const s = browser.session;
  const base = `http://127.0.0.1:${server.address().port}`;
  const button = text => s.eval(`Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === ${JSON.stringify(text)})?.click()`);
  await s.navigate(base + "/issues/THR-1?comment=reply");
  await until(() => s.eval(`!!document.querySelector('[data-comment-id="reply"][data-comment-linked]')`), "linked reply not revealed");
  assert.equal(await s.eval(`document.querySelector('[data-thread-toggle="thread"]').getAttribute('aria-expanded')`), "true");
  assert.equal(await s.eval(`document.querySelector('[data-thread-toggle="locked"]').getAttribute('aria-expanded')`), "false");
  assert.equal(await s.eval(`!!document.querySelector('[data-comment-replies="thread"] [contenteditable=true]')`), false, "reading replies opened composer");
  assert.equal(await s.eval(`getComputedStyle(document.querySelector('[data-thread-toggle="thread"]')).fontSize`), "14px");
  await s.click('[data-thread-toggle="locked"]');
  assert.equal(await s.eval(`document.querySelector('[data-thread-toggle="thread"]').getAttribute('aria-expanded')`), "true", "opening another thread closed first");
  await new Promise(resolve => setTimeout(resolve, 4500));
  assert(await s.eval(`!!document.querySelector('[data-comment-id="reply"][data-comment-linked]')`), "highlight disappeared before ten seconds");
  await until(() => s.eval(`!!document.querySelector('[aria-label="Emoji and symbols"]')`), "symbol picker unavailable");
  await s.click('[aria-label="Emoji and symbols"]');
  await s.click('[aria-label="warning attention"]');
  await until(() => s.eval(`Array.from(document.querySelectorAll('[contenteditable=true]')).some(e => e.innerText.includes('⚠'))`), "symbol did not enter editor");
  assert(await s.eval(`document.body.innerText.includes('Sender authentication warning')`), 'signature hid authentication warning');
  assert.equal(await s.eval(`document.body.innerText.includes('Best regards,')`), false, 'signature not initially collapsed');
  await s.eval(`Array.from(document.querySelectorAll('summary')).find(e=>e.textContent==='Show signature').click()`);
  await until(() => s.eval(`document.body.innerText.includes('Best regards,')`), 'signature did not expand');
  await button('Not a signature');
  await until(() => s.eval(`!Array.from(document.querySelectorAll('summary')).some(e=>e.textContent==='Show signature')`), 'signature annotation not restored');
  await s.screenshot('/tmp/radd-issue-features-comments.png');
  await new Promise(resolve => setTimeout(resolve, 5700));
  assert.equal(await s.eval(`!!document.querySelector('[data-comment-id="reply"][data-comment-linked]')`), false, "highlight never cleared");
  await s.navigate(base + '/');
  await until(() => s.eval(`!!document.querySelector('[data-widget-id="w1"]')`), "My Work widgets missing");
  assert.equal(await s.eval(`!!document.querySelector('[aria-label="Widget width"]')`), false, "resize controls escaped edit mode");
  await button('Customize');
  await until(() => s.eval(`!!document.querySelector('[aria-label="Widget width"]')`), "edit sizing missing");
  await s.click('[aria-label="Widget width"]');
  await s.send('Input.dispatchKeyEvent', {type:'keyDown', key:'ArrowUp', code:'ArrowUp'});
  await s.send('Input.dispatchKeyEvent', {type:'keyUp', key:'ArrowUp', code:'ArrowUp'});
  await until(() => s.eval(`document.querySelector('[aria-label="Widget width"]').value === '8'`), 'keyboard resize failed');
  await button('Cancel');
  assert.equal(workWidgets[0].width,7, 'Cancel saved layout');
  await button('Customize');
  // Actual mouse drag on the corner changes both dimensions.
  const box = await s.eval(`(() => { const r = document.querySelector('[data-widget-id="w1"] .cursor-nwse-resize').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
  await s.send('Input.dispatchMouseEvent',{type:'mousePressed',x:box.x,y:box.y,button:'left',clickCount:1});
  await s.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:box.x+100,y:box.y+80,button:'left',buttons:1});
  await s.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:box.x+100,y:box.y+80,button:'left',clickCount:1});
  await button('Save');
  await until(() => workWidgets[0].height === 440 && workWidgets[0].width > 7, 'drag resize did not persist');
  await until(() => s.eval(`!document.querySelector('[aria-label="Widget width"]')`), "Save did not leave edit mode");
  await s.click('[data-widget-id="w1"] button[aria-expanded]');
  await until(() => workWidgets[0].collapsed, 'normal-mode collapse not persisted');
  await s.navigate(base + '/');
  await until(() => s.eval(`document.querySelector('[data-widget-id="w1"]')?.dataset.collapsed === 'true'`), 'saved collapsed state did not reload');
  await s.screenshot('/tmp/radd-issue-features-dashboard.png');
  console.log(JSON.stringify({passed:true, checks:['resolution defaults','independent threads','composer on demand','readable reply control','10 second highlight','Unicode symbol insertion','edit-only resize','cancel leaves server unchanged','pointer resize saved','collapse saved across reload']}));
} catch(error) {
  if(browser) { await browser.session.screenshot('/tmp/radd-issue-features-failure.png'); console.error(await browser.session.eval('document.body.innerText')); }
  throw error;
} finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
