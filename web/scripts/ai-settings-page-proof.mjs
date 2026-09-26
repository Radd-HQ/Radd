/**
 * Browser proof for RADD-1379: Settings → AI is the ai plugin's own page (its UI remote), not a
 * host route — against the REAL backend.
 *
 *   1. the nav entry comes from the plugin's manifest, once, in the Server group;
 *   2. the page is rendered by /plugins/ai/remoteEntry.js: providers, roles, feature toggles
 *      (the SDK's ScopedSettings over the `ai` section) and presets all render, and match the API;
 *   3. the provider form opens (read-only: it is closed with Cancel);
 *   4. a real save round-trips: a throwaway preset is created, switched off and deleted from the
 *      page, each step confirmed through the API;
 *   5. the plugin's AI gate — the query bar's and the palette's Ask read it (RADD-1400) — carries
 *      the entity tags its settings page invalidates;
 *   6. Server status and the Plugins page link to the plugin's page.
 *
 * Nothing the instance already had is changed: providers and roles are only read.
 *
 * Usage: node scripts/ai-settings-page-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9502;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ai-settings-proof-profile");
const tag = `proof-${Date.now().toString(36)}`;

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
const presetFromApi = `(async () => { ${API} return (await api("GET", "/ai/presets")).body.find((p) => p.name === ${JSON.stringify(tag)}) ?? null; })()`;

/** Set a React-controlled input or textarea the way React sees it. */
const setValue = (selector, value) => `(() => {
  const el = document.querySelector(${JSON.stringify(selector)});
  if (!el) return false;
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(el, ${JSON.stringify(value)});
  el.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`;

const { session, close } = await openBrowser({ port: PORT, profile: PROFILE });
let created = false;
try {
  await session.navigate(`${baseUrl}/login`, 800);
  check("headless Chrome is hover-capable", await session.hoverCapable());
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);

  const truth = await session.eval(`(async () => { ${API}
    const caps = (await api("GET", "/capabilities")).body;
    return { providers: (await api("GET", "/ai/providers")).body, roles: (await api("GET", "/ai/roles")).body,
      settings: (await api("GET", "/scoped-settings?scope=instance")).body.filter((r) => r.key.startsWith("ai_")).map((r) => r.key),
      nav: caps.nav.filter((n) => n.plugin === "ai"), remote: caps.remotes.find((r) => r.name === "ai") };
  })()`);
  check("the manifest declares the page's nav entry",
    truth.nav.length === 1 && truth.nav[0].path === "/settings/ai" && truth.nav[0].group === "Server" && truth.nav[0].requires_admin,
    JSON.stringify(truth.nav));
  // At least 1.14.0, where ScopedSettings arrived; later plugin work raises it (1.16.0 since RADD-1395).
  const [major, minor] = String(truth.remote?.ui_api_version ?? "0.0").split(".").map(Number);
  check("the ai remote asks for a UI API with ScopedSettings (≥ 1.14.0)", major === 1 && minor >= 14, JSON.stringify(truth.remote));

  // 1–2. the page.
  await session.navigate(`${baseUrl}/settings/ai`, 1500);
  check("the providers section renders", await waitFor(session, `Boolean(document.querySelector("[data-ai-providers]"))`));
  const nav = await session.eval(`(() => {
    const links = [...document.querySelectorAll('section[aria-label="Server"] a')];
    const labels = links.map((a) => a.textContent.trim());
    return { count: labels.filter((l) => l === "AI").length, href: links.find((a) => a.textContent.trim() === "AI")?.getAttribute("href"),
      after: labels[labels.indexOf("AI") - 1], before: labels[labels.indexOf("AI") + 1], active: links.find((a) => a.textContent.trim() === "AI")?.getAttribute("aria-current") };
  })()`);
  check("the Server group carries AI once, where it used to sit", nav.count === 1 && nav.href === "/settings/ai"
    && nav.after === "Page spaces" && nav.before === "Storage", JSON.stringify(nav));
  const source = await session.eval(`(async () => {
    const loaded = performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/plugins/ai/"));
    const remote = loaded.find((n) => n.includes("/plugins/ai/remoteEntry.js"));
    const body = remote ? await (await fetch(remote)).text() : "";
    return { loaded, servesPage: body.includes("Extra request parameters (JSON)") && body.includes("/settings/ai") };
  })()`);
  check("the page comes from /plugins/ai/remoteEntry.js", source.loaded.length > 0 && source.servesPage, JSON.stringify(source.loaded));

  const rendered = await session.eval(`(() => ({
    providers: [...document.querySelectorAll("[data-ai-providers] tbody tr td:first-child")].map((td) => td.textContent.trim()),
    roles: [...document.querySelectorAll("[data-ai-role]")].map((tr) => tr.getAttribute("data-ai-role")),
    features: [...document.querySelectorAll("[data-ai-features] [data-setting]")].map((el) => el.getAttribute("data-setting")),
    presets: Boolean(document.querySelector('[data-ai-presets] [data-ai-preset-form="new"]')),
  }))()`);
  check("every provider the API lists is a row",
    truth.providers.length > 0 && truth.providers.every((p) => rendered.providers.some((cell) => cell.startsWith(p.name))),
    JSON.stringify({ api: truth.providers.map((p) => p.name), page: rendered.providers }));
  check("the three model roles render", rendered.roles.join() === "chat,embeddings,vision", rendered.roles.join());
  const chat = truth.roles.find((r) => r.role === "chat");
  const chatTrigger = await session.eval(`document.querySelector('[data-ai-role="chat"] [aria-label="Chat provider"]')?.textContent.trim() ?? null`);
  check("the chat role shows its assigned provider", chat ? chatTrigger?.includes(chat.provider_name) : chatTrigger?.includes("Not assigned"),
    JSON.stringify({ chat: chat?.provider_name, shown: chatTrigger }));
  check("the feature toggles are the ai section's settings, through ScopedSettings",
    truth.settings.length >= 10 && truth.settings.every((key) => rendered.features.includes(key)),
    JSON.stringify({ api: truth.settings.length, page: rendered.features.length }));
  check("the presets section renders its form", rendered.presets);
  await session.screenshot(resolve("scripts", "ai-settings-page-proof.png"), { fullPage: true });

  // 3. the provider form (read-only).
  const first = truth.providers[0];
  await session.click(`button[aria-label=${JSON.stringify(`Edit ${first.name}`)}]`, () => true);
  const form = await waitFor(session, `(() => { const d = document.querySelector("[role=dialog]"); if (!d) return null;
    return { reasoning: Boolean(d.querySelector("input[type=checkbox]")) || ${JSON.stringify(first.wire_shape)} === "local",
      text: d.textContent.includes("Wire shape") && d.textContent.includes("Default model") }; })()`);
  check("the provider form opens with its fields", form?.reasoning && form?.text, JSON.stringify(form));
  await session.click("[role=dialog] button", (text) => text.trim() === "Cancel");
  check("Cancel closes it without saving", await waitFor(session, `!document.querySelector("[role=dialog]")`));

  // 4. a real save: create, switch off, delete a throwaway preset.
  const form_ = '[data-ai-preset-form="new"]';
  await session.eval(setValue(`${form_} input`, tag));
  await session.eval(setValue(`${form_} textarea`, "Rewrite the selection as one short sentence."));
  await session.click(`${form_} button[type=submit]`, () => true);
  const saved = await waitFor(session, presetFromApi);
  created = Boolean(saved);
  check("a preset created on the page is saved", saved?.enabled === true && saved?.prompt.startsWith("Rewrite"), JSON.stringify(saved));
  check("the page lists it", await waitFor(session, `Boolean(document.querySelector('[data-ai-preset=${JSON.stringify(tag)}]'))`));
  await session.eval(`document.querySelector('[data-ai-preset=${JSON.stringify(tag)}] [role=switch]').click()`);
  const off = await waitFor(session, `(async () => { const p = await ${presetFromApi}; return p && p.enabled === false ? p : null; })()`);
  check("its switch saves enabled = false", Boolean(off), JSON.stringify(off));
  check("the switch reads off after the refetch",
    await waitFor(session, `document.querySelector('[data-ai-preset=${JSON.stringify(tag)}] [role=switch]')?.getAttribute("aria-checked") === "false"`));
  await session.click(`button[aria-label=${JSON.stringify(`Delete ${tag}`)}]`, () => true);
  const gone = await waitFor(session, `(async () => (await ${presetFromApi}) === null)()`);
  created = !gone;
  check("Delete removes it", gone);
  check("the page drops the row", await waitFor(session, `!document.querySelector('[data-ai-preset=${JSON.stringify(tag)}]')`));

  // 5. the plugin's gate (the query bar's and palette's Ask read it since RADD-1400) is tagged
  // with what its settings page invalidates. This page has no query bar: opening the palette
  // mounts its modes' gates, which read the status; closing it leaves the query unobserved.
  for (const type of ["rawKeyDown", "keyUp"]) {
    await session.send("Input.dispatchKeyEvent", { type, key: "k", code: "KeyK", windowsVirtualKeyCode: 75, modifiers: 2 });
  }
  await waitFor(session, `window.__RADD_QUERY_CLIENT__.getQueryData(["ai", "status"]) !== undefined`);
  for (const type of ["rawKeyDown", "keyUp"]) {
    await session.send("Input.dispatchKeyEvent", { type, key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  }
  await waitFor(session, `!document.querySelector('[role=dialog][aria-label="Command palette"]')`);
  const gate = await session.eval(`(async () => {
    const qc = window.__RADD_QUERY_CLIENT__;
    const status = qc.getQueryCache().find({ queryKey: ["ai", "status"], exact: true });
    if (!status) return { cached: false };
    const before = { at: status.state.dataUpdatedAt, stale: status.state.isInvalidated };
    // What the plugin's invalidateEntities(queryClient, "aiRole") does. Off the pages that use it the
    // gate has no observer, so it is marked stale (refetched on next use) rather than refetched now.
    await qc.invalidateQueries({ predicate: (q) => (q.meta?.entities ?? []).includes("aiRole") });
    await new Promise((r) => setTimeout(r, 800));
    return { cached: true, entities: status.meta?.entities, staleBefore: before.stale,
      reached: status.state.isInvalidated || status.state.dataUpdatedAt > before.at };
  })()`);
  check("the ai plugin's /ai/status gate declares aiProvider + aiRole, and their invalidation reaches it",
    gate.cached && gate.entities?.includes("aiProvider") && gate.entities?.includes("aiRole") && !gate.staleBefore && gate.reached,
    JSON.stringify(gate));

  // 6. links that lead here.
  await session.navigate(`${baseUrl}/settings/instance`, 1500);
  check("Server status's AI row links to the plugin's page",
    await waitFor(session, `[...document.querySelectorAll('a[href="/settings/ai"][data-status-row]')].length === 1`));
  await session.navigate(`${baseUrl}/settings/plugins`, 1500);
  check("the Plugins page links the ai plugin to its settings",
    await waitFor(session, `document.querySelectorAll('main a[href="/settings/ai"]').length > 0`));

  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors));
} finally {
  if (created) {
    const cleaned = await session.eval(`(async () => { ${API} const p = await ${presetFromApi};
      return p ? (await api("DELETE", "/ai/presets/" + p.id)).status : 204; })()`);
    check("the throwaway preset is deleted again", cleaned === 204, String(cleaned));
  }
  await close();
}
const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "ai settings page", baseUrl },
);
process.exit(failed ? 1 : 0);
