/** Linked-comment reveal, one-open-thread toggles, symbol picker, signature collapse (RADD-1337), reply edit/delete
 *  (RADD-1477: the author's or a manager's, absent for anyone else; a root with replies is refused before any request)
 *  and My Work widget resize, against a fixture API. */
import assert from "node:assert/strict";
import {mkdtemp} from "node:fs/promises";
import {openBrowser, until} from "./lib/cdp.mjs";
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";
import {serveBuiltSpa} from "./lib/spa-server.mjs";

// RADD-1401: a mailed body's signature is folded by the mailintake remote's `content.body` claim.
const user = {id: "admin", name: "Review Owner", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC"};
const other = {id: "other", name: "Someone Else", email: "other@example.test"};
const project = {id: "project", key: "THR", name: "Thread review", permissions: ["*"], created_at: "2026-01-01"};
// RADD-1477: the same person as a plain member — comment.write, no project.manage — for the "not yours" case.
const MEMBER_PERMISSIONS = ["item.read", "item.update", "comment.write", "comment.read_internal"];
let manager = true;
const states = ["Open", "Done"].map((name, i) => ({id: `state-${i}`, name, category: i ? "done" : "todo", category_key: i ? "done" : "todo", position: i, project_id: project.id}));
const item = {id: "issue", key: "THR-1", project_id: project.id, number: 1, title: "Review the delivery plan",
  description: "Discuss open questions before completing the work.\n\nBest regards,\nSam\n\nSender authentication warning", email_signature: "Best regards,\nSam", state: states[0],
  priority: "normal", kind: "issue", labels: [], custom_fields: {},
  capabilities: {can_update: true, can_comment: true, can_transition: true},
  links: {incoming: [], outgoing: []}, created_at: "2026-01-01", updated_at: "2026-01-01"};
let comments = [{id: "ordinary", body: "An informational comment with a reply", is_thread: false, reply_count: 1},
  {id: "thread", body: "Has the delivery been verified?", is_thread: true, reply_count: 2, can_resolve: true},
  // RADD-1283: the project's rule does not let this reader resolve this one.
  {id: "locked", body: "Managers sign this off", is_thread: true, reply_count: 1, can_resolve: false,
    resolved_at: "2026-09-20T09:00:00Z", resolver_name: "A Manager"}].map(row => ({...row, entity_type: "item", entity_id: item.id, author: user, visibility: "public", visible_to_teams: [], anchor: null, parent_comment_id: null, resolved_at: null, resolved_by: null, created_at: "2026-01-01", updated_at: "2026-01-01", ...row}));
const replies = [{...comments[0], id: "reply", parent_comment_id: "thread", body: "Checking the delivery now.", is_thread: false},
  {...comments[0], id: "reply-other", parent_comment_id: "thread", body: "Someone else's answer.", is_thread: false, author: other}];
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
const spa = await serveBuiltSpa(async (req, res, url) => {
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
    else if (route === "/auth/me") data = manager ? user : {...user, global_role: "member", permissions: []};
    // RADD-1477: edit and delete, on a comment or a reply; a root with replies is refused with the reason.
    else if (/^\/comments\/[^/]+$/.test(route) && req.method === "PATCH") {
      const id = route.split("/")[2];
      const edit = (row) => (row.id === id ? {...row, ...body, updated_at: "2026-01-02"} : row);
      comments = comments.map(edit); replies.splice(0, replies.length, ...replies.map(edit));
      data = [...comments, ...replies].find(c => c.id === id);
    }
    else if (/^\/comments\/[^/]+$/.test(route) && req.method === "DELETE") {
      const id = route.split("/")[2];
      if (replies.some(r => r.parent_comment_id === id)) { status = 409; data = {detail: "comment: This comment has replies; delete them first"}; }
      else {
        const at = replies.findIndex(r => r.id === id);
        if (at >= 0) { const [gone] = replies.splice(at, 1); comments = comments.map(c => c.id === gone.parent_comment_id ? {...c, reply_count: replies.filter(r => r.parent_comment_id === c.id).length} : c); }
        else comments = comments.filter(c => c.id !== id);
        status = 204; data = {};
      }
    }
    else if (route.includes("capabilities")) data = {capabilities: [], nav: [], plugins: [...CORE_PLUGINS, "mailintake"],
      remotes: [{name: "mailintake", remote_entry: "/plugins/mailintake/remoteEntry.js", ui_api_version: "2.0.0"}]};
    else if (route.endsWith("/mail-contacts")) data = [];
    else if (route === "/projects/summary") data = {total: 1, related_count: 0, permissions: ["*"]};
    else if (route === "/page-spaces/summary") data = {total: 0, permissions: []};
    else if (route === "/projects/project" || route === "/projects/by-key/THR") data = manager ? project : {...project, permissions: MEMBER_PERMISSIONS};
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
    else if (route.endsWith("/replies")) data = {comments: replies.filter(r => r.parent_comment_id === route.split("/")[2]), older_cursor: null};
    else if (route.endsWith("/allowed-transitions")) data = {mode: "guards", targets: states.map(s => ({state_id: s.id, allowed: s.id === states[0].id || !comments.some(c => c.is_thread && !c.resolved_at), failures: []}))};
    else if (route === "/projects/project/transitions") data = [transition];
    else if (route === "/projects/project/thread-resolution") data = threadPolicy = req.method === "PUT" ? body : threadPolicy;
    else if (route === "/issue-types") data = issueTypes;
    else if (route === "/transitions/transition" && req.method === "PATCH") data = transition = {...transition, ...body};
    else if (route.endsWith("/sla")) data = {entries: []};
    else if (route.endsWith("/watchers")) data = {watching: false, watchers: []};
    else if (route.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (route === "/ai/status") data = {enabled: false, features: {}};
    else if (route === "/instance") data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (route.includes("/resolve")) data = {value: false};
    else if (route.endsWith("/timelogging")) data = {enabled: false};
    res.writeHead(status, {"content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0)});
    res.end(JSON.stringify(data)); return true;
  }
});
let browser;
try {
  browser = await openBrowser({port: 18859, profile: await mkdtemp("/tmp/radd-issue-features-"), scale: 1});
  const s = browser.session;
  const base = spa.origin;
  const button = text => s.eval(`Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === ${JSON.stringify(text)})?.click()`);
  await s.navigate(base + "/issues/THR-1?comment=reply");
  await until(s, () => s.eval(`!!document.querySelector('[data-comment-id="reply"][data-comment-linked]')`), "linked reply not revealed");
  assert.equal(await s.eval(`document.querySelector('[data-thread-toggle="thread"]').getAttribute('aria-expanded')`), "true");
  assert.equal(await s.eval(`document.querySelector('[data-thread-toggle="locked"]').getAttribute('aria-expanded')`), "false");
  assert.equal(await s.eval(`!!document.querySelector('[data-comment-replies="thread"] [contenteditable=true]')`), false, "reading replies opened composer");
  // RADD-1335's readable controls, on the kit (RADD-1448): the disclosure and the Reply action are
  // full-size buttons — 32px targets with 13px words.
  const control = (selector) => `(() => { const b = document.querySelector('${selector}'); return b && [getComputedStyle(b).fontSize, b.getBoundingClientRect().height]; })()`;
  assert.deepEqual(await s.eval(control('[data-thread-toggle="thread"]')), ["13px", 32]);
  assert.deepEqual(await s.eval(control('[data-open-reply="thread"]')), ["13px", 32]);
  await s.click('[data-thread-toggle="locked"]');
  assert.equal(await s.eval(`document.querySelector('[data-thread-toggle="thread"]').getAttribute('aria-expanded')`), "true", "opening another thread closed first");
  await new Promise(resolve => setTimeout(resolve, 4500));
  assert(await s.eval(`!!document.querySelector('[data-comment-id="reply"][data-comment-linked]')`), "highlight disappeared before ten seconds");
  // The composer is hidden until asked for (RADD-1448): open it to reach its toolbar.
  await s.click('[data-open-comment]');
  await until(s, () => s.eval(`!!document.querySelector('[aria-label="Emoji and symbols"]')`), "symbol picker unavailable");
  await s.click('[aria-label="Emoji and symbols"]');
  await s.click('[aria-label="warning attention"]');
  await until(s, () => s.eval(`Array.from(document.querySelectorAll('[contenteditable=true]')).some(e => e.innerText.includes('⚠'))`), "symbol did not enter editor");
  assert(await s.eval(`document.body.innerText.includes('Sender authentication warning')`), 'signature hid authentication warning');
  assert.equal(await s.eval(`document.body.innerText.includes('Best regards,')`), false, 'signature not initially collapsed');
  await s.eval(`Array.from(document.querySelectorAll('summary')).find(e=>e.textContent==='Show signature').click()`);
  await until(s, () => s.eval(`document.body.innerText.includes('Best regards,')`), 'signature did not expand');
  await button('Not a signature');
  await until(s, () => s.eval(`!Array.from(document.querySelectorAll('summary')).some(e=>e.textContent==='Show signature')`), 'signature annotation not restored');
  await s.screenshot('/tmp/radd-issue-features-comments.png');
  await new Promise(resolve => setTimeout(resolve, 5700));
  assert.equal(await s.eval(`!!document.querySelector('[data-comment-id="reply"][data-comment-linked]')`), false, "highlight never cleared");

  // RADD-1477: a reply is edited and deleted by its author like a comment. Each rendered body swaps
  // its placeholder for the viewer as it nears the viewport, moving what is below it: click a
  // control once it has stopped moving, or the click lands where it used to be.
  const steadyClick = async (selector) => {
    await until(s, () => s.eval(`new Promise((resolve) => {
      const at = () => document.querySelector(${JSON.stringify(selector)})?.getBoundingClientRect().top;
      const before = at();
      setTimeout(() => resolve(before !== undefined && at() === before
        && !document.querySelector('[data-comment-id] [aria-busy="true"]')), 250);
    })`), `${selector} kept moving`);
    return s.click(selector);
  };
  const escape = async () => {
    await s.send("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27});
    await s.send("Input.dispatchKeyEvent", {type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27});
  };
  const editorText = `document.querySelector('[data-comment-edit="reply"] [contenteditable="true"]')?.textContent`;
  await until(s, () => s.eval(`!!document.querySelector('[data-comment-id="reply"] [aria-label="Edit reply"]')
    && !!document.querySelector('[data-comment-id="reply"] [aria-label="Delete reply"]')`), "own reply offers no Edit and Delete");
  // A manager acts on anyone's reply.
  assert(await s.eval(`!!document.querySelector('[data-comment-id="reply-other"] [aria-label="Edit reply"]')`), "a manager cannot edit another person's reply");
  const patchesBefore = requests.filter(r => r.method === "PATCH").length;
  await steadyClick('[data-comment-id="reply"] [aria-label="Edit reply"]');
  await until(s, () => s.eval(`(${editorText} ?? "").includes("Checking the delivery now.")`), "Edit did not open the reply's editor on its text");
  // A just-mounted editor can take focus before Milkdown's listener is attached: retry until the text lands.
  for (let attempt = 0; attempt < 5; attempt++) {
    await steadyClick('[data-comment-edit="reply"] [contenteditable="true"]');
    await s.send("Input.insertText", {text: " Edited."});
    if (await s.eval(`new Promise(r => setTimeout(() => r((${editorText} ?? "").includes("Edited.")), 400))`)) break;
  }
  await until(s, () => s.eval(`(${editorText} ?? "").includes("Edited.")`), "typing did not reach the reply draft");
  // Escape closes the editor without a request and keeps the draft: Edit again shows it.
  await escape();
  await until(s, () => s.eval(`!document.querySelector('[data-comment-edit="reply"]') && document.querySelector('[data-comment-id="reply"]').innerText.includes("Checking the delivery now.")`), "Escape did not close the reply editor");
  assert.equal(requests.filter(r => r.method === "PATCH").length, patchesBefore, "Escape sent a PATCH");
  await steadyClick('[data-comment-id="reply"] [aria-label="Edit reply"]');
  await until(s, () => s.eval(`(${editorText} ?? "").includes("Edited.")`), "Escape lost the reply draft");
  await steadyClick('[data-comment-edit="reply"] [data-comment-edit-save]');
  await until(s, () => requests.some(r => r.method === "PATCH" && r.route === "/comments/reply" && r.body.body.includes("Edited.")), "Save did not PATCH the reply");
  await until(s, () => s.eval(`!document.querySelector('[data-comment-edit="reply"]')
    && document.querySelector('[data-comment-id="reply"]')?.innerText.includes("Edited.")
    && document.querySelector('[data-comment-id="reply"]')?.innerText.includes("(edited)")`), "the saved reply did not redraw as edited");
  assert.equal(requests.filter(r => r.method === "PATCH").length, patchesBefore + 1, "Save sent more than one PATCH");
  // Delete asks first; confirmed, the reply goes and the thread's disclosure counts one fewer.
  await steadyClick('[data-comment-id="reply"] [aria-label="Delete reply"]');
  await until(s, () => s.eval(`document.querySelector('[role="dialog"]')?.innerText.includes("Delete this reply?")`), "Delete did not ask");
  await s.click('[role="dialog"] button', text => text.trim() === "Delete");
  await until(s, () => requests.some(r => r.method === "DELETE" && r.route === "/comments/reply"), "confirming did not DELETE the reply");
  await until(s, () => s.eval(`!document.querySelector('[data-comment-id="reply"]')
    && document.querySelector('[data-thread-toggle="thread"]')?.textContent.trim() === "Hide 1 reply"`), "the deleted reply lingered, or the count did not follow");
  // A root that still has a reply is refused before any request: the dialog says what to do instead.
  await steadyClick('[data-comment-id="thread"] [aria-label="Delete comment"]');
  await until(s, () => s.eval(`document.querySelector('[role="dialog"]')?.innerText.includes("Delete them first")`), "deleting a root with replies did not explain itself");
  assert(!requests.some(r => r.method === "DELETE" && r.route === "/comments/thread"), "a root with replies was sent for deletion");
  await s.click('[role="dialog"] button', text => text.trim() === "OK");
  await until(s, () => s.eval(`!document.querySelector('[role="dialog"]')`), "the notice did not close");
  await s.screenshot('/tmp/radd-issue-features-reply-actions.png');
  // As a plain member: one's own reply keeps its actions, someone else's offers none.
  manager = false;
  await s.navigate(base + "/issues/THR-1");
  await until(s, () => s.eval(`!!document.querySelector('[data-comment-id="reply-other"]') && !!document.querySelector('[data-comment-id="ordinary"] [aria-label="Edit comment"]')`), "the member view did not render");
  assert.equal(await s.eval(`!!document.querySelector('[data-comment-id="reply-other"] [aria-label="Edit reply"]')
    || !!document.querySelector('[data-comment-id="reply-other"] [aria-label="Delete reply"]')`), false, "a member may act on another person's reply");
  manager = true;
  await s.navigate(base + '/');
  await until(s, () => s.eval(`!!document.querySelector('[data-widget-id="w1"]')`), "My Work widgets missing");
  assert.equal(await s.eval(`!!document.querySelector('[aria-label="Widget width"]')`), false, "resize controls escaped edit mode");
  await button('Customize');
  await until(s, () => s.eval(`!!document.querySelector('[aria-label="Widget width"]')`), "edit sizing missing");
  await s.click('[aria-label="Widget width"]');
  await s.send('Input.dispatchKeyEvent', {type:'keyDown', key:'ArrowUp', code:'ArrowUp'});
  await s.send('Input.dispatchKeyEvent', {type:'keyUp', key:'ArrowUp', code:'ArrowUp'});
  await until(s, () => s.eval(`document.querySelector('[aria-label="Widget width"]').value === '8'`), 'keyboard resize failed');
  await button('Cancel');
  assert.equal(workWidgets[0].width,7, 'Cancel saved layout');
  await button('Customize');
  // Actual mouse drag on the corner changes both dimensions.
  const box = await s.eval(`(() => { const r = document.querySelector('[data-widget-id="w1"] .cursor-nwse-resize').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
  await s.send('Input.dispatchMouseEvent',{type:'mousePressed',x:box.x,y:box.y,button:'left',clickCount:1});
  await s.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:box.x+100,y:box.y+80,button:'left',buttons:1});
  await s.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:box.x+100,y:box.y+80,button:'left',clickCount:1});
  await button('Save');
  await until(s, () => workWidgets[0].height === 440 && workWidgets[0].width > 7, 'drag resize did not persist');
  await until(s, () => s.eval(`!document.querySelector('[aria-label="Widget width"]')`), "Save did not leave edit mode");
  await s.click('[data-widget-id="w1"] button[aria-expanded]');
  await until(s, () => workWidgets[0].collapsed, 'normal-mode collapse not persisted');
  await s.navigate(base + '/');
  await until(s, () => s.eval(`document.querySelector('[data-widget-id="w1"]')?.dataset.collapsed === 'true'`), 'saved collapsed state did not reload');
  await s.screenshot('/tmp/radd-issue-features-dashboard.png');
  console.log(JSON.stringify({passed:true, checks:['resolution defaults','independent threads','composer on demand','readable reply control','10 second highlight','Unicode symbol insertion',
    'own reply offers Edit and Delete','a manager edits anyone\'s reply','Edit opens the reply editor on its text','Escape closes without a request and keeps the draft','Save sends one PATCH and redraws as edited',
    'Delete asks, then the reply goes and the count follows','a root with replies is refused before any request','a member sees no actions on another person\'s reply',
    'edit-only resize','cancel leaves server unchanged','pointer resize saved','collapse saved across reload']}));
} catch(error) {
  if(browser) { await browser.session.screenshot('/tmp/radd-issue-features-failure.png'); console.error(await browser.session.eval('document.body.innerText')); }
  throw error;
} finally { await browser?.close(); await spa.close(); }
