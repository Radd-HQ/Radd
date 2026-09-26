/**
 * Browser proof for RADD-1389 against the REAL backend: Settings → Server status lists what the
 * loaded plugins report, instead of a schema that named SSO, LDAP, SMTP and AI.
 *
 *   1. every non-connector capability from /capabilities is a row with its own label and state;
 *   2. Outbound email follows the sender rows (compared against /mail/senders);
 *   3. each row links to its owning plugin's page (AI, Email, Directory, Storage);
 *   4. /instance/status is gone; the Directory page still shows its bind-account state;
 *   5. no console errors.
 *
 * Usage: node scripts/server-status-proof.mjs <baseUrl> [email] [password]
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

const { session, close } = await openBrowser({ port: 9489, profile: resolve(process.env.TMPDIR || "/tmp", "radd-server-status-proof") });
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, String(status));

  const caps = await session.eval(`fetch("/api/v1/capabilities").then((r) => r.json())`);
  const expected = caps.capabilities.filter((c) => c.category !== "connector");
  const senders = await session.eval(`fetch("/api/v1/mail/senders").then((r) => r.json())`);
  const old = await session.eval(`fetch("/api/v1/instance/status").then((r) => r.status)`);
  check("the typed /instance/status endpoint is gone", old === 404, String(old));
  check("every capability names its owning plugin", caps.capabilities.every((c) => c.plugin),
    caps.capabilities.filter((c) => !c.plugin).map((c) => c.key).join(","));
  const outbound = caps.capabilities.find((c) => c.key === "outbound_mail");
  check("outbound email is mailintake's capability", outbound?.plugin === "mailintake", JSON.stringify(outbound));
  check("outbound email follows the enabled sender rows",
    outbound?.enabled === senders.some((s) => s.enabled), `${outbound?.enabled} vs ${senders.length} sender(s)`);

  await session.navigate(`${baseUrl}/settings/instance`, 300);
  await waitFor(session, `document.body.innerText.includes("Deploy status") && !document.body.innerText.includes("Loading status")`);
  const rows = await session.eval(`[...document.querySelectorAll("[data-status-row]")].map((el) => ({
    label: el.dataset.statusRow, text: el.textContent, href: el.getAttribute("href") }))`);
  for (const cap of expected) {
    const row = rows.find((r) => r.label === cap.label);
    const summary = typeof cap.detail?.summary === "string" ? cap.detail.summary : "";
    check(`row "${cap.label}" shows ${cap.enabled ? "On" : "Off"}${summary ? ` and "${summary}"` : ""}`,
      row && row.text.includes(cap.enabled ? "On" : "Off") && row.text.includes(summary), row ? row.text : "missing");
  }
  const linkOf = (label) => rows.find((r) => r.label === label)?.href;
  const byKey = (key) => expected.find((c) => c.key === key)?.label;
  check("AI links to the ai plugin's page", linkOf(byKey("ai")) === "/settings/ai", linkOf(byKey("ai")));
  check("Outbound email links to Settings → Email", linkOf(byKey("outbound_mail")) === "/settings/email", linkOf(byKey("outbound_mail")));
  check("the directory links to Settings → Directory", linkOf(byKey("ldap")) === "/settings/directory", linkOf(byKey("ldap")));
  check("storage links to Settings → Storage", linkOf(byKey("storage")) === "/settings/storage", linkOf(byKey("storage")));
  const connectors = caps.capabilities.filter((c) => c.category === "connector");
  check("connectors fold into one row linking to Plugins",
    rows.some((r) => r.label === "Connectors" && r.href === "/settings/plugins" && r.text.includes(`of ${connectors.length} configured`)));

  const ldap = caps.capabilities.find((c) => c.key === "ldap");
  await session.navigate(`${baseUrl}/settings/directory`, 300);
  const bindRow = await waitFor(session, `[...document.querySelectorAll("[data-directory-page] section div")].find((el) => el.textContent.startsWith("Bind (service) account"))?.textContent`);
  check("the Directory page's bind-account row matches the ldap capability",
    bindRow && bindRow.includes(ldap.detail.bind_account ? "On" : "Off"), `${bindRow} vs ${ldap.detail.bind_account}`);
  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
} finally {
  await close();
}
const failed = report(Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])), { proof: "server status" });
process.exit(failed ? 1 : 0);
