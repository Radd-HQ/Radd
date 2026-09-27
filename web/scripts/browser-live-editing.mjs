/** RADD-1397: co-editing's UI is the collab plugin's, proven with the ACTUAL collab remote (served
 * from its ui/dist) against synthetic HTTP fixtures and a synthetic y-websocket room — never a real
 * instance.
 *
 *   1. with collab listed, a reader sees the colleague already in the room (the remote's presence
 *      chrome), and Edit opens a LIVE session: the remote's binding makes the host's editor a
 *      shared copy (Done, not Save; "Editing together"), a colleague's paragraph arrives in it,
 *      and the elected saver writes both through the page's own save with the session's voucher;
 *   2. with collab dropped from capabilities, the same page edits with Save and Cancel, the save
 *      carries `expected_version`, and nothing asks for /plugins/collab/ or /collab/;
 *   3. re-listing collab restores the session exactly once — one join, one socket, one presence
 *      strip, one bound editor.
 */
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { openBrowser, until } from "./lib/cdp.mjs";
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";
import { createMockLiveRoom } from "./lib/mock-live-room.mjs";
import { serveBuiltSpa } from "./lib/spa-server.mjs";

let collabEnabled = true, collabVersion = 1;
const user = { id: "admin", name: "Fixture Editor", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC" };
const colleague = { id: "grace", name: "Grace Fixture", color: "var(--chart-todo)", emoji: null };
const space = { id: "space", slug: "handbook", name: "Handbook", permissions: ["*"], position: 0, page_count: 1 };
let page = { id: "page", number: 7, space_id: space.id, space, slug: "live-page", path: "live-page", title: "Live page",
  parent_id: null, position: 0, version: 3, created_by: user.id, updated_by: user.id, created_at: "2026-01-01",
  updated_at: "2026-01-01", archived_at: null, labels: [], breadcrumb: [], body: "The page before anyone edited it." };
const room = createMockLiveRoom({ peer: colleague });
const requests = [], patches = [], joins = [];
let sessions = 0;

const spa = await serveBuiltSpa(async (req, res, url) => {
  if (url.pathname.startsWith("/plugins/")) {
    requests.push({ route: url.pathname, method: req.method });
    if (!url.pathname.startsWith("/plugins/collab/")) { res.writeHead(404); res.end(); return true; }
    return false;
  }
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    requests.push({ route, method: req.method, body });
    let data = [], status = 200;
    if (route === "/auth/me") data = user;
    else if (route.includes("capabilities")) data = { capabilities: [], nav: [], ui: [],
      plugins: [...CORE_PLUGINS, ...(collabEnabled ? ["collab"] : [])],
      remotes: collabEnabled ? [{ name: "collab", remote_entry: `/plugins/collab/remoteEntry.js?v=${collabVersion}`, ui_api_version: "2.0.0" }] : [] };
    else if (/^\/collab\/pages\/page\/join$/.test(route)) {
      // The backend's rule, in miniature: an editor seeds a room whose document is still empty.
      const session = `session-${++sessions}`;
      joins.push({ role: body.role, session });
      data = { session, role: body.role, seed: body.role === "editor" && room.empty, page_version: page.version };
    }
    else if (route === "/pages/page" && req.method === "PATCH") {
      patches.push(body);
      if (!body.collab_session && body.expected_version !== undefined && body.expected_version !== page.version) {
        status = 409; data = { detail: "This page changed since you opened it" };
      } else {
        page = { ...page, body: body.body ?? page.body, version: body.collab_session && !body.final ? page.version : page.version + 1 };
        data = page;
      }
    }
    else if (route === "/auth/me/preferences") data = {};
    else if (route === "/projects/summary") data = { total: 0, related_count: 0, permissions: ["*"] };
    else if (route === "/page-spaces/summary") data = { total: 1, permissions: ["*"] };
    else if (route === "/page-spaces") data = [space];
    else if (route === "/page-spaces/by-identity/handbook" || route === "/page-spaces/space") data = space;
    else if (route === "/page-spaces/space/pages") data = [page];
    else if (route === "/pages/by-path/handbook/live-page" || route === "/pages/page") data = page;
    else if (route.endsWith("/comments/feed")) data = { comments: [], older_cursor: null };
    else if (route.endsWith("/watch")) data = { watching: false };
    else if (route.includes("/notifications")) data = { items: [], notifications: [], unread_count: 0, total: 0 };
    else if (route === "/instance") data = { work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5 };
    else if (route.includes("/resolve")) data = { value: false };
    else if (route === "/users/directory") data = [user, { id: colleague.id, name: colleague.name }];
    res.writeHead(status, { "content-type": "application/json", "X-Total-Count": String(Array.isArray(data) ? data.length : 0) });
    res.end(JSON.stringify(data)); return true;
  }
  if (url.pathname.startsWith("/shared/")) requests.push({ route: url.pathname, method: req.method });
});
spa.server.on("upgrade", (req, socket) => {
  requests.push({ route: new URL(req.url, "http://fixture").pathname.replace("/api/v1", ""), method: "UPGRADE" });
  if (collabEnabled && req.url.startsWith("/api/v1/collab/pages/page")) room.upgrade(req, socket);
  else socket.destroy();
});

const checks = [];
let browser;
try {
  browser = await openBrowser({ port: 18871, profile: await mkdtemp("/tmp/radd-live-editing-"), width: 1500, height: 1000, scale: 1 });
  const s = browser.session;
  const count = (selector) => s.eval(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  const refresh = () => s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
  const collabRequests = () => requests.filter((r) => /^\/(?:plugins\/collab\/|collab\/)/.test(r.route.replace(/^\/api\/v1/, ""))).length;
  const EDITOR = `document.querySelector('[aria-label="Edit page content"] .ProseMirror')`;
  const PRESENCE = `(document.querySelector('[aria-label^="In this page:"]')?.getAttribute("aria-label") ?? "")`;
  const typeAtEnd = async (text) => {
    await s.eval(`(() => {
      const view = ${EDITOR}; view.focus();
      const range = document.createRange(); range.selectNodeContents(view); range.collapse(false);
      const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
    })()`);
    await s.send("Input.insertText", { text });
  };

  // --- 1. collab listed: a reader is present, an editor is live ---
  await s.navigate(`${spa.origin}/pages/handbook/live-page`);
  assert(await s.eval(`matchMedia("(hover: hover)").matches`), "the browser must report a hover-capable pointer");
  await until(s, `document.body.innerText.includes("The page before anyone edited it.")`, "the page renders");
  await until(s, `${PRESENCE}.includes("1 editing") && ${PRESENCE}.includes("1 viewing")`, "the reader sees the colleague in the room");
  assert.deepEqual(joins.map((j) => j.role), ["observer"], "reading joins as an observer");
  for (const file of ["/plugins/collab/remoteEntry.js", "/plugins/collab/room.js"]) {
    assert(requests.some((r) => r.route === file), `${file} was loaded`);
  }
  assert(!requests.some((r) => r.route === "/plugins/collab/bind-editor.js"), "reading loads no editor binding");
  assert(!requests.some((r) => r.route.startsWith("/shared/prosemirror-")), "reading loads no editor runtime");
  checks.push("with collab listed, a reader joins as an observer and the remote's presence strip shows the colleague (1 editing · 1 viewing); neither the binding chunk nor the shared editor runtime has loaded");

  await s.click("button", (text) => text.trim() === "Edit page");
  await until(s, `${EDITOR}?.getAttribute("contenteditable") === "true"`, "the bound editor accepts typing");
  await until(s, `${EDITOR}.innerText.includes("The page before anyone edited it.")`, "the seeded document is bound");
  assert.deepEqual(joins.map((j) => j.role), ["observer", "editor"]);
  assert(requests.some((r) => r.route === "/plugins/collab/bind-editor.js"), "editing loads the remote's binding");
  for (const shim of ["model", "state", "view"]) {
    assert(requests.some((r) => r.route === `/shared/prosemirror-${shim}.js`), `the binding runs on the host's prosemirror-${shim}`);
  }
  const panel = await s.eval(`(() => {
    const panel = document.querySelector('[aria-label="Edit page content"]');
    const buttons = [...panel.querySelectorAll("button")].map((b) => b.textContent.trim());
    return { buttons, bar: panel.querySelector(".radd-rich-editor")?.innerText ?? "",
      saver: panel.querySelector("[data-collab-saver]")?.getAttribute("data-collab-saver") ?? "absent" };
  })()`);
  assert(panel.buttons.includes("Done") && !panel.buttons.includes("Save") && !panel.buttons.includes("Cancel"), JSON.stringify(panel.buttons));
  assert.match(panel.bar, /Editing together/);
  assert.equal(panel.saver, "true", "this browser is the elected saver");
  await until(s, `${PRESENCE}.includes("2 editing")`, "both editors are present");
  await s.screenshot("/tmp/radd-live-editing-live.png");
  checks.push("Edit opens a live session from the collab remote: the host's editor bound to the room (Done, no Save/Cancel, 'Editing together'), the page header says 2 editing, and this client is the elected saver");

  const typed = " Typed in the shared copy.";
  await typeAtEnd(typed);
  room.peerWrites("A paragraph from Grace.");
  await until(s, `${EDITOR}.innerText.includes("A paragraph from Grace.")`, "the colleague's paragraph arrives in the editor");
  for (let i = 0; i < 150 && !patches.some((p) => (p.body ?? "").includes("A paragraph from Grace.") && p.body.includes(typed.trim())); i++) {
    await new Promise((r) => setTimeout(r, 40));
  }
  const autosave = patches.find((p) => (p.body ?? "").includes("A paragraph from Grace.") && p.body.includes(typed.trim()));
  assert(autosave, "the saver autosaved both lines: " + JSON.stringify(patches));
  assert.equal(autosave.collab_session, joins[1].session, "the save carries the session's voucher");
  assert.equal(autosave.expected_version, undefined, "a vouched save skips the version check");
  checks.push("typing and a colleague's paragraph both land in the bound editor, and the elected saver writes both through the page's own PATCH with the session as its voucher (no expected_version)");

  await s.click("button", (text) => text.trim() === "Done");
  await until(s, `!document.querySelector('[aria-label="Edit page content"]')`, "Done leaves edit mode");
  const final = patches.at(-1);
  assert.equal(final.final, true, "Done sends the final save: " + JSON.stringify(final));
  assert.equal(final.collab_session, joins[1].session);
  checks.push("Done sends the session's final save and returns to reading");

  // --- 2. collab dropped: the ordinary flow, and not one request for collab ---
  collabEnabled = false; await refresh();
  await until(s, `!document.querySelector('[aria-label^="In this page:"]')`, "the presence strip is withdrawn");
  for (let i = 0; i < 100 && room.open > 0; i++) await new Promise((r) => setTimeout(r, 40));
  assert.equal(room.open, 0, "the observer session closed its socket");
  const before = collabRequests();
  await s.click("button", (text) => text.trim() === "Edit page");
  await until(s, `${EDITOR}?.getAttribute("contenteditable") === "true"`, "the ordinary editor");
  const legacy = await s.eval(`(() => {
    const panel = document.querySelector('[aria-label="Edit page content"]');
    return { buttons: [...panel.querySelectorAll("button")].map((b) => b.textContent.trim()),
      bar: panel.querySelector(".radd-rich-editor").innerText, saver: !!panel.querySelector("[data-collab-saver]") };
  })()`);
  assert(legacy.buttons.includes("Save") && legacy.buttons.includes("Cancel") && !legacy.buttons.includes("Done"), JSON.stringify(legacy.buttons));
  assert.match(legacy.bar, /Switch to plain text editing/);
  assert(!legacy.saver);
  await typeAtEnd(" Saved the ordinary way.");
  // Milkdown publishes the markdown 200 ms after the last change; a person pressing Save is slower.
  await new Promise((r) => setTimeout(r, 400));
  const versionBefore = page.version;
  await s.click("button", (text) => text.trim() === "Save");
  await until(s, `!document.querySelector('[aria-label="Edit page content"]')`, "Save leaves edit mode");
  const ordinary = patches.at(-1);
  assert.equal(ordinary.expected_version, versionBefore, JSON.stringify(ordinary));
  assert.equal(ordinary.collab_session, undefined);
  assert.match(ordinary.body, /Saved the ordinary way\./);
  await new Promise((r) => setTimeout(r, 1000));
  assert.equal(collabRequests(), before, "nothing asked for /plugins/collab/ or /collab/: " +
    JSON.stringify(requests.slice(-20).map((r) => r.method + " " + r.route)));
  await s.screenshot("/tmp/radd-live-editing-ordinary.png");
  checks.push("with collab dropped from capabilities the same page edits with Save and Cancel, saves with expected_version, and makes no /plugins/collab/ or /collab/ request");

  // --- 3. re-listed: the session returns, once ---
  const joinsBefore = joins.length, upgradesBefore = room.upgrades.length;
  collabEnabled = true; collabVersion += 1; await refresh();
  await until(s, `${PRESENCE}.includes("1 editing")`, "the presence strip returns");
  await new Promise((r) => setTimeout(r, 800));
  assert.equal(joins.length - joinsBefore, 1, "one join: " + JSON.stringify(joins.slice(joinsBefore)));
  assert.equal(joins.at(-1).role, "observer");
  assert.equal(room.upgrades.length - upgradesBefore, 1, "one socket");
  assert.equal(await count("[data-editing-now]"), 1, "one presence strip");
  await s.click("button", (text) => text.trim() === "Edit page");
  await until(s, `${EDITOR}?.getAttribute("contenteditable") === "true"`, "the bound editor again");
  await until(s, `${PRESENCE}.includes("2 editing")`, "both editors again");
  assert.equal(await count('[aria-label="Edit page content"] .ProseMirror'), 1, "one editor");
  assert.equal(await count("[data-editing-now]"), 1);
  assert.equal(await count("[data-collab-saver]"), 1);
  assert.match(await s.eval(`document.querySelector('[aria-label="Edit page content"] .radd-rich-editor').innerText`), /Editing together/);
  assert.equal(joins.at(-1).role, "editor");
  await s.click("button", (text) => text.trim() === "Done");
  await until(s, `!document.querySelector('[aria-label="Edit page content"]')`, "Done again");
  checks.push("re-listing collab restores the session exactly once: one observer join and one socket, one presence strip, then one bound editor with Done");

  const errors = s.consoleErrors.filter((error) => !/Failed to load resource/.test(error));
  assert.deepEqual(errors, [], "no console errors");
  console.log(JSON.stringify({ passed: true, checks, requests: requests.length, joins: joins.length, patches: patches.length }));
} catch (error) {
  console.error(JSON.stringify({ errors: browser?.session.consoleErrors, joins, patches: patches.slice(-5),
    awareness: [...room.awareness.getStates()].map(([id, state]) => [id, state?.role, state?.user?.name]), open: room.open,
    strip: await browser?.session.eval(`document.querySelector("[data-editing-now]")?.outerHTML ?? "none"`).catch(() => "?"),
    requests: requests.slice(-30).map((r) => r.method + " " + r.route) }, null, 1));
  throw error;
} finally {
  await browser?.close();
  room.close();
  spa.server.closeAllConnections();
  await spa.close();
}
