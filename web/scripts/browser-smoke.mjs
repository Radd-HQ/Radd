/** Built-SPA smoke check: no database, credentials, external API or LLM needed. */
import assert from "node:assert/strict";
import http from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser } from "./lib/cdp.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
let account = "A";
const startedSearches = new Set();
const abortedSearches = new Set();
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname.startsWith("/api/")) {
    if (url.pathname === "/api/v1/search") {
      const q = url.searchParams.get("q");
      startedSearches.add(q);
      if (q === "before" || q === "closing") {
        res.on("close", () => { if (!res.writableEnded) abortedSearches.add(q); });
        return; // Keep a real HTTP response pending until the browser aborts it.
      }
      res.writeHead(200, {"content-type": "application/json"});
      res.end(JSON.stringify({results: []}));
      return;
    }
    if (url.pathname.endsWith("/auth/logout")) { account = null; res.writeHead(204); res.end(); return; }
    if (url.pathname.endsWith("/auth/login")) { account = "B"; res.writeHead(204); res.end(); return; }
    let data = [];
    if (url.pathname.endsWith("/auth/me")) {
      if (!account) { res.writeHead(401, {"content-type": "application/json"}); res.end('{"detail":"Sign in"}'); return; }
      data = {id: account, name: `Account ${account}`, email: `${account}@example.com`, instance_role: "member", permissions: [], timezone: "UTC"};
    } else if (url.pathname.endsWith("/projects")) {
      data = account === "A" ? [{id: "private-A", key: "PRIVATE", name: "Account A private project", created_at: "2026-01-01", permissions: []}] : [];
      res.setHeader("X-Total-Count", String(data.length));
    } else if (url.pathname.endsWith("/projects/summary")) data = {total: account === "A" ? 1 : 0, related_count: 0, permissions: []};
    else if (url.pathname.endsWith("/page-spaces/summary")) data = {total: 0, permissions: []};
    else if (url.pathname.endsWith("/preferences")) data = {};
    else if (url.pathname.includes("capabilities")) data = {capabilities: [], nav: [], plugins: [], ui: []};
    else if (url.pathname.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (url.pathname.endsWith("/ai/status")) data = {enabled: false, features: {}};
    else if (url.pathname.endsWith("/instance")) data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (url.pathname.includes("login-options")) data = {ldap_enabled: false, sso_enabled: false};
    res.writeHead(200, {"content-type": "application/json"}); res.end(JSON.stringify(data)); return;
  }
  let file = path.resolve(dist, "." + url.pathname);
  if (!file.startsWith(dist) || !existsSync(file) || statSync(file).isDirectory()) file = path.join(dist, "index.html");
  const mime = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".html": "text/html"}[path.extname(file)] ?? "application/octet-stream";
  res.writeHead(200, {"content-type": mime}); res.end(readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await openBrowser({port: Number(process.env.RADD_BROWSER_PORT ?? 18786), profile: await mkdtemp("/tmp/radd-smoke-"), scale: 1});
  const s = browser.session;
  await s.navigate(base + "/projects");
  assert(await s.eval(`document.body.innerText.includes('Account A private project')`));
  for (const width of [390, 768, 1440]) {
    await s.send("Emulation.setDeviceMetricsOverride", {width, height: 900, deviceScaleFactor: 1, mobile: width < 768});
    await new Promise(resolve => setTimeout(resolve, 100));
    assert(await s.eval(`document.documentElement.scrollWidth <= innerWidth`));
    if (width === 390) assert.equal(await s.eval(`document.querySelector('aside').getBoundingClientRect().width`), 0);
  }
  const until = async (predicate, message) => {
    for (let i = 0; i < 100; i++) {
      if (await predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error(message + ` (started: ${[...startedSearches]}, aborted: ${[...abortedSearches]})`);
  };
  await s.click('button', text => text.includes("Search issues"));
  await s.click('input[aria-label="Search"]');
  await s.send("Input.insertText", {text: "before"});
  await until(() => startedSearches.has("before"), "first search never started");
  const replaceSearch = async text => {
    await s.eval(`document.querySelector('input[aria-label="Search"]').select()`);
    await s.send("Input.insertText", {text});
  };
  await replaceSearch("after");
  await until(() => startedSearches.has("after") && abortedSearches.has("before"), "superseded search was not aborted");
  await replaceSearch("closing");
  await until(() => startedSearches.has("closing"), "closing search never started");
  await s.send("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape"});
  await until(() => abortedSearches.has("closing"), "closed palette kept its search running");
  await s.eval(`__RADD_QUERY_CLIENT__.setQueryData(['private-test'], {title:'Account A private issue'})`);
  await s.click('button[aria-haspopup="menu"]', text => text.includes("Account A"));
  await s.click('[role="menuitem"]', text => text.includes("Log out"));
  await new Promise(resolve => setTimeout(resolve, 700));
  assert.equal(await s.eval("location.pathname"), "/login");
  await s.click('input[type="email"]');
  await s.send("Input.insertText", {text: "b@example.com"});
  await s.click('input[type="password"]');
  await s.send("Input.insertText", {text: "test-password"});
  await s.click('button[type="submit"]');
  await new Promise(resolve => setTimeout(resolve, 800));
  await s.navigate(base + "/projects");
  assert(!(await s.eval(`document.body.innerText.includes('Account A private')`)));
  assert.equal(await s.eval(`__RADD_QUERY_CLIENT__.getQueryData(['private-test']) ?? null`), null);
  assert.equal(s.consoleErrors.filter(e => !e.includes("WebSocket") && !e.includes("401")).length, 0, s.consoleErrors.join("\n"));
  console.log("Built SPA: responsive shell, real HTTP search cancellation and account A → logout → account B isolation passed.");
} finally { browser?.close(); server.close(); }
