/** RADD-1401: the public survey page is the csat remote's and a mailed body reads as the mailintake
 * remote draws it — against synthetic HTTP fixtures, never a real instance. The ACTUAL remotes are
 * served from their ui/dist.
 *
 *   1. an ANONYMOUS visitor (a fresh profile, /auth/me answers the Anyone principal) opens the
 *      survey link: the host's public frame — no shell — loads the csat remote, which draws the page
 *      at the pattern `/public/csat/$token`; `?rating=4` preselects a star, a rating submits, the
 *      visitor stays on the page, and asks the server for nothing but who it is, the manifest and
 *      the survey;
 *   2. an unknown token says the link is unavailable;
 *   3. with csat off, the same link is the host's "unavailable" notice and no survey is asked for;
 *   4. signed in, an issue whose description and comment carry a signature annotation read with
 *      it folded under "Show signature" (the mailintake remote's `content.body` claim); "Not a
 *      signature" posts the restore and the description reads whole;
 *   5. with mailintake withdrawn — no reload — the comment reads whole, as any other comment.
 */
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
import {mkdtemp} from "node:fs/promises";
import {openBrowser, until} from "./lib/cdp.mjs";
import {CORE_PLUGINS} from "./lib/core-plugins.mjs";
import {remoteFile, serveBuiltSpa} from "./lib/spa-server.mjs";

const REMOTES = ["csat", "mailintake"];
for (const name of REMOTES) assert(existsSync(remoteFile(name, "remoteEntry.js")), `build the ${name} remote first (node scripts/build-all.mjs)`);

const anyone = {id: "anyone", name: "Anyone", email: "", anonymous: true, global_role: "member", instance_role: "member", permissions: [], timezone: ""};
const admin = {id: "admin", name: "Desk Agent", email: "agent@example.test", global_role: "admin", instance_role: "admin", permissions: ["*"], timezone: "UTC"};
let signedIn = false, csatOn = true, mailOn = true;
const TOKEN = "tok-123";
let survey = {item_key: "DESK-7", item_title: "The printer on floor 3 jams", rating: null, responded_at: null};
const submissions = [], restores = [];

const project = {id: "project", key: "DESK", name: "Desk", permissions: ["*"], created_at: "2026-01-01"};
const states = ["Open", "Done"].map((name, i) => ({id: `state-${i}`, name, category: i ? "done" : "todo", category_key: i ? "done" : "todo", position: i, project_id: project.id}));
const SIGNATURE = "Best regards,\nSam Requester";
const item = {id: "issue", key: "DESK-7", project_id: project.id, number: 7, title: survey.item_title,
  description: `The printer jams on every job since Monday.\n\n${SIGNATURE}`, email_signature: SIGNATURE, state: states[0],
  priority: "normal", kind: "issue", labels: [], custom_fields: {},
  capabilities: {can_update: true, can_comment: true, can_transition: true},
  links: {incoming: [], outgoing: []}, created_at: "2026-01-01", updated_at: "2026-01-01"};
const comments = [{id: "mailed", entity_type: "item", entity_id: item.id, author: null, body: "Still jamming this morning.\n\nThanks,\nSam",
  email_signature: "Thanks,\nSam", is_thread: false, reply_count: 0, visibility: "public", visible_to_teams: [], anchor: null,
  parent_comment_id: null, resolved_at: null, resolved_by: null, created_at: "2026-01-01", updated_at: "2026-01-01", can_resolve: false}];

let requests = [];
const spa = await serveBuiltSpa(async (req, res, url) => {
  if (url.pathname.startsWith("/plugins/")) {
    requests.push({route: url.pathname, method: req.method});
    if (!REMOTES.includes(url.pathname.split("/")[2])) {res.writeHead(404); res.end(); return true;}
    return false;
  }
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    requests.push({route, method: req.method, body});
    let data = [], status = 200;
    if (route === "/auth/me") data = signedIn ? admin : anyone;
    else if (route === "/capabilities") data = {capabilities: [], nav: [], view_types: [], widget_types: [],
      plugins: [...CORE_PLUGINS, ...(csatOn ? ["csat"] : []), ...(mailOn ? ["mailintake"] : [])],
      remotes: [...(csatOn ? [{name: "csat", remote_entry: "/plugins/csat/remoteEntry.js", ui_api_version: "2.0.0"}] : []),
        ...(mailOn ? [{name: "mailintake", remote_entry: "/plugins/mailintake/remoteEntry.js", ui_api_version: "2.0.0"}] : [])]};
    else if (route === `/public/csat/${TOKEN}`) {
      if (req.method === "POST") {submissions.push(body); survey = {...survey, rating: body.rating, responded_at: "2026-09-26T10:00:00Z"};}
      data = survey;
    }
    else if (route.startsWith("/public/csat/")) {status = 404; data = {detail: "Survey not found"};}
    else if (route === `/mail/signatures/item/${item.id}/restore`) {restores.push(route); item.email_signature = null; status = 204;}
    else if (route === "/auth/me/preferences") data = {};
    else if (route === "/projects/summary") data = {total: 1, related_count: 0, permissions: ["*"]};
    else if (route === "/page-spaces/summary") data = {total: 0, permissions: []};
    else if (route === "/projects/project" || route === "/projects/by-key/DESK") data = project;
    else if (route === "/projects") data = [project];
    else if (route.startsWith("/items/by-key/") || route === "/items/issue") data = item;
    else if (route === "/fields/writable") data = {readonly_fields: []};
    else if (route === "/screens/effective") data = {fields: []};
    else if (route === "/states") data = states;
    else if (route.endsWith("/comments/feed")) data = {comments, older_cursor: null};
    else if (route.endsWith("/replies")) data = {comments: [], older_cursor: null};
    else if (route.endsWith("/allowed-transitions")) data = {mode: "guards", targets: states.map((s) => ({state_id: s.id, allowed: true, failures: []}))};
    else if (route.endsWith("/watchers")) data = {watching: false, watchers: []};
    else if (route.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (route === "/instance") data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (route.endsWith("/mail-contacts")) data = [];
    else if (route.endsWith("/csat")) data = null;
    else if (route.includes("/resolve")) data = {value: false};
    else if (route.endsWith("/timelogging")) data = {enabled: false};
    res.writeHead(status, {"content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0)});
    res.end(status === 204 ? "" : JSON.stringify(data)); return true;
  }
});
const base = spa.origin;

let browser;
const checks = [];
try {
  browser = await openBrowser({port: 18873, profile: await mkdtemp("/tmp/radd-csat-mail-"), scale: 1});
  const s = browser.session;
  const text = (t) => s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
  const apiRoutes = () => requests.filter((r) => !r.route.startsWith("/plugins/")).map((r) => r.route);

  // 1. The anonymous visitor.
  requests = [];
  await s.navigate(`${base}/public/csat/${TOKEN}?rating=4`, 300);
  await until(s, () => s.eval(`!!document.querySelector('[data-csat-survey="${TOKEN}"]')`), "survey page did not render");
  assert(requests.some((r) => r.route === "/plugins/csat/remoteEntry.js"), "the page came from the csat remote");
  assert.equal(await s.eval(`document.querySelector("h1")?.textContent`), "Radd", "the host draws the frame");
  assert.equal(await s.eval(`!!document.querySelector("aside, header nav")`), false, "no app shell around a public page");
  assert(await text(survey.item_title), "the survey names its issue");
  assert.equal(await s.eval(`document.querySelector('[role=radio][aria-checked=true]')?.getAttribute('aria-label')`), "4 — Satisfied", "?rating=4 preselects");
  await s.eval(`document.querySelector("textarea").focus()`);
  await s.send("Input.insertText", {text: "Fixed within the hour"});
  await s.click('button[type="submit"]');
  await until(s, () => s.eval(`!!document.querySelector("[data-csat-recorded]")`), "the thanks state never showed");
  assert.deepEqual(submissions, [{rating: 4, comment: "Fixed within the hour"}], "the rating and comment were posted");
  assert.equal(await s.eval("location.pathname"), `/public/csat/${TOKEN}`, "the visitor was never sent to sign in");
  const asked = [...new Set(apiRoutes())].sort();
  assert.deepEqual(asked, ["/auth/me", "/capabilities", `/public/csat/${TOKEN}`], `a visitor asks only for itself, the manifest and the survey: ${asked}`);
  checks.push("anonymous survey from the csat remote", "?rating preselects", "rating submits", "no redirect", "visitor asks nothing else");

  // 2. An unknown token.
  await s.navigate(`${base}/public/csat/nope`, 300);
  await until(s, () => text("This survey link isn't available"), "unknown token not explained");
  checks.push("unknown token is unavailable");

  // 3. csat off: the host's notice, and no survey request.
  csatOn = false; requests = [];
  await s.navigate(`${base}/public/csat/${TOKEN}`, 300);
  await until(s, () => s.eval(`!!document.querySelector('[data-plugin-missing="page"]')`), "no unavailable notice with csat off");
  assert(!apiRoutes().some((r) => r.startsWith("/public/csat/")), "nothing asked the survey endpoint");
  assert(!(await s.eval(`!!document.querySelector("[data-csat-survey]")`)));
  checks.push("csat off → unavailable");
  csatOn = true;

  // 4. Signed in: mailed bodies read folded.
  signedIn = true; requests = [];
  await s.navigate(`${base}/issues/DESK-7`, 300);
  await until(s, () => s.eval(`!!document.querySelector('[data-mail-signed="issue"]') && !!document.querySelector('[data-mail-signed="mailed"]')`), "mailed bodies were not claimed");
  assert(requests.some((r) => r.route === "/plugins/mailintake/remoteEntry.js"), "the claim came from the mailintake remote");
  assert(await text("The printer jams on every job since Monday."), "the text above the signature reads");
  assert(!(await text("Best regards,")), "the description's signature is folded");
  assert(!(await text("Thanks,\nSam")) && await text("Still jamming this morning."), "the comment's signature is folded");
  await s.eval(`document.querySelector('[data-mail-signed="issue"] summary').click()`);
  await until(s, () => text("Best regards,"), "Show signature did not unfold");
  await s.eval(`Array.from(document.querySelectorAll('[data-mail-signed="issue"] button')).find((b) => b.textContent.trim() === "Not a signature").click()`);
  await until(s, () => s.eval(`!document.querySelector('[data-mail-signed="issue"]')`), "the restored description still reads folded");
  assert.deepEqual(restores, [`/mail/signatures/item/${item.id}/restore`]);
  assert(await text("Best regards,"), "the whole description reads after the restore");
  checks.push("mailed description folded", "mailed comment folded", "Show signature", "Not a signature restores");

  // 5. mailintake withdrawn, no reload: the comment reads whole.
  await s.eval("window.__stillHere = true");
  mailOn = false;
  await s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey: ["capabilities"]})`);
  await until(s, () => s.eval(`!document.querySelector('[data-mail-signed]')`), "the claim outlived its plugin");
  await until(s, () => s.eval(`document.body.innerText.includes("Thanks,") && document.body.innerText.includes("Sam")`), "the comment's signature text is missing without mailintake");
  assert.equal(await s.eval(`Array.from(document.querySelectorAll("summary")).some((e) => e.textContent === "Show signature")`), false);
  assert.equal(await s.eval("window.__stillHere"), true, "withdrawal did not reload the page");
  checks.push("mailintake off → plain body, live");

  assert.deepEqual(s.consoleErrors, [], "no console errors");
  checks.push("no console errors");
  console.log(JSON.stringify({passed: true, checks}));
} catch (error) {
  if (browser) await browser.session.screenshot("/tmp/radd-csat-mail-failure.png");
  throw error;
} finally {
  await browser?.close();
  await spa.close();
}
