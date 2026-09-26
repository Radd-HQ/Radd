/**
 * Browser proof for RADD-1390 against the REAL backend: no host list decides where a plugin's
 * settings live or which icon its nav entry shows.
 *
 *   1. Settings → General renders exactly the instance rows no plugin homes (`homed` = false);
 *   2. every contributed settings-nav entry draws the icon its manifest names (a lucide class
 *      derived from the kebab-case name), not the fallback — Automations' Zap included;
 *   3. no console errors.
 *
 * Usage: node scripts/settings-surfaces-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

async function waitFor(session, expression, attempts = 60) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.eval(expression);
    if (value) return value;
    await sleep(200);
  }
  return session.eval(expression);
}

const { session, close } = await openBrowser({ port: 9490, profile: resolve(process.env.TMPDIR || "/tmp", "radd-settings-surfaces-proof") });
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, String(status));

  const rows = await session.eval(`fetch("/api/v1/scoped-settings?scope=instance").then((r) => r.json())`);
  const unhomed = rows.filter((r) => !r.homed).map((r) => r.label || r.key);
  check("some instance rows are homed by their plugins, some are left for General",
    rows.some((r) => r.homed) && unhomed.length > 0, `${rows.length} rows, ${unhomed.length} unhomed`);

  await session.navigate(`${baseUrl}/settings/general`, 300);
  await waitFor(session, `document.body.innerText.includes(${JSON.stringify(unhomed[0])}) && document.querySelectorAll('nav[aria-label="Settings sections"] a').length > 10`);
  const text = await session.eval(`document.querySelector("main")?.innerText ?? document.body.innerText`);
  check("General shows every unhomed row", unhomed.every((label) => text.includes(label)),
    unhomed.filter((label) => !text.includes(label)).join(", "));
  const homed = rows.filter((r) => r.homed && r.label && !unhomed.includes(r.label)).map((r) => r.label);
  check("General shows no homed row", homed.every((label) => !text.includes(label)),
    homed.filter((label) => text.includes(label)).join(", "));

  const caps = await session.eval(`fetch("/api/v1/capabilities").then((r) => r.json())`);
  const nav = caps.nav.filter((n) => n.section === "settings");
  const drawn = await session.eval(`Object.fromEntries([...document.querySelectorAll('nav[aria-label="Settings sections"] a')]
    .map((a) => [a.getAttribute("href"), a.querySelector("svg")?.getAttribute("class") ?? ""]))`);
  for (const item of nav) {
    const cls = drawn[item.path] ?? "missing";
    check(`${item.label} draws its declared icon "${item.icon}"`, cls.includes(`lucide-${item.icon}`), cls);
  }
  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
} finally {
  await close();
}
const failed = report(Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])), { proof: "settings surfaces" });
process.exit(failed ? 1 : 0);
