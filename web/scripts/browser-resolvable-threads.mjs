/** RADD-1282: browser contract for issue threads and workflow rule preservation.
 * RADD-1383: the approval rule's editor is the ACTUAL approvals remote (served from its
 * ui/dist), contributed into the transitions editor's rule slot; withdrawn, the rule it
 * served stays visible as a fail-closed notice the admin can remove.
 * RADD-1478: an ordinary comment offers "Start thread from this comment" (a thread and a
 * reply do not); one PATCH redraws it as an unresolved thread with its resolve controls and
 * no reload, and a refusal is shown on the comment. */
import assert from "node:assert/strict";
import {mkdtemp} from "node:fs/promises";
import {openBrowser, until} from "./lib/cdp.mjs";
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";
import {serveBuiltSpa} from "./lib/spa-server.mjs";

let approvalsEnabled = true;
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
    resolved_at: "2026-09-20T09:00:00Z", resolver_name: "A Manager"},
  // RADD-1448: nobody answered this one — it shows no disclosure and no empty replies area.
  {id: "quiet", body: "A note nobody answered", is_thread: false, reply_count: 0}].map(row => ({...row, entity_type: "item", entity_id: item.id, author: user, visibility: "public", visible_to_teams: [], anchor: null, parent_comment_id: null, resolved_at: null, resolved_by: null, created_at: "2026-01-01", updated_at: "2026-01-01", ...row}));
const reply = (parent, id, body) => ({...comments[0], id, parent_comment_id: parent, body, is_thread: false, reply_count: 0});
const replies = [reply("ordinary", "reply-ordinary", "Noted, thanks."), reply("thread", "reply", "Checking the delivery now."),
  reply("locked", "reply-locked", "Signed off last week.")];
let transition = {id: "transition", project_id: project.id, from_state_id: null, to_state_id: states[1].id, position: 0,
  applies_when: [], rules: [{check: "require_field", params: {kind: "builtin", key: "assignee", op: "set"}},
    {check: "require_approval", params: {approvers: [{kind: "user", id: user.id, name: user.name}]}},
    {check: "require_resolved_threads", params: {}}]};
const requests = [];
let threadPolicy = {default: "author", overrides: []};
const issueTypes = [{id: "type-bug", project_id: "project", name: "Bug", color: "#ff0000", position: 0, is_default: true},
  {id: "type-review", project_id: "project", name: "Review", color: "#00ff00", position: 1, is_default: false}];
let failResolve = false;
let failConvert = false;
const spa = await serveBuiltSpa(async (req, res, url) => {
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    requests.push({route, query: url.search, method: req.method, body});
    let data = [], status = 200;
    if (route === "/auth/me") data = user;
    else if (route.includes("capabilities")) data = {capabilities: [], nav: [], ui: [],
      plugins: [...CORE_PLUGINS, ...(approvalsEnabled ? ["approvals"] : [])],
      remotes: approvalsEnabled ? [{name: "approvals", remote_entry: "/plugins/approvals/remoteEntry.js", ui_api_version: "2.0.0"}] : []};
    else if (route === "/items/issue/approvals") data = {live: [], history: [], requestable_to_states: []};
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
    // RADD-1478: `is_thread: true` on PATCH turns a comment into an unresolved thread the caller may resolve.
    else if (/^\/comments\/[^/]+$/.test(route) && req.method === "PATCH") {
      if (failConvert) {status = 409; data = {detail: "comment: Thread conversion refused"};}
      else {
        const id = route.split("/")[2];
        comments = comments.map(c => c.id === id ? {...c, ...body, updated_at: "2026-01-02",
          ...(body.is_thread ? {resolved_at: null, resolved_by: null, resolver_name: null, can_resolve: true} : {})} : c);
        data = comments.find(c => c.id === id);
      }
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
      data = reply(id, `reply-${replies.length}`, body.body);
      replies.push(data);
      comments = comments.map(c => c.id === id ? {...c, reply_count: replies.filter(r => r.parent_comment_id === id).length,
        ...(body.unresolve ? {resolved_at: null, resolved_by: null, resolver_name: null} : {})} : c);
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
  browser = await openBrowser({port: 18849, profile: await mkdtemp("/tmp/radd-resolvable-threads-"), scale: 1});
  const s = browser.session;
  // RADD-1448: replies now render under every open comment, and each rendered body swaps its plain
  // placeholder for the viewer as it nears the viewport — moving everything below it, the composer
  // included. Click a control once it has stopped moving, or the click lands where it used to be.
  const steadyClick = async (selector) => {
    await until(s, () => s.eval(`new Promise((resolve) => {
      const at = () => document.querySelector(${JSON.stringify(selector)})?.getBoundingClientRect().top;
      const before = at();
      setTimeout(() => resolve(before !== undefined && at() === before
        && !document.querySelector('[data-comment-id] [aria-busy="true"]')), 250);
    })`), `${selector} kept moving`);
    return s.click(selector);
  };
  const base = spa.origin;
  await s.navigate(base + "/issues/THR-1");
  await until(s, () => s.eval(`!!document.querySelector('[data-thread-resolution="thread"]')`), "thread lifecycle did not render");
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
  // RADD-1448: replies show without a click; the disclosure is there only when replies are, and
  // Reply is an action beside it — never the toggle.
  await until(s, () => s.eval(`document.querySelector('[data-comment-replies="thread"]')?.innerText.includes('Checking the delivery now.')
    && document.querySelector('[data-comment-replies="ordinary"]')?.innerText.includes('Noted, thanks.')`), "replies are not visible by default");
  const footers = await s.eval(`(() => {
    const toggle = (id) => document.querySelector('[data-thread-toggle="' + id + '"]');
    const state = (id) => toggle(id) && [toggle(id).getAttribute("aria-expanded"), toggle(id).textContent.trim()];
    return {
      thread: state("thread"), ordinary: state("ordinary"), locked: state("locked"),
      lockedHidden: !document.body.innerText.includes("Signed off last week."),
      quietToggle: !!toggle("quiet"), quietArea: !!document.querySelector('[data-comment-replies="quiet"]'),
      quietReply: document.querySelector('[data-open-reply="quiet"]')?.textContent.trim() ?? null,
      replyIsNoDisclosure: [...document.querySelectorAll("[data-open-reply]")].every((b) => !b.hasAttribute("aria-expanded")),
    };
  })()`);
  assert.deepEqual(footers, {thread: ["true", "Hide 1 reply"], ordinary: ["true", "Hide 1 reply"], locked: ["false", "Show 1 reply · resolved"],
    lockedHidden: true, quietToggle: false, quietArea: false, quietReply: "Reply", replyIsNoDisclosure: true});
  // One click on Reply opens a focused composer with ONE submit; Escape closes it back to Reply.
  await steadyClick('[data-open-reply="quiet"]');
  await until(s, () => s.eval(`!!document.querySelector('[data-comment-replies="quiet"] [data-reply-composer] [contenteditable="true"]')
    && !!document.activeElement?.closest('[data-reply-composer]')`), "one click on Reply did not open a focused composer");
  assert.deepEqual(await s.eval(`[...document.querySelectorAll('[data-comment-replies="quiet"] button[type="submit"]')].map((b) => b.textContent.trim())`), ["Reply"]);
  await s.send("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27});
  await s.send("Input.dispatchKeyEvent", {type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27});
  await until(s, () => s.eval(`!document.querySelector('[data-reply-composer]') && document.activeElement?.dataset.openReply === "quiet"
    && !document.querySelector('[data-comment-replies="quiet"]')`), "Escape did not close the composer back to its Reply button");
  // A thread the rule keeps from this reader: marked, but no Resolve and no Reply and unresolve.
  assert.equal(await s.eval(`document.querySelector('[data-comment-id="locked"] [data-thread-state]').textContent.trim()`), "Resolved by A Manager");
  assert.equal(await s.eval(`!!document.querySelector('[data-thread-resolution="locked"]')`), false, "Resolve offered against the rule");
  // Reply on a collapsed (resolved) thread opens its replies with the composer under them.
  await steadyClick('[data-open-reply="locked"]');
  await until(s, () => s.eval(`!!document.querySelector('[data-comment-replies="locked"] [contenteditable="true"]')
    && document.querySelector('[data-comment-replies="locked"]').innerText.includes("Signed off last week.")
    && document.querySelector('[data-thread-toggle="locked"]').getAttribute("aria-expanded") === "true"`), "locked thread reply composer missing");
  assert.equal(await s.eval(`!!document.querySelector('[data-comment-replies="locked"] [data-reply-unresolve]')`), false, "Reply and unresolve offered against the rule");
  await steadyClick('[data-comment-replies="locked"] [data-reply-cancel]');
  await until(s, () => s.eval(`!document.querySelector('[data-reply-composer]') && document.activeElement?.dataset.openReply === "locked"`), "Cancel did not return to Reply");
  failResolve = true;
  await steadyClick('[data-thread-resolution="thread"]');
  await until(s, () => s.eval(`document.body.innerText.includes('Thread resolution refused')`), "resolution error missing");
  assert.equal(comments[1].resolved_at, null);
  failResolve = false;
  const before = requests.filter(r => r.route.endsWith("/allowed-transitions")).length;
  await steadyClick('[data-thread-resolution="thread"]');
  await until(s, () => s.eval(`document.querySelector('[data-thread-resolution="thread"]').textContent.includes('Unresolve thread')
    && document.querySelector('[data-comment-id="thread"] [data-thread-state]').textContent.includes('Resolved by Review Owner')`), "resolution did not update controls");
  await until(s, () => requests.filter(r => r.route.endsWith("/allowed-transitions")).length > before, "resolution did not refresh transitions");
  // Resolving collapses the thread: its toggle says why.
  assert.deepEqual(await s.eval(`(() => { const t = document.querySelector('[data-thread-toggle="thread"]'); return [t.getAttribute('aria-expanded'), t.textContent.trim()]; })()`),
    ["false", "Show 1 reply · resolved"]);
  await steadyClick('[data-open-reply="thread"]');
  // A resolved thread still takes replies: Reply keeps it resolved, Reply and unresolve reopens it.
  await until(s, () => s.eval(`!!document.querySelector('[data-reply-unresolve]')`), "resolved thread offers no Reply and unresolve");
  assert.equal(await s.eval(`document.querySelector('[data-reply-unresolve]').disabled`), true, "Reply and unresolve lit before any text");
  await steadyClick('[data-reply-composer] [contenteditable="true"]');
  await s.send("Input.insertText", {text: "Late note"});
  await until(s, () => s.eval(`!document.querySelector('[data-reply-unresolve]').disabled`), "Reply and unresolve did not light up");
  await s.screenshot("/tmp/radd-thread-resolved.png");
  await steadyClick('[data-comment-replies="thread"] button[type="submit"]');
  await until(s, () => requests.some(r => r.method === "POST" && r.route === "/comments/thread/replies" && r.body.body.includes("Late note") && !r.body.unresolve), "plain reply not sent");
  await until(s, () => s.eval(`document.querySelector('[data-comment-id="thread"]').dataset.thread === "resolved"`), "plain reply reopened the thread");
  // Posting closes the composer, and the reply appears under the thread.
  await until(s, () => s.eval(`!document.querySelector('[data-reply-composer]')
    && document.querySelector('[data-comment-replies="thread"]')?.innerText.includes("Late note")`), "posting did not close the composer onto the new reply");
  await steadyClick('[data-open-reply="thread"]');
  // A just-mounted editor can take focus before Milkdown's listener is attached,
  // so the first keystrokes never reach the draft; retry until the button lights.
  await until(s, () => s.eval(`!!document.querySelector('[data-reply-composer] [contenteditable="true"]')`), "reply composer did not reopen");
  for (let attempt = 0; attempt < 5; attempt++) {
    await steadyClick('[data-reply-composer] [contenteditable="true"]');
    await s.send("Input.insertText", {text: "Not done after all"});
    if (await s.eval(`new Promise(r => setTimeout(() => r(!document.querySelector('[data-reply-unresolve]').disabled), 400))`)) break;
  }
  await until(s, () => s.eval(`!document.querySelector('[data-reply-unresolve]').disabled`), "second reply did not light up");
  await steadyClick('[data-reply-unresolve]');
  await until(s, () => requests.some(r => r.method === "POST" && r.route === "/comments/thread/replies" && r.body.unresolve === true), "reply-and-unresolve not sent");
  await until(s, () => s.eval(`document.querySelector('[data-comment-id="thread"]').dataset.thread === "unresolved"
    && !document.querySelector('[data-reply-unresolve]')`), "reply-and-unresolve did not reopen the thread");
  await s.click('[data-comment-filter="unresolved"]');
  await until(s, () => s.eval(`!document.querySelector('[data-comment-id="ordinary"]') && !!document.querySelector('[data-comment-id="thread"]')`), "unresolved filter incorrect");
  assert(requests.some(r => r.route.endsWith("/comments/feed") && r.query.includes("unresolved=true")));
  await s.click('[data-comment-filter="all"]');
  await until(s, () => s.eval(`!!document.querySelector('[data-comment-id="ordinary"]')`), "all comments not restored");
  // RADD-1448: the composer is hidden until asked for — a row of two buttons, and no editor.
  const composerRow = await s.eval(`(() => {
    const row = document.querySelector('[data-comment-composer="closed"]');
    return row && {buttons: [...row.querySelectorAll("button")].map((b) => b.textContent.trim()),
      editors: document.querySelectorAll('[data-comment-composer] [contenteditable="true"]').length,
      hint: row.querySelector("[data-start-thread]")?.title};
  })()`);
  assert.deepEqual(composerRow, {buttons: ["Comment", "Start thread"], editors: 0,
    hint: "A thread can be resolved: use it for a question that needs an answer"});
  await steadyClick('[data-start-thread]');
  const composer = `document.querySelector('[data-comment-composer="open"]')`;
  const submit = `${composer}?.querySelector('button[type="submit"]')`;
  await until(s, () => s.eval(`${composer}?.dataset.mode === "thread" && !!${composer}.querySelector('[contenteditable="true"]')
    && !!document.activeElement?.closest('[data-comment-composer]')`), "Start thread did not open a focused composer");
  // One submit, named for what it posts; no checkbox (the mode is a switch); dark until there is text.
  const opened = await s.eval(`(() => { const c = ${composer}; return {
    submits: [...c.querySelectorAll('button[type="submit"]')].map((b) => b.textContent.trim()),
    checkbox: !!c.querySelector('input[type="checkbox"]'), disabled: c.querySelector('button[type="submit"]').disabled,
    mode: c.querySelector('[data-composer-mode] [aria-checked="true"]')?.textContent.trim() }; })()`);
  assert.deepEqual(opened, {submits: ["Start thread"], checkbox: false, disabled: true, mode: "Thread"}, "Start thread lit on an empty composer");
  // The mode switch changes the submit's words: a wrong choice needs no Cancel.
  await steadyClick('[data-composer-mode] [data-option="comment"]');
  await until(s, () => s.eval(`${submit}?.textContent.trim() === "Comment" && ${composer}.dataset.mode === "comment"`), "mode switch did not relabel the submit");
  await steadyClick('[data-composer-mode] [data-option="thread"]');
  await until(s, () => s.eval(`${submit}?.textContent.trim() === "Start thread"`), "mode switch did not switch back");
  for (let attempt = 0; attempt < 5; attempt++) {
    await steadyClick('[data-comment-composer="open"] [contenteditable="true"]');
    await s.send("Input.insertText", {text: "Please verify the checklist"});
    if (await s.eval(`new Promise(r => setTimeout(() => r(!(${submit})?.disabled), 400))`)) break;
  }
  await until(s, () => s.eval(`!(${submit})?.disabled`), "Start thread did not light up");
  // Cancel keeps the draft: the row returns (focus on the button it came from), reopening shows it.
  await steadyClick('[data-composer-cancel]');
  await until(s, () => s.eval(`!!document.querySelector('[data-comment-composer="closed"]') && document.activeElement?.hasAttribute("data-start-thread")`), "Cancel did not return to the row");
  await steadyClick('[data-start-thread]');
  await until(s, () => s.eval(`${composer}?.querySelector('[contenteditable="true"]')?.textContent.includes("Please verify the checklist") && !(${submit})?.disabled`), "Cancel lost the draft");
  await steadyClick('[data-comment-composer="open"] button[type="submit"]');
  await until(s, () => comments.some(c => c.body.includes("Please verify") && c.is_thread), "composer did not create thread");
  // Posting closes and clears it: Comment reopens an empty composer in Comment mode.
  await until(s, () => s.eval(`!!document.querySelector('[data-comment-composer="closed"]')`), "posting did not close the composer");
  await steadyClick('[data-open-comment]');
  await until(s, () => s.eval(`${composer}?.dataset.mode === "comment" && ${composer}.querySelector('[contenteditable="true"]')?.textContent === ""
    && (${submit})?.disabled && (${submit})?.textContent.trim() === "Comment"`), "fresh composer missing");
  for (let attempt = 0; attempt < 5; attempt++) {
    await steadyClick('[data-comment-composer="open"] [contenteditable="true"]');
    await s.send("Input.insertText", {text: "An ordinary follow-up"});
    if (await s.eval(`new Promise(r => setTimeout(() => r(!(${submit})?.disabled), 400))`)) break;
  }
  await until(s, () => s.eval(`!(${submit})?.disabled`), "comment submit did not enable");
  await steadyClick('[data-comment-composer="open"] button[type="submit"]');
  await until(s, () => comments.some(c => c.body.includes("ordinary follow-up") && !c.is_thread), "ordinary comment was marked as a thread");
  // RADD-1478: an ordinary comment can become a thread after the fact; a thread and a reply offer nothing.
  const startFrom = (id) => `document.querySelector('[data-start-thread-from="${id}"]')`;
  await until(s, () => s.eval(`!!${startFrom("quiet")}`), "an ordinary comment offers no Start thread");
  assert.equal(await s.eval(`!!${startFrom("thread")} || !!${startFrom("locked")}`), false, "a thread offers Start thread");
  assert.equal(await s.eval(`!!document.querySelector('[data-comment-id="reply-ordinary"] [data-start-thread-from]')
    || !!document.querySelector('[data-comment-replies] [aria-label="Start thread from this comment"]')`), false, "a reply offers Start thread");
  await s.eval(`window.__proofNoReload = true`);
  await steadyClick('[data-start-thread-from="quiet"]');
  await until(s, () => requests.some(r => r.method === "PATCH" && r.route === "/comments/quiet" && r.body.is_thread === true), "Start thread did not PATCH is_thread");
  await until(s, () => s.eval(`(() => { const card = document.querySelector('[data-comment-id="quiet"]');
    return card?.dataset.thread === "unresolved" && card.querySelector('[data-thread-state]')?.textContent.trim() === "Unresolved thread"
      && !!card.querySelector('[data-thread-resolution="quiet"]') && !card.querySelector('[data-start-thread-from]'); })()`),
    "the converted comment did not redraw as an unresolved thread with resolve controls");
  assert.equal(await s.eval(`window.__proofNoReload === true`), true, "the conversion reloaded the page");
  assert.deepEqual(Object.keys(requests.find(r => r.method === "PATCH" && r.route === "/comments/quiet").body), ["is_thread"], "the conversion sent more than is_thread");
  // A refusal comes back onto the comment, and the comment stays what it was.
  failConvert = true;
  const follow = comments.find(c => c.body.includes("ordinary follow-up")).id;
  await steadyClick(`[data-start-thread-from="${follow}"]`);
  await until(s, () => s.eval(`document.querySelector('[data-comment-id="${follow}"]')?.innerText.includes("Thread conversion refused")`), "the conversion refusal was not shown on the comment");
  assert.equal(await s.eval(`document.querySelector('[data-comment-id="${follow}"]').dataset.thread ?? null`), null, "a refused conversion redrew as a thread");
  failConvert = false;
  await s.screenshot("/tmp/radd-resolvable-threads.png");
  await s.navigate(base + "/p/THR/settings/workflow");
  await until(s, () => s.eval(`document.body.innerText.includes('All threads must be resolved')`), "workflow rule editor missing");
  // Wait for what the PAGE shows, not for the fixture to record the save: the
  // request lands before its response does, and a control is disabled until then —
  // a click in that window is (rightly) ignored.
  const box = (label) => `Array.from(document.querySelectorAll('label')).find(l => l.textContent.trim() === ${JSON.stringify(label)})?.querySelector('input')`;
  const shows = (label, checked) => until(s, () => s.eval(`(() => { const b = ${box(label)}; return !!b && !b.disabled && b.checked === ${checked}; })()`),
    `${label} did not settle ${checked ? "on" : "off"}`);
  await shows("All threads must be resolved", true);
  await s.click('label', text => text.trim() === "All threads must be resolved");
  await until(s, () => !transition.rules.some(r => r.check === "require_resolved_threads"), "rule toggle did not save");
  assert(transition.rules.some(r => r.check === "require_field"));
  assert(transition.rules.some(r => r.check === "require_approval"));
  await shows("All threads must be resolved", false);
  await s.click('label', text => text.trim() === "All threads must be resolved");
  await until(s, () => transition.rules.some(r => r.check === "require_resolved_threads"), "rule toggle did not re-enable");
  await shows("All threads must be resolved", true);
  await shows("Require approval", true);
  await s.click('label', text => text.trim() === "Require approval");
  await until(s, () => !transition.rules.some(r => r.check === "require_approval"), "approval toggle did not save");
  assert(transition.rules.some(r => r.check === "require_resolved_threads"), "approval edit dropped thread guard");
  await shows("Require approval", false);
  // Ticked again, the remote seeds the configuring user (the server refuses an empty rule).
  await s.click('label', text => text.trim() === "Require approval");
  await until(s, () => transition.rules.some(r => r.check === "require_approval" && r.params.approvers?.[0]?.id === user.id), "approval toggle did not re-seed");
  assert.equal(transition.rules.at(-1).check, "require_approval", "the contributed rule no longer sorts last");
  await shows("Require approval", true);
  // Withdrawn: the editor leaves with the plugin, the rule stays and says it refuses every move.
  approvalsEnabled = false;
  await s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey: ['capabilities']})`);
  await until(s, () => s.eval(`!!document.querySelector('[data-unserved-rule="require_approval"]')`), "withdrawn approval rule shows no fail-closed notice");
  assert.equal(await s.eval(`!!document.querySelector('[data-approval-rule]')`), false, "approval editor outlived its plugin");
  await s.click('[aria-label="Remove rule require_approval"]');
  await until(s, () => !transition.rules.some(r => r.check === "require_approval"), "unserved rule did not remove");
  assert(transition.rules.some(r => r.check === "require_resolved_threads"), "removing the unserved rule dropped the thread guard");
  await until(s, () => s.eval(`!document.querySelector('[data-unserved-rule]')`), "notice outlived the removed rule");
  await until(s, () => s.eval(`!!document.querySelector('[aria-label="Remove condition"]:not([disabled])')`), "field condition not removable");
  await s.click('[aria-label="Remove condition"]');
  await until(s, () => !transition.rules.some(r => r.check === "require_field"), "field condition did not save");
  assert(transition.rules.some(r => r.check === "require_resolved_threads"), "field edit dropped thread guard");
  // RADD-1283: who can resolve — a default plus an issue-type rule, saved whole.
  await until(s, () => s.eval(`!!document.querySelector('[data-thread-resolution-settings]')`), "thread resolution settings missing");
  // RADD-1495: the control renders only once the issue types have loaded, and a toast from the
  // preceding save can sit over it on a slow runner — wait for it to be there, uncovered and
  // idle before the click, and say what the fixture last saw if the save never arrives.
  const addRule = '[data-thread-resolution-settings] [data-add-thread-rule]';
  const addRuleReady = () => s.eval(`(() => {
    const el = document.querySelector(${JSON.stringify(addRule)});
    if (!el || el.disabled) return false;
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return !!hit && el.contains(hit) && !document.querySelector('[role="status"] [data-toast-action]');
  })()`);
  await until(s, addRuleReady, "add-rule control never became clickable");
  const ruleSaved = () => threadPolicy.overrides.length === 1 && threadPolicy.overrides[0].issue_type_id === "type-bug";
  const lastRequests = () => requests.slice(-4).map((r) => `${r.method} ${r.route}`).join(" | ");
  await steadyClick(addRule);
  try {
    await until(s, ruleSaved, "issue-type rule not saved", { timeoutMs: 8_000, describe: async () => `last requests: ${lastRequests()}` });
  } catch (first) {
    // One retry: a click swallowed by a repaint is a runner artefact, a second miss is a bug.
    console.error(`add-rule click did not save on the first try (${first.message.split("\n")[0]}); retrying once`);
    await until(s, addRuleReady, "add-rule control not clickable for the retry");
    await steadyClick(addRule);
    await until(s, ruleSaved, "issue-type rule not saved after a retry", { describe: async () => `last requests: ${lastRequests()}` });
  }
  await until(s, () => s.eval(`!!document.querySelector('[data-thread-rule="type-bug"]')`), "issue-type rule row missing");
  assert.equal(threadPolicy.default, "author");
  await s.screenshot("/tmp/radd-thread-workflow.png");
  console.log(JSON.stringify({passed: true, checks: ["ordinary comments have no lifecycle", "a thread looks like a thread",
    "replies show without a click", "no disclosure on a comment nobody answered", "a resolved thread starts collapsed and says why",
    "Reply opens a focused composer in one click", "Escape and Cancel return to Reply", "Reply on a collapsed thread opens it",
    "the rule hides resolve controls", "reply keeps a resolved thread resolved", "posting closes the composer onto the reply",
    "reply and unresolve reopens", "replies persist", "resolution error", "resolve/reopen", "transition refresh", "unresolved filter",
    "the composer is a Comment / Start thread row until asked", "the open composer has one submit", "the mode switch relabels the submit",
    "Cancel keeps the draft", "composer creates explicit thread", "composer resets",
    "an ordinary comment offers Start thread; a thread and a reply do not", "one PATCH {is_thread} redraws it as an unresolved thread with resolve controls, no reload",
    "a refused conversion is shown on the comment", "workflow preserves independent rules",
    "approval editor is the approvals remote", "withdrawn plugin rule fails closed and can be removed"],
    screenshots: ["/tmp/radd-thread-resolved.png", "/tmp/radd-resolvable-threads.png", "/tmp/radd-thread-workflow.png"]}));
} catch (error) {
  if (browser) {
    await browser.session.screenshot("/tmp/radd-threads-failure.png");
    console.error(await browser.session.eval("JSON.stringify({text:document.body.innerText,editors:Array.from(document.querySelectorAll(\"[contenteditable=true]\")).map(e=>e.outerHTML)})"));
    console.error(JSON.stringify(requests.filter(r => r.method !== "GET")));
  }
  throw error;
} finally {
  await browser?.close();
  await spa.close();
}
