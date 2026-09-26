/**
 * Smoke for RADD-1373 against a REAL backend: core plugins' UI is bundled and registered at boot.
 *
 *   1. /capabilities lists no remote for any core plugin, and the page never requests one;
 *   2. core-contributed pages render (Version control, Automations, Audit) and optional remotes
 *      still load (Alertmanager);
 *   3. an issue page's pickers render without a "Selection unavailable" flash, sampled right after
 *      the first paint;
 *   4. no console errors.
 *
 * Usage: node scripts/bundled-plugins-smoke.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";

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

const { session, close } = await openBrowser({ port: 9486, profile: resolve(process.env.TMPDIR || "/tmp", "radd-bundled-smoke") });
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, String(status));

  const caps = await session.eval(`fetch("/api/v1/capabilities").then((r) => r.json())`);
  const coreRemotes = (caps.remotes ?? []).filter((remote) => CORE_PLUGINS.includes(remote.name)).map((remote) => remote.name);
  check("no core plugin is served as a remote", coreRemotes.length === 0, coreRemotes.join(","));
  check("core plugins are loaded on the server", CORE_PLUGINS.every((name) => caps.plugins.includes(name)),
    CORE_PLUGINS.filter((name) => !caps.plugins.includes(name)).join(","));

  const pages = [
    ["/settings/vcs", "Version control"],
    ["/settings/automations", "Automations"],
    ["/settings/audit", "Audit log"],
    ["/settings/alertmanager", "Alertmanager"],
  ];
  for (const [path, heading] of pages) {
    await session.navigate(`${baseUrl}${path}`, 300);
    const found = await waitFor(session, `[...document.querySelectorAll("h1,h2")].some((h) => h.textContent.trim() === ${JSON.stringify(heading)})`);
    check(`${path} renders`, found);
  }

  const key = await session.eval(`fetch("/api/v1/items?limit=1").then((r) => r.json()).then((d) => (d.items ?? d)[0]?.key ?? null)`);
  if (key) {
    await session.navigate(`${baseUrl}/issues/${key}`, 150);
    const early = await session.eval(`document.body.innerText.includes("Selection unavailable")`);
    await waitFor(session, `Boolean(document.querySelector("h1"))`);
    const later = await session.eval(`document.body.innerText.includes("Selection unavailable")`);
    check("the issue page shows no unavailable picker, at first paint or after", !early && !later, `${key} early=${early} later=${later}`);
  }
  const remoteRequests = await session.eval(`performance.getEntriesByType("resource").map((e) => e.name).filter((n) => /\\/plugins\\/[^/]+\\/remoteEntry/.test(n))`);
  const coreFetched = remoteRequests.filter((url) => CORE_PLUGINS.some((name) => url.includes(`/plugins/${name}/`)));
  check("the browser never fetched a core plugin bundle", coreFetched.length === 0, coreFetched.join(","));
  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
} finally {
  await close();
}
const failed = report(Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])), { proof: "bundled plugins smoke" });
process.exit(failed ? 1 : 0);
