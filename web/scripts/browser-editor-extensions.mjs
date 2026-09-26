/** RADD-1395: the editor's extension points, filled by the ACTUAL ai remote (served from its
 * ui/dist) against synthetic HTTP fixtures — never a real instance.
 *
 *   1. with ai listed, the toolbar AI button, Ask AI over a selection, the read-menu triggers and
 *      the issue rail card are the ai remote's contributions (registered by plugin "ai");
 *   2. a transform run lands in the HOST's per-block review; Reject all leaves the text, Accept all
 *      applies it, and the saved description still carries the `radd:media` fence the mocked model
 *      DROPPED (RADD-1274: masked going out, appended coming back, with the review's note);
 *   3. a read action answers in the host's reading pane;
 *   4. dropping ai from capabilities withdraws every control from an open editor, a rendered
 *      comment and the rail — no reload, no request to /ai or /plugins/ai;
 *   5. re-listing ai restores each control exactly once.
 */
import assert from "node:assert/strict";
import {mkdtemp} from "node:fs/promises";
import {openBrowser, until} from "./lib/cdp.mjs";
import {CORE_PLUGINS} from "./lib/core-plugins.mjs";
import {serveBuiltSpa} from "./lib/spa-server.mjs";

let aiEnabled = true, aiVersion = 1;
const FENCE = "```radd:media\nsrc: /api/v1/attachments/demo-video\n```";
const user = {id: "admin", name: "Editor Owner", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC"};
const project = {id: "project", key: "EDX", name: "Editor extensions", permissions: ["*"], created_at: "2026-01-01"};
const state = {id: "state", name: "Open", category: "todo", category_key: "todo", position: 0, project_id: project.id};
let item = {id: "issue", key: "EDX-1", project_id: project.id, number: 1, title: "Extension points fixture",
  description: `The first paragraph reads rough.\n\n${FENCE}\n\nThe second paragraph also reads rough.\n`, state,
  priority: "normal", kind: "issue", labels: [], custom_fields: {},
  capabilities: {can_update: true, can_comment: true, can_transition: true},
  links: {incoming: [], outgoing: []}, created_at: "2026-01-01", updated_at: "2026-01-01"};
const comments = [{id: "c1", body: "A rendered comment the read menu speaks for.", is_thread: false, reply_count: 0}]
  .map(row => ({...row, entity_type: "item", entity_id: item.id, author: user, visibility: "public", visible_to_teams: [],
    anchor: null, parent_comment_id: null, resolved_at: null, resolved_by: null, created_at: "2026-01-01", updated_at: "2026-01-01"}));
const REPLACEMENT = "The first paragraph reads smoothly.\n\nThe second paragraph reads smoothly too.\n";
const SELECTION_REPLY = "opening";
const requests = [], streams = [], patches = [];
const sse = (res, chunks) => {
  res.writeHead(200, {"content-type": "text/event-stream"});
  for (const t of chunks) res.write(`data: ${JSON.stringify({t})}\n\n`);
  res.end("event: done\ndata: {}\n\n");
};
const spa = await serveBuiltSpa(async (req, res, url) => {
  if (url.pathname.startsWith("/plugins/")) {
    requests.push({route: url.pathname, method: req.method});
    if (!url.pathname.startsWith("/plugins/ai/")) {res.writeHead(404); res.end(); return true;}
    return false;
  }
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    requests.push({route, method: req.method, body});
    if (route === "/ai/editor/stream") {
      streams.push(body);
      // Summaries answer as a summary; a selection run answers one word for the selection; any other
      // action is the whole-document transform, whose reply DROPS the protected fence's placeholder —
      // the case RADD-1274 exists for.
      sse(res, body.action_id === "summarize_selection" ? ["A short ", "summary of the text."]
        : body.selection?.trim() ? [SELECTION_REPLY] : [REPLACEMENT.slice(0, 20), REPLACEMENT.slice(20)]);
      return true;
    }
    if (route === "/items/issue/ai/summarize/stream") {sse(res, ["The whole issue, ", "summarized."]); return true;}
    let data = [];
    if (route === "/auth/me") data = user;
    else if (route.includes("capabilities")) data = {capabilities: [], nav: [], ui: [],
      plugins: [...CORE_PLUGINS, ...(aiEnabled ? ["ai"] : [])],
      remotes: aiEnabled ? [{name: "ai", remote_entry: `/plugins/ai/remoteEntry.js?v=${aiVersion}`, ui_api_version: "1.16.0"}] : []};
    else if (route === "/ai/status") data = {enabled: true, stream_responses: true, features: {editor_actions: true, summarize: true, similar_rerank: false}};
    else if (route === "/ai/editor/actions") data = [{id: "improve_writing", label: "Improve writing", kind: "builtin"},
      {id: "summarize_selection", label: "Summarize", kind: "builtin"}];
    else if (route === "/auth/me/preferences") data = {};
    else if (route === "/projects/summary") data = {total: 1, related_count: 0, permissions: ["*"]};
    else if (route === "/page-spaces/summary") data = {total: 0, permissions: []};
    else if (route === "/projects/project" || route === "/projects/by-key/EDX") data = project;
    else if (route === "/projects") data = [project];
    else if (route === "/items/issue" && req.method === "PATCH") {patches.push(body); item = {...item, ...body}; data = item;}
    else if (route.startsWith("/items/by-key/") || route === "/items/issue") data = item;
    else if (route === "/fields/writable") data = {readonly_fields: []};
    else if (route === "/screens/effective") data = {fields: []};
    else if (route === "/states") data = [state];
    else if (route.endsWith("/comments/feed")) data = {comments, older_cursor: null};
    else if (route.endsWith("/allowed-transitions")) data = {mode: "off", targets: []};
    else if (route.endsWith("/watchers")) data = {watching: false, watchers: []};
    else if (route.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (route === "/instance") data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (route.includes("/resolve")) data = {value: false};
    else if (route.endsWith("/timelogging")) data = {enabled: false};
    res.writeHead(200, {"content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0)});
    res.end(JSON.stringify(data)); return true;
  }
});
const checks = [];
let browser;
try {
  browser = await openBrowser({port: 18857, profile: await mkdtemp("/tmp/radd-editor-extensions-"), scale: 1});
  const s = browser.session;
  const count = selector => s.eval(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  const owners = slot => s.eval(`globalThis.__RADD_SLOT_REGISTRY__.forSlot(${JSON.stringify(slot)}).map((e) => e.plugin)`);
  const refresh = () => s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
  const aiRequests = () => requests.filter(r => /^\/(?:ai\/|plugins\/ai\/)|\/ai\//.test(r.route)).length;
  // The comment composer is a rich editor too, with its own toolbar: the description's editor is
  // marked once opened, so every editor check below is about that one.
  const DESC = "[data-proof-desc]";
  const editorText = () => s.eval(`document.querySelector("${DESC} .ProseMirror")?.innerText ?? ""`);
  const openDescription = async () => {
    await s.hover(".group\\/desc");
    await s.click('[aria-label="Edit description"]');
    await until(s, `[...document.querySelectorAll(".radd-rich-editor")].some((e) => e.innerText.includes("paragraph"))`, "description editor");
    await s.eval(`[...document.querySelectorAll(".radd-rich-editor")].find((e) => e.innerText.includes("paragraph")).setAttribute("data-proof-desc", "")`);
  };

  await s.navigate(`${spa.origin}/issues/EDX-1`);
  assert(await s.eval(`matchMedia("(hover: hover)").matches`), "the browser must report a hover-capable pointer");
  await until(s, `!!document.querySelector('[aria-label="AI actions for this comment"]') && !!document.querySelector("[data-ai-rail]")`, "ai read menu and rail");
  for (const slot of ["content.read.action", "issue.rail.top", "editor.toolbar.action", "editor.selection.action", "item.draft.assist"]) {
    assert.deepEqual(await owners(slot), ["ai"], slot);
  }
  assert(requests.some(r => r.route === "/plugins/ai/remoteEntry.js"), "the remote bundle was loaded");
  assert.equal(await count('[aria-label="AI actions for the description"]'), 1);
  // The comment composer's toolbar carries the remote's button before any edit starts.
  assert.equal(await count('.radd-rich-editor [role="toolbar"] svg.radd-ai-toolbar-icon'), 1);
  checks.push("with ai listed, the read menus (description, comment), the rail card and the composer's toolbar button render, and every editor/read/rail/draft slot's only owner is the ai remote");

  // A read action answers in the HOST's reading pane.
  await s.hover('[data-comment-id="c1"]');
  await s.click('[aria-label="AI actions for this comment"]');
  await until(s, `!!document.querySelector("[data-ai-read-panel]")`, "read menu opened");
  await s.click("[data-ai-read-panel] button", text => text.trim() === "Summarize");
  await until(s, `document.querySelector("[data-reading-panel]")?.innerText.includes("summary of the text")`, "summary in the pane");
  await s.screenshot("/tmp/radd-editor-extensions-pane.png");
  assert.equal(await s.eval(`document.querySelector("[data-reading-panel]").getAttribute("aria-label")`), "AI results — Summary");
  assert.equal(streams.at(-1).action_id, "summarize_selection");
  assert.equal(streams.at(-1).document, comments[0].body);
  await s.click('[data-reading-panel] button[aria-label^="Close"]');
  await until(s, `!document.querySelector("[data-reading-panel]")`, "pane closed");
  checks.push("a comment's read-menu Summarize streams from the ai remote into the host's reading pane");

  // The description editor: the toolbar button is the remote's; the review is the host's.
  await openDescription();
  await until(s, `!!document.querySelector('${DESC} [role="toolbar"] svg.radd-ai-toolbar-icon')`, "editor with AI button");
  const runTransform = async () => {
    await s.click(`${DESC} [role="toolbar"] button[aria-label="AI"]`);
    await until(s, `!!document.querySelector("[data-ai-toolbar-menu]")`, "toolbar menu");
    await s.click("[data-ai-toolbar-menu] button", text => text.trim() === "Improve writing");
    await until(s, `document.querySelector("${DESC} [data-editor-run-panel]")?.innerText.includes("to review") && document.querySelectorAll("${DESC} .milkdown-diff-controls").length > 0`, "host review");
  };
  await runTransform();
  const sent = streams.at(-1);
  assert.equal(sent.action_id, "improve_writing");
  assert(sent.document.includes("⟦keep-1⟧") && !sent.document.includes("radd:media"), "the fence went out masked: " + sent.document);
  const review = await s.eval(`({
    pairs: document.querySelectorAll("${DESC} .milkdown-diff-controls").length,
    note: document.querySelector("${DESC} [data-editor-run-note]")?.textContent ?? "",
    toolbarDisabled: document.querySelector('${DESC} [role="toolbar"] button[aria-label="AI"]').disabled,
  })`);
  assert(review.pairs >= 1, JSON.stringify(review));
  await s.screenshot("/tmp/radd-editor-extensions-review.png");
  assert.match(review.note, /left out 1 protected block/);
  assert.equal(review.toolbarDisabled, true, "a second run is not offered during review");
  await s.click(`${DESC} [data-editor-run-panel] button`, text => /reject all/i.test(text));
  await until(s, `!document.querySelector("${DESC} [data-editor-run-panel]") && document.querySelectorAll("${DESC} .milkdown-diff-controls").length === 0`, "review rejected");
  assert.match(await editorText(), /reads rough/);
  checks.push("the toolbar AI run streams a masked document and lands in the host's per-block review with the transform's note; Reject all leaves the text");

  await runTransform();
  await s.click(`${DESC} [data-editor-run-panel] button`, text => /accept all/i.test(text));
  await until(s, `!document.querySelector("${DESC} [data-editor-run-panel]")`, "review accepted");
  assert.match(await editorText(), /reads smoothly/);
  // The editor publishes its markdown 200 ms after the last change (Milkdown's listener), as it
  // does for typing; a person pressing Save is slower than that.
  await new Promise(r => setTimeout(r, 400));
  const patchesBefore = patches.length;
  await s.click("button", text => text.trim() === "Save");
  await until(s, `!document.querySelector("${DESC}")`, "description saved");
  assert.equal(patches.length, patchesBefore + 1);
  const saved = patches.at(-1)?.description ?? "";
  assert.match(saved, /reads smoothly/);
  assert(saved.includes("```radd:media") && saved.includes("src: /api/v1/attachments/demo-video"), "the dropped fence survived: " + saved);
  checks.push("Accept all applies the transform; the saved description keeps the radd:media fence the model dropped (RADD-1274)");

  // Ask AI over a selection is the remote's too.
  await openDescription();
  const selectFirstWord = () => s.eval(`(() => {
    const pm = document.querySelector("${DESC} .ProseMirror"); pm.focus();
    const text = pm.querySelector("p").firstChild; const range = document.createRange();
    range.setStart(text, 4); range.setEnd(text, 9);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); return selection.toString();
  })()`);
  assert.equal(await selectFirstWord(), "first");
  await until(s, `!!document.querySelector("[data-editor-selection-actions] [data-ai-selection-button]")`, "selection action");
  // Past the fade-in: the chrome is painted above the toolbar it may overlap, and hit-tests as itself.
  await new Promise(r => setTimeout(r, 500));
  const chrome = await s.eval(`(() => {
    const b = document.querySelector("[data-ai-selection-button]"); const r = b.getBoundingClientRect();
    return { opacity: getComputedStyle(b).opacity, hit: b.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)) };
  })()`);
  assert.equal(chrome.opacity, "1", JSON.stringify(chrome));
  assert(chrome.hit, JSON.stringify(chrome));
  await s.screenshot("/tmp/radd-editor-extensions-selection.png");
  await s.click("[data-ai-selection-button]");
  await until(s, `!!document.querySelector("[data-ai-selection-menu]")`, "selection menu");
  await s.click("[data-ai-selection-menu] button", text => text.trim() === "Improve writing");
  await until(s, `!!document.querySelector("${DESC} [data-editor-run-panel]")`, "selection run");
  assert.equal(streams.at(-1).selection.trim(), "first", "the captured selection travelled with the run");
  await until(s, `document.querySelector("${DESC} [data-editor-run-panel]")?.innerText.includes("to review")`, "selection review");
  // Only the selected passage changes: the paragraph outside the selection reads as it did, carries
  // no diff marks, and no review control follows it.
  const scoped = await s.eval(`(() => {
    const pm = document.querySelector("${DESC} .ProseMirror");
    const second = [...pm.querySelectorAll("p")].find((p) => p.textContent.includes("second paragraph"));
    const controls = [...pm.querySelectorAll(".milkdown-diff-controls")];
    return {
      second: second?.textContent ?? null,
      marked: second ? second.querySelectorAll('[class*="milkdown-diff"]').length : -1,
      after: controls.filter((c) => second && (second.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING)).length,
      changed: controls.length > 0 && pm.innerText.includes(${JSON.stringify(SELECTION_REPLY)}),
    };
  })()`);
  assert.deepEqual(scoped, {second: "The second paragraph reads smoothly too.", marked: 0, after: 0, changed: true});
  await s.click(`${DESC} [data-editor-run-panel] button`, text => /reject all/i.test(text));
  await until(s, `!document.querySelector("${DESC} [data-editor-run-panel]")`, "selection review rejected");
  checks.push("Ask AI over a selection sends the captured range, changes only that passage (the text outside it is untouched) and reviews in the same host band");

  // Withdrawal: the description editor is open, a comment is rendered, the composer is mounted.
  await s.eval("window.__sameDocument = true");
  await selectFirstWord();
  await until(s, `!!document.querySelector("[data-ai-selection-button]")`, "selection action before withdrawal");
  const before = aiRequests();
  aiEnabled = false; await refresh();
  await until(s, `!document.querySelector("svg.radd-ai-toolbar-icon") && !document.querySelector("[data-ai-selection-button]")
    && !document.querySelector('[aria-label^="AI actions for"]') && !document.querySelector("[data-ai-rail]")`, "every ai control withdrawn");
  assert.deepEqual(await owners("editor.toolbar.action"), []);
  assert(await s.eval(`!!document.querySelector("${DESC} .ProseMirror") && window.__sameDocument === true`), "the open editor survived with no reload");
  await selectFirstWord();
  await s.hover('[data-comment-id="c1"]');
  await new Promise(r => setTimeout(r, 1500));
  assert.equal(aiRequests(), before, "no request reached /ai or /plugins/ai after withdrawal");
  assert.equal(await count("[data-editor-selection-actions]"), 0, "nothing floats over the selection");
  checks.push("dropping ai from capabilities withdraws the toolbar buttons, Ask AI, the comment's read menu and the rail card from the open page — no reload, no AI request");

  aiEnabled = true; aiVersion += 1; await refresh();
  // Two editors are open (the description and the comment composer; a rendered comment shares the
  // class but has no toolbar): one AI button in each.
  await until(s, `[...document.querySelectorAll(".radd-rich-editor")].filter((e) => e.querySelector('[role="toolbar"]')).length === 2
    && [...document.querySelectorAll(".radd-rich-editor")].filter((e) => e.querySelector('[role="toolbar"]'))
      .every((e) => e.querySelectorAll('[role="toolbar"] svg.radd-ai-toolbar-icon').length === 1)
    && document.querySelectorAll('[aria-label="AI actions for this comment"]').length === 1
    && document.querySelectorAll("[data-ai-rail]").length === 1`, "ai controls restored");
  await selectFirstWord();
  await until(s, `document.querySelectorAll("[data-ai-selection-button]").length === 1`, "selection action restored");
  assert.deepEqual(await owners("editor.toolbar.action"), ["ai"]);
  checks.push("re-listing ai restores each control exactly once");

  assert(!s.consoleErrors.some(error => /TypeError|Minified React error|Invalid hook|Uncaught/.test(error)), JSON.stringify(s.consoleErrors));
  console.log(JSON.stringify({passed: true, checks, requests: requests.length, streams: streams.length}));
} catch (error) {
  console.error(JSON.stringify({errors: browser?.session.consoleErrors, requests: requests.slice(-30).map(r => r.method + " " + r.route)}, null, 1));
  throw error;
} finally {
  await browser?.close();
  spa.server.closeAllConnections();
  await spa.close();
}
