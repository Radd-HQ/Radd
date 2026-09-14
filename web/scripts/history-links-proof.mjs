/**
 * Browser proof for "change history where you are" (spec 123, RADD-1171).
 *
 *   1. renames a team through the API (a `team.updated` with Name: old → new);
 *   2. opens Settings → Teams, finds the team, opens its panel, expands the
 *      Change history card and asserts the rename is there;
 *   3. asserts the footer link on Settings → Roles deep-links the audit log
 *      to roles, and that following it lands on the page with Role selected;
 *   4. asserts a project's settings page links the PROJECT's trail.
 *
 * Usage: node scripts/history-links-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://localhost:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9472;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-history-links-proof-profile");
const tag = `hist-proof-${Date.now().toString(36)}`;

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

async function waitFor(session, expression, attempts = 24) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.eval(expression);
    if (value) return value;
    await sleep(250);
  }
  return session.eval(expression);
}

const { session, close } = await openBrowser({ port: PORT, profile: PROFILE });
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);

  // 1. a team, renamed.
  const team = await session.eval(`(async () => {
    const post = await fetch("/api/v1/teams", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: ${JSON.stringify(tag)} }) });
    if (!post.ok) return { error: "create " + post.status };
    const team = await post.json();
    const patch = await fetch("/api/v1/teams/" + team.id, { method: "PATCH", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: ${JSON.stringify(tag + "-renamed")} }) });
    return { ok: patch.ok, status: patch.status, id: team.id };
  })()`);
  check("team renamed through the API", team.ok, JSON.stringify(team));

  // 2. its panel carries the history.
  await session.navigate(`${baseUrl}/settings/teams`, 1500);
  // Type into React's controlled search box through the native setter, so
  // its onChange fires the way a keystroke would.
  await session.eval(`(() => {
    const input = document.querySelector('input[placeholder="Search teams by name…"]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, ${JSON.stringify(tag)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);
  const opened = await waitFor(session, `(() => {
    const button = document.querySelector('button[aria-label="Open ${tag}-renamed"]');
    if (!button) return false; button.click(); return true;
  })()`);
  check("the renamed team is listed and opens", opened, "");
  const expanded = await waitFor(session, `(() => {
    const heading = [...document.querySelectorAll("button[aria-expanded]")].find((b) => /change history/i.test(b.textContent));
    if (!heading) return false;
    if (heading.getAttribute("aria-expanded") !== "true") heading.click();
    return heading.textContent.trim();
  })()`);
  check("the team panel carries a Change history card with a count", /change history\s*\d+/i.test(String(expanded)), String(expanded));
  const rowText = await waitFor(session, `(() => {
    const list = document.querySelector("[data-change-history]");
    return list ? list.textContent : "";
  })()`);
  check("the history shows the rename as Name: old → new", /team updated/i.test(rowText) && rowText.includes("Name:") && rowText.includes(`${tag}-renamed`), String(rowText).slice(0, 200));
  await session.screenshot(resolve("scripts", "history-links-proof-team.png"));

  // 3. the footer link on a settings page, and where it goes.
  await session.navigate(`${baseUrl}/settings/roles`, 1500);
  const rolesHref = await waitFor(session, `document.querySelector("[data-settings-history] a")?.getAttribute("href") ?? ""`);
  check("Settings → Roles carries a Change history footer link", /\/settings\/audit\?/.test(rolesHref) && /entity=role/.test(rolesHref), String(rolesHref));
  await session.click("[data-settings-history] a");
  await sleep(1500);
  const landed = await waitFor(session, `(() => {
    const filters = document.querySelector("[data-audit-filters]");
    return location.pathname === "/settings/audit" && filters && /Role/.test(filters.textContent) ? location.href : "";
  })()`);
  check("following it lands on the audit log with Role selected", Boolean(landed), String(landed));
  const roleRows = await waitFor(session, `document.querySelectorAll("[data-audit-row]").length`);
  check("the deep-linked view lists role rows only", roleRows > 0 && await session.eval(`[...document.querySelectorAll("[data-audit-row]")].every((tr) => tr.dataset.auditEvent.startsWith("role."))`), String(roleRows));

  // 4. a project's settings page links the project's trail.
  const project = await session.eval(`(async () => { const r = await fetch("/api/v1/projects?limit=1"); const rows = await r.json(); const p = Array.isArray(rows) ? rows[0] : (rows.items ?? rows.rows ?? [])[0]; return p ? { id: p.id, key: p.key } : null; })()`);
  check("a project exists to test with", Boolean(project), JSON.stringify(project));
  if (project) {
    await session.navigate(`${baseUrl}/p/${project.key}/settings/workflow`, 1500);
    const href = await waitFor(session, `document.querySelector("[data-settings-history] a")?.getAttribute("href") ?? ""`);
    check("a project settings page links the project's trail", href.includes(`project=${project.id}`) && /entity=state/.test(href), String(href));
  }
  await session.screenshot(resolve("scripts", "history-links-proof-page.png"), { fullPage: true });
} finally {
  await close();
}

const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "history-links-proof", tag },
);
process.exit(failed ? 1 : 0);
