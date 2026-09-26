/** RADD-1400: the command palette's modes and the query bar's input modes are contributions, and
 * the ACTUAL ai remote (served from its ui/dist) contributes Ask to both — against synthetic HTTP
 * fixtures, never a real instance. A second, fixture remote ("echo") contributes a palette mode
 * that answers in STREAMED TEXT and a query mode that serves only the items dialect.
 *
 *   1. with ai listed, the palette offers Ask (registered by plugin "ai"); its answer renders as the
 *      palette's rows, the keyboard moves through them and Enter navigates — no reload;
 *   2. the echo mode's text streams into the palette before it settles;
 *   3. on the timesheet (worklog dialect) an empty bar opens on Ask — ai's mode, not echo's
 *      items-only one; mod+I toggles; a question compiles to SLQ (dialect worklog) with its
 *      explanation, and the timesheet runs it; a URL-carried query opens SLQ;
 *   4. dropping ai from capabilities removes both modes — the bar is plain SLQ with no toggle —
 *      with no request to /ai, /search/semantic or /slq/nl, and no reload;
 *   5. re-listing ai restores each exactly once.
 */
import assert from "node:assert/strict";
import http from "node:http";
import {readFileSync, existsSync, statSync} from "node:fs";
import {mkdtemp} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {openBrowser} from "./lib/cdp.mjs";
import {CORE_PLUGINS} from "./lib/core-plugins.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const aiDist = fileURLToPath(new URL("../../server/src/radd/modules/ai/ui/dist/", import.meta.url));
let aiEnabled = true, aiVersion = 1;
const echo = `import{paletteMode,queryInputMode,definePlugin}from'@radd/plugin-sdk';
export default definePlugin({contributions:[
  paletteMode({id:'echo.say',label:'Echo',hint:'say it back',placeholder:'Say something…',
    answer:async(q,{onText,signal})=>{onText('Heard: '+q);await new Promise(r=>{window.__echoRelease=r;signal.addEventListener('abort',r);});return{heading:'Echo',text:'Heard: '+q+' (done)'};}}),
  queryInputMode({id:'echo.items',label:'Echo',hint:'items only',placeholder:'Echo a query',dialects:['items'],
    toQuery:async(text)=>({query:'title ~ "'+text+'"',explanation:'Echoed.'})}),
]});`;
const user = {id: "admin", name: "Mode Owner", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC"};
const project = {id: "project", key: "MOD", name: "Modes", permissions: ["*"], created_at: "2026-01-01"};
const state = {id: "state", name: "Open", category: "todo", category_key: "todo", position: 0, project_id: project.id};
const item = (n, title) => ({id: `issue-${n}`, key: `MOD-${n}`, project_id: project.id, number: n, title, description: "", state,
  priority: "normal", kind: "issue", labels: [], custom_fields: {}, capabilities: {can_update: true, can_comment: true, can_transition: true},
  links: {incoming: [], outgoing: []}, created_at: "2026-01-01", updated_at: "2026-01-01"});
const items = [item(1, "Render farm runs out of disk"), item(2, "Nightly render retries forever")];
const SLQ = "author = me AND issue.project = MOD";
const requests = [], asks = [], timesheets = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname.startsWith("/plugins/")) {
    requests.push({route: url.pathname, method: req.method});
    if (url.pathname.startsWith("/plugins/echo/")) {res.writeHead(200, {"content-type": "text/javascript"}); res.end(echo); return;}
    const file = path.join(aiDist, url.pathname.slice("/plugins/ai/".length));
    if (!url.pathname.startsWith("/plugins/ai/") || !existsSync(file)) {res.writeHead(404); res.end(); return;}
    res.writeHead(200, {"content-type": "text/javascript"}); res.end(readFileSync(file)); return;
  }
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    requests.push({route, method: req.method, body, q: url.searchParams.get("q")});
    let data = [];
    if (route === "/auth/me") data = user;
    else if (route.includes("capabilities")) data = {capabilities: [], nav: [],
      plugins: [...CORE_PLUGINS, "echo", ...(aiEnabled ? ["ai"] : [])],
      remotes: [{name: "echo", remote_entry: "/plugins/echo/remoteEntry.js", ui_api_version: "1.18.0"},
        ...(aiEnabled ? [{name: "ai", remote_entry: `/plugins/ai/remoteEntry.js?v=${aiVersion}`, ui_api_version: "1.18.0"}] : [])]};
    else if (route === "/ai/status") data = {enabled: true, stream_responses: true,
      features: {semantic_search: true, nl_slq: true, editor_actions: false, summarize: false, similar_rerank: false}};
    else if (route === "/search/semantic") data = {enabled: true,
      items: items.map((it, i) => ({item_id: it.id, project_id: project.id, key: it.key, title: it.title, score: 0.91 - i * 0.2})),
      docs: [{page_id: "7f1c", space_id: "space", title: "Render farm runbook", score: 0.42}]};
    else if (route === "/slq/nl") {asks.push(body); data = {slq: SLQ, explanation: "Your own worklogs on MOD issues."};}
    else if (route === "/timesheet") {timesheets.push(url.searchParams.get("q") ?? "");
      data = {start: url.searchParams.get("start"), end: url.searchParams.get("end"), total_seconds: 0, entries: [], day_min_hours: 6, day_max_hours: 10, work_days: ["mon"]};}
    else if (route.endsWith("/slq/validate")) data = {ok: true};
    else if (route.endsWith("/slq/suggest")) data = {context: "field", replace_from: 0, field: null, suggestions: []};
    else if (route === "/search") data = {results: []};
    else if (route === "/search/entities") data = {groups: []};
    else if (route.startsWith("/pages/search") || route.endsWith("/search/pages")) data = {results: []};
    else if (route === "/auth/me/preferences" || route === "/preferences") data = {};
    else if (route === "/projects/summary") data = {total: 1, related_count: 0, permissions: ["*"]};
    else if (route === "/page-spaces/summary") data = {total: 0, permissions: []};
    else if (route === "/projects/project" || route === "/projects/by-key/MOD") data = project;
    else if (route === "/projects") data = [project];
    else if (route.startsWith("/items/by-key/")) data = items.find((it) => route.endsWith(it.key)) ?? items[0];
    else if (/^\/items\/issue-\d+$/.test(route)) data = items.find((it) => route.endsWith(it.id)) ?? items[0];
    else if (route === "/fields/writable") data = {readonly_fields: []};
    else if (route === "/screens/effective") data = {fields: []};
    else if (route === "/states") data = [state];
    else if (route.endsWith("/comments/feed")) data = {comments: [], older_cursor: null};
    else if (route.endsWith("/allowed-transitions")) data = {mode: "off", targets: []};
    else if (route.endsWith("/watchers")) data = {watching: false, watchers: []};
    else if (route.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (route === "/instance") data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (route.includes("/resolve")) data = {value: false};
    else if (route.endsWith("/timelogging")) data = {enabled: false};
    res.writeHead(200, {"content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0)});
    res.end(JSON.stringify(data)); return;
  }
  let file = path.resolve(dist, "." + url.pathname);
  if (!file.startsWith(dist) || !existsSync(file) || statSync(file).isDirectory()) file = path.join(dist, "index.html");
  const mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}[path.extname(file)] ?? "application/octet-stream";
  res.writeHead(200, {"content-type": mime}); res.end(readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const checks = [];
let browser;
try {
  browser = await openBrowser({port: 18861, profile: await mkdtemp("/tmp/radd-contributed-modes-"), scale: 1});
  const s = browser.session;
  const until = async (expression, label, attempts = 200) => {
    for (let i = 0; i < attempts; i++) {if (await s.eval(expression)) return; await new Promise(r => setTimeout(r, 40));}
    const palette = await s.eval(`document.querySelector('[role=dialog][aria-label="Command palette"]')?.innerText ?? null`);
    throw Error(label + ": " + (palette !== null ? "palette: " + palette : (await s.eval("document.body.innerText")).slice(0, 600)));
  };
  const press = async (key, code, keyCode, modifiers = 0) => {
    for (const type of ["rawKeyDown", "keyUp"]) await s.send("Input.dispatchKeyEvent", {type, key, code, windowsVirtualKeyCode: keyCode, modifiers});
  };
  const typeText = text => s.send("Input.insertText", {text});
  const owners = slot => s.eval(`globalThis.__RADD_SLOT_REGISTRY__.forSlot(${JSON.stringify(slot)}).map((e) => e.plugin).sort()`);
  const refresh = () => s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
  const aiRequests = () => requests.filter(r => /^\/(?:ai\/|plugins\/ai\/)|\/ai\/|^\/search\/semantic|^\/slq\/nl/.test(r.route)).length;
  const toggles = () => s.eval(`[...document.querySelectorAll('[role=group][aria-label="Query mode"] button')].map((b) => [b.textContent.trim(), b.getAttribute("aria-pressed")])`);
  const PALETTE = '[role=dialog][aria-label="Command palette"]';
  const paletteRows = () => s.eval(`[...document.querySelectorAll('${PALETTE} .max-h-\\\\[50vh\\\\] button')].map((b) => ({text: b.innerText.replace(/\\s+/g, " ").trim(), active: b.className.includes("bg-accent/15")}))`);
  const openPalette = async () => {
    await press("k", "KeyK", 75, 2);
    // The palette focuses its input a tick after opening; typing before that goes nowhere.
    await until(`document.activeElement === document.querySelector('${PALETTE} input[aria-label="Search"]')`, "palette open and focused");
  };

  // 3. The timesheet's bar: empty, so it opens on the first available mode — Ask, ai's.
  await s.navigate(`${base}/timesheet`);
  assert(await s.eval(`matchMedia("(hover: hover)").matches`), "the browser must report a hover-capable pointer");
  await until(`!!document.querySelector('input[aria-label="Ask AI for a query"]')`, "the bar opens on Ask");
  assert(requests.some(r => r.route === "/plugins/ai/remoteEntry.js"), "the ai remote bundle was loaded");
  assert.deepEqual(await owners("query.input.mode"), ["ai", "echo"]);
  assert.deepEqual(await toggles(), [["SLQ", "false"], ["Ask", "true"]], "echo's items-only mode is not offered on the worklog dialect");
  assert.equal(await s.eval(`document.querySelector('input[aria-label="Ask AI for a query"]').dataset.queryInputMode`), "ai.natural-language");
  assert.equal(await s.eval(`document.activeElement?.getAttribute("aria-label")`) === "Ask AI for a query", false, "the page-load default never grabs focus");
  await s.screenshot("/tmp/radd-contributed-modes-bar.png");
  checks.push("an empty timesheet bar opens on Ask, the ai remote's input mode; the toggle offers SLQ | Ask — echo's items-only mode stays out of the worklog dialect");

  // mod+I toggles.
  await s.click('input[aria-label="Ask AI for a query"]');
  await press("i", "KeyI", 73, 2);
  await until(`!!document.querySelector('textarea[aria-label="SLQ query"]') && !document.querySelector('input[aria-label="Ask AI for a query"]')`, "mod+I to SLQ");
  assert.deepEqual(await toggles(), [["SLQ", "true"], ["Ask", "false"]]);
  await press("i", "KeyI", 73, 2);
  await until(`document.activeElement?.getAttribute("aria-label") === "Ask AI for a query"`, "mod+I back to Ask, focused");
  checks.push("mod+I toggles SLQ ⇄ Ask, and a user switch focuses the new input");

  // A question compiles to worklog SLQ, lands in the editor with its explanation, and runs.
  await typeText("my worklogs on MOD issues");
  await press("Enter", "Enter", 13);
  await until(`document.querySelector('textarea[aria-label="SLQ query"]')?.value === ${JSON.stringify(SLQ)}`, "the answer lands as SLQ");
  await until(`document.querySelector("[data-query-explanation]")?.textContent === "Your own worklogs on MOD issues."`, "the explanation shows");
  assert.deepEqual(asks.at(-1), {question: "my worklogs on MOD issues", dialect: "worklog"});
  for (let i = 0; i < 100 && !timesheets.includes(SLQ); i++) await new Promise(r => setTimeout(r, 40));
  assert(timesheets.includes(SLQ), "the timesheet ran the generated query: " + JSON.stringify(timesheets));
  await s.screenshot("/tmp/radd-contributed-modes-answer.png");
  checks.push("a question compiles to SLQ in the worklog dialect, the bar applies it in the SLQ editor with the mode's explanation, and the timesheet runs it");

  // A URL-carried query opens SLQ even with a mode available.
  await s.navigate(`${base}/timesheet?q=${encodeURIComponent("author = me")}`);
  await until(`document.querySelector('textarea[aria-label="SLQ query"]')?.value === "author = me" && document.querySelectorAll('[role=group][aria-label="Query mode"] button').length === 2`, "URL query opens SLQ");
  assert.deepEqual(await toggles(), [["SLQ", "true"], ["Ask", "false"]]);
  checks.push("a URL-carried query opens the bar in SLQ, with Ask still offered");

  // 1. The palette's Ask, answered as the palette's own rows.
  await s.eval("window.__sameDocument = true");
  await openPalette();
  await typeText("render farm disk");
  await until(`[...document.querySelectorAll('${PALETTE} button')].some((b) => b.innerText.includes("search by meaning"))`, "the Ask entry");
  assert.deepEqual(await owners("palette.mode"), ["ai", "echo"]);
  const entries = (await paletteRows()).map(r => r.text).filter(t => t.includes("“render farm disk”")).sort();
  assert.deepEqual(entries, ["Ask: “render farm disk” — search by meaning", "Echo: “render farm disk” — say it back"]);
  await s.click(`${PALETTE} button`, text => text.includes("search by meaning"));
  await until(`document.querySelector('${PALETTE} input').placeholder === "Search by meaning…" && document.querySelector('${PALETTE}').textContent.includes("Semantic matches")`, "Ask answered");
  const rows = await paletteRows();
  assert.deepEqual(rows.map(r => r.text), ["MOD-1 Render farm runs out of disk 91%", "MOD-2 Nightly render retries forever 71%", "Render farm runbook 42%"]);
  assert.equal(await s.eval(`document.querySelectorAll('${PALETTE} .max-h-\\\\[50vh\\\\] button svg').length`), 1, "the page row draws the mode's icon");
  assert(rows[0].active, "the first row starts active");
  assert.equal(requests.filter(r => r.route === "/search/semantic").at(-1).q, "render farm disk");
  await s.screenshot("/tmp/radd-contributed-modes-palette.png");
  await press("ArrowDown", "ArrowDown", 40);
  await until(`[...document.querySelectorAll('${PALETTE} .max-h-\\\\[50vh\\\\] button')][1]?.className.includes("bg-accent/15")`, "ArrowDown moves the active row");
  await press("Enter", "Enter", 13);
  await until(`location.pathname === "/issues/MOD-2" && !document.querySelector('${PALETTE}')`, "Enter navigates to the row");
  assert.equal(await s.eval("window.__sameDocument"), true, "no reload");
  checks.push("the palette offers Ask from the ai remote; its answer renders as the palette's rows (key pill, icon, score), ArrowDown moves the active row and Enter navigates in the same document");

  // 2. A text answer streams.
  await openPalette();
  await typeText("hello");
  await until(`[...document.querySelectorAll('${PALETTE} button')].some((b) => b.innerText.includes("say it back"))`, "the Echo entry");
  await s.click(`${PALETTE} button`, text => text.includes("say it back"));
  await until(`document.querySelector("[data-palette-answer-text]")?.textContent === "Heard: hello"`, "the text streams");
  await s.eval("window.__echoRelease()");
  await until(`document.querySelector("[data-palette-answer-text]")?.textContent === "Heard: hello (done)"`, "the text settles");
  assert(await s.eval(`document.querySelector('${PALETTE}').textContent.includes("Echo")`), "the text answer's heading");
  await press("Escape", "Escape", 27);
  await until(`document.querySelector('${PALETTE} input')?.placeholder === "Search issues, or jump to…"`, "Esc backs out of the mode");
  await press("Escape", "Escape", 27);
  await until(`!document.querySelector('${PALETTE}')`, "Esc closes the palette");
  checks.push("a mode that answers in text streams it into the palette before it settles; Esc leaves the mode, then closes");

  // 4. Withdrawal, on an open timesheet with a query bar.
  await s.navigate(`${base}/timesheet`);
  await s.eval("window.__sameDocument = true");
  await until(`!!document.querySelector('input[aria-label="Ask AI for a query"]')`, "Ask before withdrawal");
  const before = aiRequests();
  aiEnabled = false; await refresh();
  await until(`!document.querySelector('[role=group][aria-label="Query mode"]') && !!document.querySelector('textarea[aria-label="SLQ query"]')`, "the bar is plain SLQ");
  assert.deepEqual(await owners("query.input.mode"), ["echo"]);
  assert.deepEqual(await owners("palette.mode"), ["echo"]);
  await s.click('textarea[aria-label="SLQ query"]');
  await press("i", "KeyI", 73, 2);
  await new Promise(r => setTimeout(r, 200));
  assert.equal(await s.eval(`!!document.querySelector('input[aria-label="Ask AI for a query"]') || !!document.querySelector('[role=group][aria-label="Query mode"]')`), false, "mod+I offers nothing");
  await openPalette();
  await typeText("render farm");
  await until(`[...document.querySelectorAll('${PALETTE} button')].some((b) => b.innerText.includes("say it back"))`, "echo still offered");
  assert.equal(await s.eval(`[...document.querySelectorAll('${PALETTE} button')].some((b) => b.innerText.includes("search by meaning"))`), false, "no Ask entry");
  await new Promise(r => setTimeout(r, 1200));
  assert.equal(aiRequests(), before, "no request reached /ai, /search/semantic, /slq/nl or /plugins/ai after withdrawal");
  assert.equal(await s.eval("window.__sameDocument"), true, "no reload");
  await press("Escape", "Escape", 27);
  await s.screenshot("/tmp/radd-contributed-modes-withdrawn.png");
  checks.push("dropping ai removes Ask from the palette and the bar (plain SLQ, no toggle, mod+I inert) with no reload and no AI request; echo's palette mode stays");

  // 5. Re-listing restores each exactly once.
  aiEnabled = true; aiVersion += 1; await refresh();
  await until(`document.querySelectorAll('[role=group][aria-label="Query mode"] button').length === 2`, "the toggle returns");
  // Nobody chose a mode on this page (mod+I offered nothing while withdrawn) and the bar is empty:
  // it opens on Ask again, as it did on arrival.
  assert.deepEqual(await toggles(), [["SLQ", "false"], ["Ask", "true"]]);
  await openPalette();
  await typeText("render farm");
  await until(`[...document.querySelectorAll('${PALETTE} button')].filter((b) => b.innerText.includes("search by meaning")).length === 1`, "Ask returns once");
  assert.deepEqual(await owners("palette.mode"), ["ai", "echo"]);
  assert.deepEqual(await owners("query.input.mode"), ["ai", "echo"]);
  await press("Escape", "Escape", 27);
  checks.push("re-listing ai restores Ask in the palette and the bar, exactly once each");

  assert(!s.consoleErrors.some(error => /TypeError|Minified React error|Invalid hook|Uncaught/.test(error)), JSON.stringify(s.consoleErrors));
  console.log(JSON.stringify({passed: true, checks, requests: requests.length, asks: asks.length}));
} catch (error) {
  console.error(JSON.stringify({errors: browser?.session.consoleErrors, requests: requests.slice(-30).map(r => r.method + " " + r.route)}, null, 1));
  throw error;
} finally {
  await browser?.close();
  server.closeAllConnections();
  server.close();
}
