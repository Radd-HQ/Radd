/**
 * RADD-1048 — the retention window is editable, and under the right heading.
 *
 * Built SPA against a local fixture API: no database, credentials or live
 * settings involved. The bug this exists to catch is the one the
 * `AutomaticMessagesPanel` comment already documents from RADD-1045: an
 * `email`-section setting renders wherever that page happens to put it, and
 * "registered, resolving, documented, editable nowhere" type-checks and builds
 * perfectly. A second failure is newer and quieter — the row lands on the page
 * but under "Automatic messages", a heading that describes what the desk SENDS
 * while this setting governs what it KEEPS and DELETES.
 *
 * So: the row is asserted to be inside the Retention section and absent from
 * the Automatic messages one, and the PUT payload is read back, because a card
 * that renders and cannot write is the same defect one layer down.
 */
import assert from "node:assert/strict";
import http from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser } from "./lib/cdp.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const RETENTION_LABEL = "Raw message retention (days)";
const settingRows = [
  {
    key: "mail_ack_body", type: "string", label: "Acknowledgement email",
    description: "Plain-text body of the receipt sent when an email opens a ticket.",
    value: "Your request has been received.", set_here: false,
    default: "Your request has been received.", choices: null, secret: false, section: "email",
  },
  {
    key: "mail_send_resolved", type: "bool", label: "Resolution emails",
    description: "Email the ticket's external contacts when it moves into a done state.",
    value: true, set_here: false, default: true, choices: null, secret: false, section: "email",
  },
  {
    key: "mail_raw_retention_days", type: "int", label: RETENTION_LABEL,
    description: "How long the original bytes of an inbound email are kept. 0 keeps nothing.",
    value: 30, set_here: false, default: 30, choices: null, secret: false, section: "email",
  },
];
const writes = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname.startsWith("/api/")) {
    let data = [];
    if (req.method === "PUT" && url.pathname.endsWith("/scoped-settings")) {
      let raw = "";
      for await (const chunk of req) raw += chunk;
      const body = JSON.parse(raw);
      writes.push(body);
      const row = settingRows.find(row => row.key === body.key);
      Object.assign(row, { value: body.value, set_here: true });
      data = row;
    } else if (url.pathname.endsWith("/scoped-settings")) data = settingRows;
    else if (url.pathname.endsWith("/mail/kinds")) data = { sources: [], senders: [] };
    else if (url.pathname.endsWith("/mail/sources") || url.pathname.endsWith("/mail/senders")) data = [];
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
const settle = (ms = 300) => new Promise(resolve => setTimeout(resolve, ms));
let browser;
try {
  browser = await openBrowser({port: Number(process.env.RADD_BROWSER_PORT ?? 18793), profile: await mkdtemp("/tmp/radd-1048-retention-"), scale: 1});
  const s = browser.session;
  await s.navigate(base + "/settings/email");
  await settle(600);

  // The panel a card's text belongs to, by heading — "is it on the page" is
  // exactly the question that was already answerable and still wrong.
  const sectionText = heading =>
    s.eval(`(() => {
      const h = [...document.querySelectorAll('h3')].find(el => el.textContent.trim() === ${JSON.stringify(heading)});
      return h ? h.closest('section').innerText : null;
    })()`);

  const retention = await sectionText("Retention");
  assert(retention, "Settings → Email has no Retention card");
  assert(retention.includes(RETENTION_LABEL), `Retention card is missing the window:\n${retention}`);

  const automatic = await sectionText("Automatic messages");
  assert(automatic, "Settings → Email has no Automatic messages card");
  assert(!automatic.includes(RETENTION_LABEL), "the retention row is still filed under Automatic messages");
  assert(!automatic.includes("Acknowledgement email"), "the ack body escaped its own panel");
  assert(automatic.includes("Resolution emails"), "excluding by key took the rows that panel owns");

  // The card is real: the input carries the resolved value, and Save writes it.
  const card = '[data-settings-card="retention"]';
  const input = `document.querySelector('${card} input')`;
  assert.equal(await s.eval(`(${input}).value`), "30");
  const box = await s.eval(`(() => {const r = (${input}).getBoundingClientRect(); return {width: r.width, height: r.height};})()`);
  assert(box.width > 100 && box.height > 20, `the editor is not a usable target: ${JSON.stringify(box)}`);

  await s.eval(`(() => {
    const el = ${input};
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, '0');
    el.dispatchEvent(new Event('input', {bubbles: true}));
  })()`);
  await settle(150);
  // Scoped to the card: every row on this page renders a button reading "Save",
  // and the first one belongs to another panel — where it is disabled, so an
  // unscoped click is a no-op that looks exactly like a broken editor.
  assert.equal(
    await s.eval(`[...document.querySelectorAll('${card} button')].find(b => b.textContent.trim() === 'Save').disabled`),
    false,
    "the edit did not mark the row dirty",
  );
  await s.click(`${card} button`, text => text.trim() === "Save");
  await settle(400);
  assert.equal(writes.length, 1, `expected one write, got ${JSON.stringify(writes)}`);
  assert.deepEqual(
    {key: writes[0].key, value: writes[0].value, scope: writes[0].scope},
    {key: "mail_raw_retention_days", value: "0", scope: "instance"},
  );

  await s.navigate(base + "/settings/email");
  await settle(600);
  assert((await sectionText("Retention")).includes("Set here"), "the saved override does not read back");
  // Frame what the proof is about: a screenshot of the fold above it would be
  // an artefact of the wrong card.
  await s.eval(`document.querySelector('${card}').scrollIntoView({block: "center"})`);
  await settle(200);
  await s.screenshot("/tmp/radd-1048-email-retention.png");
  assert.equal(s.consoleErrors.filter(e => !e.includes("WebSocket")).length, 0, s.consoleErrors.join("\n"));
  console.log("Retention card: own heading, row excluded from Automatic messages, ack body still elsewhere, resolved value, usable editor, PUT payload and read-back passed.");
} finally {
  await browser?.close();
  server.close();
}
