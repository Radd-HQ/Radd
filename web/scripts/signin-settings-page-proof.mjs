/**
 * Browser proof for RADD-1380: Settings → Sign-in is the HOST's page (it
 * carries the core auth module's MFA policy), and the SSO provider registry on
 * it is the sso plugin's remote, contributed as a section — against the REAL
 * backend.
 *
 *   1. the page renders the two-factor section, and the providers section
 *      inside the same page;
 *   2. the section's code came from /plugins/sso/ — the remote was fetched, it
 *      carries the section's copy, and the host bundle no longer does;
 *   3. the existing providers render (read-only — they are real sign-in config);
 *   4. a throwaway, DISABLED generic-OIDC provider is created through the
 *      section's dialog, appears, and is removed through the section's own
 *      delete (a disabled row never reaches anybody's login page);
 *   5. the Plugins page links sso to Sign-in with no plugin named in the host;
 *   6. signed out, /login still draws the provider buttons (they are the
 *      host's: nothing remote can load before sign-in);
 *   7. no console errors.
 *
 * Usage: node scripts/signin-settings-page-proof.mjs <baseUrl> [email] [password]
 */
import { mkdtemp } from "node:fs/promises";
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9503;
const tag = `Proof OIDC ${Date.now().toString(36)}`;

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

async function waitFor(session, expression, attempts = 40) {
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

/** Set a controlled input's value the way React notices. */
const typeInto = (selector, value) => `(() => {
  const field = document.querySelector(${JSON.stringify(selector)});
  if (!field) return false;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(field, ${JSON.stringify(value)});
  field.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`;

/** The input a visible <label> text names, inside the provider form. */
const labelled = (text) => `(() => {
  const label = [...document.querySelectorAll("[data-sso-provider-form] label")].find((l) => l.textContent.trim() === ${JSON.stringify(text)});
  return label ? (label.htmlFor ? "#" + CSS.escape(label.htmlFor) : null) : null;
})()`;

const { session, close } = await openBrowser({
  port: PORT, profile: await mkdtemp(resolve(process.env.TMPDIR || "/tmp", "radd-signin-proof-")),
});
let createdId = null;
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);
  const existing = await session.eval(`(async () => { ${API} return (await api("GET", "/sso/providers")).body; })()`);
  check("the registry answers (sso is enabled here)", Array.isArray(existing), JSON.stringify(existing)?.slice(0, 200));

  // 1. one page, both sections.
  await session.navigate(`${baseUrl}/settings/sign-in`, 1500);
  const page = await waitFor(session, `(() => {
    const mfa = document.querySelector("[data-mfa-policy]");
    const providers = document.querySelector("[data-sso-providers]");
    if (!mfa || !providers) return null;
    const heading = [...document.querySelectorAll("h2")].find((h) => h.textContent.trim() === "Sign-in");
    return { mfa: mfa.textContent, providers: providers.textContent,
      sameColumn: mfa.parentElement === providers.parentElement,
      providersFirst: Boolean(providers.compareDocumentPosition(mfa) & Node.DOCUMENT_POSITION_FOLLOWING),
      title: Boolean(heading) };
  })()`);
  check("the two-factor section renders", page?.mfa?.includes("Two-factor authentication") && page.mfa.includes("Require two-factor authentication"),
    JSON.stringify(page?.mfa?.slice(0, 160)));
  check("the providers section renders inside the Sign-in page, above two-factor",
    page?.title && page.sameColumn && page.providersFirst && page.providers.includes("Providers") && page.providers.includes("joins that account"),
    JSON.stringify(page && { title: page.title, sameColumn: page.sameColumn, providersFirst: page.providersFirst }));

  // 2. the section is the remote's.
  // Every host chunk this page actually loaded — the route is lazy, so the entry
  // script alone would say nothing about where the old panel lived.
  const origin = await session.eval(`(async () => {
    const loaded = performance.getEntriesByType("resource").map((e) => e.name);
    const remote = loaded.find((n) => new URL(n).pathname.startsWith("/plugins/sso/"));
    if (!remote) return { remote: null, entries: loaded.length };
    const code = await (await fetch(remote)).text();
    const host = loaded.filter((n) => { const p = new URL(n).pathname; return p.startsWith("/assets/") && p.endsWith(".js"); });
    const hostCode = (await Promise.all(host.map(async (s) => (await fetch(s)).text()))).join("");
    return { remote: new URL(remote).pathname, remoteCarries: code.includes("New sign-in provider"),
      hostChunks: host.length, signInChunk: hostCode.includes("what a password sign-in must also prove"),
      hostCarries: hostCode.includes("New sign-in provider"), entries: loaded.length };
  })()`);
  check("the section was loaded from /plugins/sso/ and no host chunk carries it",
    origin.remote?.startsWith("/plugins/sso/remoteEntry.js") && origin.remoteCarries && origin.signInChunk
      && !origin.hostCarries && origin.entries < 250,
    JSON.stringify(origin));

  // 3. the real providers, read-only.
  const rows = await session.eval(`[...document.querySelectorAll("[data-sso-provider]")].map((r) => r.getAttribute("data-sso-provider"))`);
  check("every existing provider renders as a row", existing.length > 0 && existing.every((p) => rows.includes(p.name)),
    JSON.stringify({ api: existing.map((p) => p.name), rows }));
  await session.screenshot(resolve("scripts", "signin-settings-page-proof.png"), { fullPage: true });

  // 4. create a disabled throwaway OIDC provider through the dialog, then remove it.
  await session.click("[data-sso-providers] button", (text) => text.trim() === "New provider");
  await waitFor(session, `Boolean(document.querySelector("[data-sso-provider-form]"))`);
  const providerSelect = await session.eval(labelled("Provider"));
  // The kinds catalog loads after the dialog opens; its options are the select's.
  await waitFor(session, `(async () => { ${API} return ((await api("GET", "/sso/kinds")).body ?? []).length > 0; })()`);
  await sleep(300);
  await session.click(providerSelect);
  await waitFor(session, `[...document.querySelectorAll('[role="option"]')].some((o) => o.textContent.includes("other OIDC issuer"))`);
  await session.click('[role="option"]', (text) => text.includes("other OIDC issuer"));
  const issuerField = await waitFor(session, labelled("Issuer URL"));
  await session.eval(typeInto(issuerField, "https://sso-proof.invalid"));
  await session.eval(typeInto(await session.eval(labelled("Button label")), tag));
  await session.eval(typeInto(await session.eval(labelled("Client ID")), "proof-client"));
  await session.eval(typeInto(await session.eval(labelled("Client secret")), "proof-secret"));
  // Off BEFORE it is created: a disabled row never appears on a login page.
  await session.eval(`(() => {
    const box = [...document.querySelectorAll("[data-sso-provider-form] label")].find((l) => l.textContent.trim() === "Enabled")?.querySelector("input");
    if (box?.checked) box.click();
    return box ? !box.checked : false;
  })()`);
  await session.click("[data-sso-provider-form] button", (text) => text.trim() === "Create provider");
  const created = await waitFor(session, `(async () => { ${API}
    const mine = ((await api("GET", "/sso/providers")).body ?? []).find((p) => p.name === ${JSON.stringify(tag)});
    return mine && !document.querySelector("[data-sso-provider-form]") && document.querySelector('[data-sso-provider="${tag}"]')
      ? { id: mine.id, kind: mine.kind, enabled: mine.enabled, issuer: mine.issuer } : null;
  })()`);
  createdId = created?.id ?? null;
  check("a disabled OIDC provider is created through the section's dialog and listed",
    created?.kind === "oidc" && created.enabled === false && created.issuer === "https://sso-proof.invalid", JSON.stringify(created));
  const chip = await session.eval(`document.querySelector('[data-sso-provider="${tag}"]')?.textContent ?? ""`);
  check("its row reads Disabled", chip.includes("Disabled"), chip);

  await session.click(`[aria-label="Remove ${tag}"]`);
  await waitFor(session, `[...document.querySelectorAll('[role="dialog"] button')].some((b) => b.textContent.trim() === "Remove")`);
  await session.click('[role="dialog"] button', (text) => text.trim() === "Remove");
  const gone = await waitFor(session, `(async () => { ${API}
    const still = ((await api("GET", "/sso/providers")).body ?? []).some((p) => p.name === ${JSON.stringify(tag)});
    return !still && !document.querySelector('[data-sso-provider="${tag}"]');
  })()`);
  if (gone) createdId = null;
  check("the section's own delete removes it", gone);

  // 5. Plugins → sso links to the host page it adds a section to.
  await session.navigate(`${baseUrl}/settings/plugins`, 1500);
  const link = await waitFor(session, `(() => {
    const row = [...document.querySelectorAll("li")].find((li) => [...li.querySelectorAll("span")].some((s) => s.textContent.trim() === "sso"));
    const a = row && [...row.querySelectorAll("a")].find((x) => x.getAttribute("href") === "/settings/sign-in");
    return a ? a.textContent.trim() : null;
  })()`);
  check("the Plugins page links sso to Sign-in", link === "Sign-in", String(link));

  // 5b. sso withdrawn, IN THIS BROWSER ONLY: the manifest the SPA reads loses sso
  // (its remote, its plugin entry), exactly as a disabled plugin's would. The
  // shared database is untouched — nothing here enables or disables a plugin.
  const { identifier } = await session.send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
    const real = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const response = await real(input, init);
      // The host's api hands fetch a URL object; a Request carries .url.
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname !== "/api/v1/capabilities" || !response.ok) return response;
      const body = await response.clone().json();
      body.plugins = body.plugins.filter((name) => name !== "sso");
      body.remotes = body.remotes.filter((remote) => remote.name !== "sso");
      body.nav = body.nav.filter((item) => item.plugin !== "sso");
      return new Response(JSON.stringify(body), { status: response.status, headers: response.headers });
    };
  })()` });
  await session.navigate(`${baseUrl}/settings/sign-in`, 1500);
  const withdrawn = await waitFor(session, `(() => {
    const mfa = document.querySelector("[data-mfa-policy]");
    if (!mfa || !mfa.textContent.includes("Require two-factor authentication")) return null;
    return { providers: Boolean(document.querySelector("[data-sso-providers]")),
      tab: [...document.querySelectorAll('nav[aria-label="Settings sections"] a')].some((a) => a.textContent.trim() === "Sign-in"),
      remote: performance.getEntriesByType("resource").some((e) => new URL(e.name).pathname.startsWith("/plugins/sso/")) };
  })()`);
  await sleep(1000); // a late remote would have registered by now
  const settledWithdrawn = withdrawn && await session.eval(`Boolean(document.querySelector("[data-sso-providers]"))`);
  check("without sso the page, its nav tab and the two-factor policy stay; the providers section does not",
    withdrawn && withdrawn.tab && !withdrawn.providers && !withdrawn.remote && !settledWithdrawn, JSON.stringify(withdrawn));
  await session.send("Page.removeScriptToEvaluateOnNewDocument", { identifier });

  // 6. signed out, the login page still draws the provider buttons.
  const enabledNames = existing.filter((p) => p.enabled && p.configured).map((p) => p.name);
  await session.eval(`fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" }).then((r) => r.status)`);
  await session.navigate(`${baseUrl}/login`, 1500);
  const buttons = await waitFor(session, `(() => {
    const anchors = [...document.querySelectorAll("a")].filter((a) => a.textContent.trim().startsWith("Sign in with "));
    return anchors.length ? anchors.map((a) => a.textContent.trim()) : null;
  })()`);
  check("signed out, /login shows a button per enabled provider",
    enabledNames.length > 0 && enabledNames.every((n) => buttons?.includes(`Sign in with ${n}`)),
    JSON.stringify({ enabledNames, buttons }));
  const remoteOnLogin = await session.eval(`performance.getEntriesByType("resource").some((e) => new URL(e.name).pathname.startsWith("/plugins/sso/"))`);
  check("…without the sso remote (it cannot load before sign-in)", remoteOnLogin === false);
} catch (error) {
  check("the proof ran to the end", false, error.message);
} finally {
  if (createdId) {
    // Only reached when the UI delete failed: log back in and remove the row directly.
    await session.login(baseUrl, email, password);
    const status = await session.eval(`fetch("/api/v1/sso/providers/${createdId}", { method: "DELETE" }).then((r) => r.status)`);
    check("fallback cleanup removed the throwaway provider", status === 204, String(status));
  }
  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors));
  await close();
}
const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "sign-in settings page (RADD-1380)" },
);
process.exit(failed ? 1 : 0);
