/** RADD-1529: the Profile password panel, on the built SPA against synthetic HTTP fixtures.
 *
 *   1. an account whose password Radd holds sees the panel; one that signs in through a
 *      provider does not (it is not offered a form the server would refuse);
 *   2. the three fields are real password inputs with the browser's autocomplete hints, laid
 *      out one under another at a usable size, in both themes;
 *   3. a mismatch is caught before anything is sent;
 *   4. a wrong current password (401) is said inline and does NOT bounce to /login;
 *   5. a good change sends exactly {current_password, new_password}, clears the form and
 *      says how many other sessions ended.
 */
import assert from "node:assert/strict";
import {mkdtemp} from "node:fs/promises";
import {openBrowser, until} from "./lib/cdp.mjs";
import {CORE_PLUGINS} from "./lib/core-plugins.mjs";
import {serveBuiltSpa} from "./lib/spa-server.mjs";

let local = true, answer = 200;
const posts = [];
const user = () => ({id: "u1", name: "Pat Local", email: "pat@example.test", instance_role: "member", global_role: "member",
  permissions: [], timezone: "UTC", has_local_password: local});
const spa = await serveBuiltSpa(async (req, res, url) => {
  if (url.pathname.startsWith("/plugins/")) {res.writeHead(404); res.end(); return true;}
  if (!url.pathname.startsWith("/api/")) return false;
  const route = url.pathname.replace("/api/v1", "");
  let raw = ""; for await (const chunk of req) raw += chunk;
  if (route === "/auth/password" && req.method === "POST") {
    posts.push(JSON.parse(raw));
    res.writeHead(answer, {"content-type": "application/json"});
    res.end(JSON.stringify(answer === 200 ? {sessions_ended: 2} : {detail: "the current password is not correct"}));
    return true;
  }
  let data = [];
  if (route === "/auth/me") data = user();
  else if (route.includes("capabilities")) data = {capabilities: [], nav: [], ui: [], plugins: CORE_PLUGINS, remotes: []};
  else if (route === "/auth/me/preferences") data = {};
  else if (route === "/auth/totp") data = {enabled: false, pending: false};
  else if (route === "/projects/summary") data = {total: 0, related_count: 0, permissions: []};
  else if (route === "/page-spaces/summary") data = {total: 0, permissions: []};
  else if (route.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
  else if (route === "/instance") data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
  res.writeHead(200, {"content-type": "application/json", "X-Total-Count": "0"});
  res.end(JSON.stringify(data)); return true;
});

const checks = [];
let browser;
try {
  browser = await openBrowser({port: 18871, profile: await mkdtemp("/tmp/radd-password-"), scale: 1});
  const s = browser.session;
  const PANEL = "[data-password-panel]";
  const field = (label) => `(() => [...document.querySelectorAll('${PANEL} label')].find((l) => l.textContent.trim() === ${JSON.stringify(label)})?.control)()`;
  const type = async (label, text) => {
    await s.eval(`${field(label)}.focus(), ${field(label)}.select()`);
    await s.send("Input.insertText", {text});
  };
  const errorText = () => s.eval(`[...document.querySelectorAll('${PANEL} [id$="-hint"], ${PANEL} [role="alert"], ${PANEL} p')].map((n) => n.textContent.trim()).join(" | ")`);

  // 1. A provider account is not offered the form.
  local = false;
  await s.navigate(`${spa.origin}/settings/profile`);
  await until(s, `document.body.innerText.includes("Two-factor authentication")`, "profile page");
  assert.equal(await s.eval(`!!document.querySelector('${PANEL}')`), false, "a provider account was offered a password form");
  checks.push("a provider account sees no password form");

  local = true;
  await s.navigate(`${spa.origin}/settings/profile`);
  await until(s, `!!document.querySelector('${PANEL}')`, "password panel");
  checks.push("a local account sees the panel");

  // 2. Real password inputs, stacked, usable — measured, in both themes.
  const measure = () => s.eval(`[...document.querySelectorAll('${PANEL} input')].map((i) => { const r = i.getBoundingClientRect(); const c = getComputedStyle(i);
    return {type: i.type, auto: i.autocomplete, w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), font: c.fontSize, color: c.color, bg: c.backgroundColor}; })`);
  for (const theme of ["dark", "light"]) {
    await s.eval(`document.documentElement.classList.toggle("light", ${theme === "light"})`);
    const inputs = await measure();
    assert.equal(inputs.length, 3);
    assert.deepEqual(inputs.map((i) => i.type), ["password", "password", "password"]);
    assert.deepEqual(inputs.map((i) => i.auto), ["current-password", "new-password", "new-password"]);
    for (const input of inputs) {
      assert.ok(input.w >= 240 && input.h >= 28, `a ${input.w}x${input.h} input in ${theme}`);
      assert.notEqual(input.color, input.bg, `text the colour of its field in ${theme}`);
    }
    assert.ok(inputs[0].top < inputs[1].top && inputs[1].top < inputs[2].top, "the fields are not stacked");
    await s.eval(`document.querySelector('${PANEL}').scrollIntoView({block: "center"})`);
    await s.screenshot(`/tmp/radd-password-${theme}.png`);
  }
  await s.eval(`document.documentElement.classList.remove("light")`);
  checks.push("three password inputs with autocomplete hints, stacked and at a usable size in both themes");

  const submit = () => s.click(`${PANEL} button[type="submit"]`);

  // 3. A mismatch never leaves the browser.
  await type("Current password", "the old one");
  await type("New password", "a brand new phrase");
  await type("New password, again", "a different phrase");
  await submit();
  await until(s, async () => (await errorText()).includes("do not match"), "mismatch message");
  assert.equal(posts.length, 0, "a mismatched password was sent");
  checks.push("a mismatch is caught before anything is sent");

  // 4. A wrong current password is said inline; the page stays put.
  answer = 401;
  await type("New password, again", "a brand new phrase");
  await submit();
  await until(s, async () => (await errorText()).includes("not your current password"), "wrong-current message");
  assert.equal(await s.eval(`location.pathname`), "/settings/profile", "a wrong current password bounced to /login");
  assert.equal(posts.length, 1);
  checks.push("a wrong current password is said inline and does not bounce to /login");

  // 5. A good change: the exact body, a cleared form, and the count of sessions ended.
  answer = 200;
  await submit();
  await until(s, `document.body.innerText.includes("Password changed.")`, "success toast");
  assert.deepEqual(posts.at(-1), {current_password: "the old one", new_password: "a brand new phrase"});
  assert.ok(await s.eval(`document.body.innerText.includes("2 other sessions of yours signed out")`));
  assert.deepEqual(await s.eval(`[...document.querySelectorAll('${PANEL} input')].map((i) => i.value)`), ["", "", ""]);
  checks.push("a good change sends exactly the two passwords, clears the form and reports the sessions ended");

  assert.deepEqual(s.consoleErrors.filter((e) => !/401/.test(e)), [], "console errors");
  console.log(JSON.stringify({passed: true, checks, screenshots: ["/tmp/radd-password-dark.png", "/tmp/radd-password-light.png"]}));
} finally {
  await browser?.close();
  await spa.close();
}
