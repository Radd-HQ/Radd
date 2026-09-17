/** Built-SPA smoke check: no database, credentials, external API or LLM needed. */
import assert from "node:assert/strict";
import http from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser } from "./lib/cdp.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
// RADD-988: built SPA against a local fixture API; no live settings are changed.
const rows = ["General", "Private"].map((name, index) => ({
  id: `00000000-0000-4000-8000-00000000000${index}`, name, host_type: "filesystem",
  endpoint: "", access_key: "", has_secret_key: false, bucket: "", region: "", secure: false,
  root_dir: "/tmp/" + name, delivery_mode: "proxy", presign_expiry_seconds: null,
  user_selectable: true, is_default: index === 0, source: "user", email_images_allowed: false,
  attachment_count: 0, total_bytes: 0,
}));
const writes = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname.startsWith("/api/")) {
    let data = [];
    if (req.method === "PATCH" && url.pathname.includes("/storage/hosts/")) {
      let raw = "";
      for await (const chunk of req) raw += chunk;
      const patch = JSON.parse(raw);
      const row = rows.find(row => url.pathname.endsWith(row.id));
      Object.assign(row, patch); writes.push(patch); data = row;
    } else if (url.pathname.endsWith("/storage/hosts")) data = rows;
    else if (url.pathname.endsWith("/auth/me")) data = {id: "admin", name: "Admin", email: "admin@example.test", instance_role: "admin", permissions: ["global.manage"], timezone: "UTC"};
    else if (url.pathname.endsWith("/projects/summary") || url.pathname.endsWith("/page-spaces/summary")) data = {total: 0, permissions: []};
    else if (url.pathname.endsWith("/preferences")) data = {};
    else if (url.pathname.includes("capabilities")) data = {capabilities: [], nav: [], plugins: [], ui: []};
    else if (url.pathname.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (url.pathname.endsWith("/ai/status")) data = {enabled: false, features: {}};
    else if (url.pathname.endsWith("/instance")) data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (url.pathname.includes("/audit")) data = [];
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
  browser = await openBrowser({port: Number(process.env.RADD_BROWSER_PORT ?? 18791), profile: await mkdtemp("/tmp/radd-email-storage-"), scale: 1});
  const s = browser.session;
  await s.navigate(base + "/settings/storage");
  const edit = async name => {
    await s.click('button[aria-label="Actions for ' + name + '"]');
    await new Promise(resolve => setTimeout(resolve, 150));
    await s.click('[role="menuitem"]', text => text.trim() === "Edit");
    await new Promise(resolve => setTimeout(resolve, 250));
  };
  const checkbox = `[...document.querySelectorAll('[role="dialog"] label')].find(l => l.textContent.includes('Allow images in service-desk email')).querySelector('input')`;
  await edit("General");
  assert.equal(await s.eval(checkbox + '.checked'), false);
  assert(await s.eval(`document.querySelector('[role="dialog"]').innerText.includes('Restricted files are excluded')`));
  await s.eval(checkbox + '.click()');
  await s.click('button[type="submit"]', text => text === "Save changes");
  await new Promise(resolve => setTimeout(resolve, 400));
  assert.equal(writes.length, 1);
  assert.equal(writes[0].email_images_allowed, true);
  assert.equal(rows[1].email_images_allowed, false);
  await s.navigate(base + "/settings/storage");
  assert(await s.eval(`document.body.innerText.includes('Email images')`));
  await edit("General");
  assert.equal(await s.eval(checkbox + '.checked'), true);
  await s.eval(checkbox + '.scrollIntoView({block: "center"})');
  const geometry = await s.eval(`(() => {const r = (${checkbox}).closest('label').getBoundingClientRect(); return {width: r.width, height: r.height, top: r.top, bottom: r.bottom, viewport: innerHeight};})()`);
  assert(geometry.width > 200 && geometry.height > 10 && geometry.top >= 0 && geometry.bottom <= geometry.viewport);
  await s.screenshot("/tmp/radd-988-storage-settings.png");
  await s.click('[role="dialog"] button', text => text === "Cancel");
  await edit("Private");
  assert.equal(await s.eval(checkbox + '.checked'), false);
  await s.click('[role="dialog"] button', text => text === "Cancel");
  await edit("General");
  await s.eval(checkbox + '.click()');
  await s.click('button[type="submit"]', text => text === "Save changes");
  await new Promise(resolve => setTimeout(resolve, 300));
  assert.equal(writes[1].email_images_allowed, false);
  assert(!await s.eval(`document.body.innerText.includes('Email images')`));
  await s.click('button', text => text === "Add host");
  assert.equal(await s.eval(checkbox + '.checked'), false);
  assert.equal(s.consoleErrors.filter(e => !e.includes("WebSocket")).length, 0, s.consoleErrors.join("\n"));
  console.log("Storage email opt-in: default off, selective enable, PATCH payload, reopen persistence, private exclusion, visible layout, disable, new-host default and clean console passed.");
} catch (error) {
  if (browser) { console.error(browser.session.consoleErrors); console.error(await browser.session.eval("document.body.innerText")); await browser.session.screenshot("/tmp/radd-988-proof-failure.png"); }
  throw error;
} finally { browser?.close(); server.close(); }
