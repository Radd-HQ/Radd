/**
 * Browser proof for RADD-1381: Settings → Directory is the ldap plugin's own
 * remote, against the REAL backend (and whatever directory it is bound to).
 *
 *   1. the settings nav carries Directory once, under Server, from the plugin's
 *      manifest; the page's code is /plugins/ldap/remoteEntry.js;
 *   2. every section renders: status, the three tabs' settings, the sync
 *      last-run lines, the live group browse, the mirrored groups and a
 *      group's role grants;
 *   3. the AD user import dialog opens, searches the directory and closes —
 *      nothing is selected, nothing is imported;
 *   4. one reversible settings edit (the group sync interval) saves from the
 *      page and is put back exactly as it was (reset, or the old value);
 *   5. no console errors on the way.
 *
 * It never enables/disables a plugin, never runs a sync, never imports.
 *
 * Usage: node scripts/directory-settings-page-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9504;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-directory-proof-profile");
const SETTING = "ldap_group_sync_seconds";

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

async function waitFor(session, expression, attempts = 60) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.eval(expression);
    if (value) return value;
    await sleep(250);
  }
  return session.eval(expression);
}

const API = `const api = async (method, path, body) => { const r = await fetch("/api/v1" + path, { method,
  headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text(); return { status: r.status, body: text ? JSON.parse(text) : null }; };`;
const readSetting = `(async () => { ${API}
  const rows = (await api("GET", "/scoped-settings?scope=instance")).body;
  const row = rows.find((r) => r.key === ${JSON.stringify(SETTING)});
  return row ? { value: String(row.value), set_here: row.set_here } : null;
})()`;
/** Type into a controlled input the way React hears it, then blur (the row autosaves on blur). */
const typeInto = (selector, value) => `(() => {
  const field = document.querySelector(${JSON.stringify(selector)});
  if (!field) return false;
  field.focus();
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(field, ${JSON.stringify(value)});
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.blur();
  return true;
})()`;

const { session, close } = await openBrowser({ port: PORT, profile: PROFILE });
let original = null;
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);
  check("hover-capable browser (Tailwind gates hover: on it)", await session.hoverCapable());
  original = await session.eval(readSetting);
  check("the setting to edit exists", original, JSON.stringify(original));

  // 1. nav + provenance.
  await session.navigate(`${baseUrl}/settings/directory`, 2500);
  check("the page mounts", await waitFor(session, `Boolean(document.querySelector("[data-directory-page]"))`));
  const nav = await session.eval(`(() => {
    const links = [...document.querySelectorAll('nav[aria-label="Settings sections"] a')];
    const mine = links.filter((a) => a.textContent.trim() === "Directory");
    const server = [...document.querySelectorAll('nav[aria-label="Settings sections"] section')]
      .find((s) => s.getAttribute("aria-label") === "Server");
    const order = server ? [...server.querySelectorAll("a")].map((a) => a.textContent.trim()) : [];
    return { count: mine.length, href: mine[0]?.getAttribute("href"), inServer: Boolean(server && mine[0] && server.contains(mine[0])),
      order, active: mine[0]?.classList.contains("active") };
  })()`);
  check("the nav carries Directory once, under Server", nav.count === 1 && nav.inServer && nav.href === "/settings/directory", JSON.stringify(nav));
  check("…between Email and Sign-in, and active", nav.order.indexOf("Email") < nav.order.indexOf("Directory")
    && nav.order.indexOf("Directory") < nav.order.indexOf("Sign-in") && nav.active, JSON.stringify(nav.order));
  const provenance = await session.eval(`(async () => { ${API}
    const caps = (await api("GET", "/capabilities")).body;
    const resources = performance.getEntriesByType("resource").map((e) => e.name);
    return { remote: caps.remotes.find((r) => r.name === "ldap")?.remote_entry ?? null,
      nav: caps.nav.filter((n) => n.plugin === "ldap").map((n) => n.path),
      loaded: resources.some((n) => n.includes("/plugins/ldap/remoteEntry.js")),
      hostChunk: resources.filter((n) => /\\/assets\\/directory-[^/]*\\.js/.test(n)) };
  })()`);
  check("the page comes from /plugins/ldap/", provenance.loaded && provenance.remote?.startsWith("/plugins/ldap/remoteEntry.js"), JSON.stringify(provenance));
  check("the nav entry is the plugin's manifest", provenance.nav.join() === "/settings/directory", JSON.stringify(provenance.nav));
  check("no host directory chunk loaded", provenance.hostChunk.length === 0, JSON.stringify(provenance.hostChunk));

  // 2. every section.
  const statusRows = await waitFor(session, `(() => { const rows = [...document.querySelectorAll("[data-directory-status]")];
    return rows.length === 3 ? rows.map((r) => r.textContent.trim()) : null; })()`);
  check("the status section shows sign-in, bind account and workers", statusRows, JSON.stringify(statusRows));
  const connection = await waitFor(session, `(() => {
    const keys = [...document.querySelectorAll("[data-setting]")].map((e) => e.dataset.setting);
    return keys.includes("ldap_url") ? { keys, secret: document.querySelector('[data-setting="ldap_bind_password"] input')?.type } : null; })()`);
  check("Connection tab: the five connection settings, password masked",
    connection && ["ldap_url", "ldap_user_domain", "ldap_bind_dn", "ldap_bind_password", "ldap_admin_groups"].every((k) => connection.keys.includes(k))
      && connection.secret === "password", JSON.stringify(connection));

  await session.click('[data-directory-tab="users"]');
  const users = await waitFor(session, `(() => {
    const keys = [...document.querySelectorAll("[data-setting]")].map((e) => e.dataset.setting);
    const line = document.querySelector("[data-user-sync-last-run]")?.textContent ?? "";
    return keys.includes("ldap_user_sync_enabled") && /^(Last run|Never ran)/.test(line) ? { keys, line } : null; })()`);
  check("User sync tab: its four settings and the last-run line",
    users && ["ldap_user_sync_base", "ldap_user_sync_enabled", "ldap_user_sync_deactivate_missing", "ldap_exclude_disabled"].every((k) => users.keys.includes(k)),
    JSON.stringify(users));

  // 3. the import dialog: open, search, close.
  await session.click("button", (text) => text.trim() === "Import users…");
  check("the import dialog opens", await waitFor(session, `Boolean(document.querySelector('[role="dialog"] [data-import-users]'))`));
  await session.eval(`(() => { const f = document.querySelector('[data-import-users] input:not([type="checkbox"])');
    f.focus(); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(f, "a");
    f.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const searched = await waitFor(session, `(() => { const root = document.querySelector("[data-import-users]");
    const rows = root?.querySelectorAll("[data-directory-user-results] li").length ?? 0;
    const text = root?.textContent ?? "";
    return rows > 0 || text.includes("No directory users match.") ? { rows, checked: root.querySelectorAll("input:checked").length } : null; })()`, 120);
  check("the dialog searches the live directory (nothing selected)", searched && searched.checked === 0, JSON.stringify(searched));
  await session.click('[role="dialog"] button', (text) => text.trim() === "Close");
  check("the import dialog closes", await waitFor(session, `!document.querySelector("[data-import-users]")`));

  await session.click('[data-directory-tab="groups"]');
  const groups = await waitFor(session, `(() => {
    const keys = [...document.querySelectorAll("[data-setting]")].map((e) => e.dataset.setting);
    const browse = document.querySelectorAll("[data-directory-group]").length;
    const empty = document.querySelector("[data-directory-groups]")?.textContent.includes("No directory groups match.");
    const line = document.querySelector("[data-group-sync-last-run]")?.textContent ?? "";
    return keys.includes(${JSON.stringify(SETTING)}) && (browse > 0 || empty) && line.startsWith("Linked-team reconcile")
      ? { keys, browse, line } : null; })()`, 120);
  check("Groups tab: its settings, the live group browse and the reconcile line",
    groups && groups.keys.includes("ldap_group_search_base"), JSON.stringify(groups));
  const mirrored = await waitFor(session, `(() => { const rows = document.querySelectorAll("[data-mirrored-group]").length;
    return rows > 0 || document.querySelector("[data-mirrored-groups]")?.textContent.includes("Nothing mirrored yet") ? { rows } : null; })()`);
  check("the mirrored-groups table renders", mirrored && mirrored.rows > 0, JSON.stringify(mirrored));
  if (mirrored?.rows > 0) {
    await session.click("[data-mirrored-group] button[aria-expanded]");
    const grants = await waitFor(session, `(() => { const s = document.querySelector('[data-mirrored-group-roles] section[aria-label="Role grants"]');
      if (!s) return null; const t = s.textContent;
      return t.includes("Loading") ? null : { grants: s.querySelectorAll("li[data-grant-id]").length,
        none: t.includes("No role grants."), grantButton: [...s.querySelectorAll("button")].some((b) => b.textContent.includes("Grant role")) }; })()`);
    check("a mirrored group expands to its role grants (manageable)", grants && (grants.grants > 0 || grants.none) && grants.grantButton, JSON.stringify(grants));
  }
  await session.screenshot(resolve(TMP, "directory-settings-page-proof.png"), { fullPage: true });

  // 4. one reversible settings edit, from the page.
  const row = `[data-setting="${SETTING}"]`;
  const next = String(Number(original.value) + 1);
  await session.eval(typeInto(`${row} input`, next));
  const saved = await waitFor(session, `(async () => { const s = await ${readSetting}; return s.value === ${JSON.stringify(next)} && s.set_here ? s : null; })()`);
  check("an edit on the page saves the override", saved, JSON.stringify(saved));
  check("the row says it is set here", await waitFor(session, `document.querySelector('${row}')?.textContent.includes("Set here")`));
  if (original.set_here) await session.eval(typeInto(`${row} input`, original.value));
  else await session.click(`${row} button`, (text) => text.trim() === "Reset");
  const restored = await waitFor(session, `(async () => { const s = await ${readSetting};
    return s.value === ${JSON.stringify(original.value)} && s.set_here === ${original.set_here} ? s : null; })()`);
  check(`…and is put back from the page (${original.set_here ? "old value" : "Reset"})`, restored, JSON.stringify(restored));
  check("the page follows the restored value", await waitFor(session,
    `document.querySelector('${row} input')?.value === ${JSON.stringify(original.value)}`));

  // 5. console.
  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors.slice(0, 5)));
} finally {
  // Whatever happened above, leave the setting exactly as it was found.
  if (original) {
    const now = await session.eval(readSetting).catch(() => null);
    if (!now || now.value !== original.value || now.set_here !== original.set_here) {
      const put = await session.eval(`(async () => { ${API}
        return ${original.set_here}
          ? (await api("PUT", "/scoped-settings", { scope: "instance", key: ${JSON.stringify(SETTING)}, value: ${JSON.stringify(original.value)} })).status
          : (await api("DELETE", "/scoped-settings?scope=instance&key=${SETTING}")).status; })()`).catch(String);
      check("cleanup restored the setting", put === 200 || put === 204, String(put));
    }
  }
  await close();
}
const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "directory settings page (RADD-1381)", baseUrl, setting: SETTING, original },
);
process.exit(failed ? 1 : 0);
