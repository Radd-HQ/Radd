#!/usr/bin/env node
/**
 * Proof for the public reports radd-hq/radd#8–#17 (RADD-1236…1245), in one
 * throwaway project + one throwaway page space:
 *
 *   node web/scripts/remus-reports-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 *   #8  add/list/remove participants over MCP, by email;
 *   #9  a worklog logged over MCP appears on the open item with NO reload;
 *   #10 the theme toggles light AND back from the account menu, no reload;
 *   #11 a related link added over MCP appears in the panel with no reload;
 *   #12 `/pages/<page uuid>` lands on the page; a uuid nobody owns explains
 *       the address shape and links to the spaces;
 *   #13 the palette's Go to lists Pages;
 *   #14 the collapsed rail carries Pages;
 *   #15 in the wiki the top button is "New page" and creates one under the
 *       open page; elsewhere it is still "New item";
 *   #16 a linear (REST-written) history carries no "grouped" note;
 *   #17 a manager can delete a LIVE page from the page, landing on the space.
 * Every check is a measurement. Fixtures are deleted at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: remus-reports-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9496;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-remus-reports-proof");
const STAMP = Date.now().toString(36).slice(-5);
const KEY = `RR${STAMP.slice(-4).toUpperCase()}`;
const SLUG = `remus-proof-${STAMP}`;

const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, {
      method, headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
  const mcp = async (name, args) => {
    const r = await fetch("/api/v1/mcp", {
      method: "POST", headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }),
    });
    const body = await r.json();
    const text = body?.result?.content?.[0]?.text;
    return { status: r.status, error: body?.error ?? null, isError: body?.result?.isError ?? null, result: text ? JSON.parse(text) : body?.result };
  };
`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { key: KEY, slug: SLUG };
  let projectId = null;
  let spaceId = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    context.login = await session.login(baseUrl, adminEmail, adminPassword);
    const setup = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Remus proof" });
      await api("PUT", "/projects/" + project.body.id + "/timelogging", { enabled: true });
      const item = await api("POST", "/items", { project_id: project.body.id, title: "Out-of-band target" });
      const space = await api("POST", "/page-spaces", { name: "Remus proof", slug: ${JSON.stringify(SLUG)} });
      const parent = await api("POST", "/pages", { space_id: space.body.id, title: "Parent", body: "v1 body" });
      await api("PATCH", "/pages/" + parent.body.id, { body: "v2 body", expected_version: parent.body.version });
      await api("PATCH", "/pages/" + parent.body.id, { body: "v3 body", expected_version: parent.body.version + 1 });
      const doomed = await api("POST", "/pages", { space_id: space.body.id, title: "Doomed", body: "bye" });
      return { project: project.body, item: item.body, space: space.body, parent: parent.body, doomed: doomed.body };
    })()`);
    projectId = setup.project.id;
    spaceId = setup.space.id;
    context.setup = { item: setup.item.key, parent: setup.parent.path, doomed: setup.doomed.path };

    // --- #9 / #11 / #8: out-of-band writes reach the open item -------------
    await session.navigate(`${baseUrl}/issues/${setup.item.key}`, 2500);
    // Both surfaces start collapsed (the rail's Time tracking section, the
    // Related links card) — open them so the measurement is of the rows.
    await session.click("button[aria-expanded]", (t) => /^Time tracking$/.test(t.trim()));
    await session.click("button[aria-expanded]", (t) => /^Related links/.test(t.trim()));
    await sleep(600);
    const before = await session.eval(`({ note: document.body.textContent.includes("remus-oob-note"), link: Boolean(document.querySelector('a[href="https://gitlab.example.com/infra/awx/-/merge_requests/14"]')) })`);
    context.before = before;
    const oob = await session.eval(`(async () => { ${API}
      const logged = await mcp("log_work", { key: ${JSON.stringify(setup.item.key)}, time_spent: "1h 30m", note: "remus-oob-note" });
      const linked = await mcp("add_related_link", { key: ${JSON.stringify(setup.item.key)}, url: "https://gitlab.example.com/infra/awx/-/merge_requests/14", title: "awx !14" });
      const added = await mcp("add_participant", { key: ${JSON.stringify(setup.item.key)}, email: ${JSON.stringify(adminEmail)} });
      const listed = await mcp("list_participants", { key: ${JSON.stringify(setup.item.key)} });
      const removed = await mcp("remove_participant", { key: ${JSON.stringify(setup.item.key)}, email: ${JSON.stringify(adminEmail)} });
      const after = await mcp("list_participants", { key: ${JSON.stringify(setup.item.key)} });
      const links = await mcp("list_related_links", { key: ${JSON.stringify(setup.item.key)} });
      return { logged, linked, added, listed, removed, after, links };
    })()`);
    context.oob = { logged: oob.logged.result, added: oob.added.result, listed: oob.listed.result, after: oob.after.result, links: oob.links.result };
    checks.participantsAddListRemoveOverMcp =
      oob.added.result?.added?.email === adminEmail &&
      (oob.listed.result?.participants ?? []).some((p) => p.email === adminEmail) &&
      oob.removed.result?.removed?.email === adminEmail &&
      (oob.after.result?.participants ?? []).length === 0;
    checks.relatedLinksListOverMcp = (oob.links.result?.links ?? []).map((l) => l.title).join() === "awx !14";
    await sleep(3500); // realtime coalesce + refetch
    const live = await session.eval(`({ note: document.body.textContent.includes("remus-oob-note"), link: Boolean(document.querySelector('a[href="https://gitlab.example.com/infra/awx/-/merge_requests/14"]')), path: location.pathname })`);
    context.live = live;
    checks.worklogAppearsWithoutReload = before.note === false && live.note === true;
    checks.relatedLinkAppearsWithoutReload = before.link === false && live.link === true;
    await session.screenshot(resolve("scripts", "remus-reports-proof-item.png"));

    // --- #10: theme toggles and toggles BACK ---------------------------------
    const accountTrigger = `button[aria-haspopup="menu"]`;
    const openAccount = async () => {
      // The predicate is serialised into the page, so it cannot close over adminEmail.
      await session.click(accountTrigger, (t) => /@/.test(t) && /theme|Profile|.+/.test(t));
      await sleep(300);
      return session.eval(`[...document.querySelectorAll('[role="menuitem"]')].map((m) => m.textContent.trim())`);
    };
    const menu1 = await openAccount();
    await session.click('[role="menuitem"]', (t) => /Light theme/.test(t));
    await sleep(300);
    const afterLight = await session.eval(`document.documentElement.classList.contains("light")`);
    const menu2 = await openAccount();
    await session.click('[role="menuitem"]', (t) => /Dark theme/.test(t)).catch(() => null);
    await sleep(300);
    const afterDark = await session.eval(`document.documentElement.classList.contains("light")`);
    context.theme = { menu1, afterLight, menu2, afterDark };
    checks.themeSwitchesToLightWithoutReload = menu1.some((t) => /Light theme/.test(t)) && afterLight === true;
    checks.themeMenuFlipsAndSwitchesBack = menu2.some((t) => /Dark theme/.test(t)) && afterDark === false;

    // --- #15: the top button follows the route --------------------------------
    await session.navigate(`${baseUrl}/`, 1500);
    const onHome = await session.eval(`[...document.querySelectorAll("button")].map((b) => b.textContent.trim()).filter((t) => /^New (item|page)$/.test(t))`);
    await session.navigate(`${baseUrl}/pages/${SLUG}/${setup.parent.path}`, 2500);
    const onPage = await session.eval(`(() => { const b = document.querySelector("[data-new-page]"); return b ? { text: b.textContent.trim(), title: b.title, disabled: b.disabled } : null; })()`);
    context.newButton = { onHome, onPage };
    checks.newItemElsewhere = onHome.join() === "New item";
    checks.newPageOnTheWikiNamesTheParent = onPage?.text === "New page" && onPage.title === "New page under Parent" && onPage.disabled === false;
    await session.click("[data-new-page]", () => true);
    await sleep(2000);
    const created = await session.eval(`({ path: location.pathname, title: document.querySelector('input[aria-label="Page title"]')?.value ?? null })`);
    context.created = created;
    checks.newPageLandsUnderTheParent = created.path.startsWith(`/pages/${SLUG}/${setup.parent.path}/`) && created.title === "Untitled";

    // --- #16: a linear history carries no grouped note ------------------------
    await session.navigate(`${baseUrl}/pages/${SLUG}/${setup.parent.path}`, 2500);
    await session.click("button", (t) => /^History$/.test(t)).catch(() => session.click('[role="tab"]', (t) => /History/.test(t)));
    await sleep(800);
    const history = await session.eval(`({ versions: [...document.querySelectorAll("li span")].map((s) => s.textContent.trim()).filter((t) => /^v\\d+$/.test(t)), grouped: document.querySelector("[data-history-grouped]")?.textContent?.trim() ?? null })`);
    context.history = history;
    checks.linearHistoryListsEveryVersionAndNoGroupedNote = history.versions.join() === "v2,v1" && history.grouped === null;

    // --- #12: a page uuid in the space slot lands on the page ------------------
    await session.navigate(`${baseUrl}/pages/${setup.parent.id}`, 2500);
    const rescued = await session.eval(`location.pathname`);
    context.rescued = rescued;
    checks.pageUuidAddressLandsOnThePage = rescued === `/pages/${SLUG}/${setup.parent.path}`;
    await session.navigate(`${baseUrl}/pages/00000000-0000-4000-8000-000000000000`, 2500);
    const bogus = await session.eval(`({ text: document.body.textContent, spaces: [...document.querySelectorAll("a")].some((a) => a.textContent.trim() === "All spaces" && a.getAttribute("href") === "/pages") })`);
    context.bogus = { spaces: bogus.spaces, explains: /pageId=/.test(bogus.text) };
    checks.unknownUuidExplainsTheAddressAndLinksOut = /Page space not found/.test(bogus.text) && /pageId=/.test(bogus.text) && bogus.spaces === true;

    // --- #14 / #13: the rail and the palette carry Pages ----------------------
    await session.navigate(`${baseUrl}/`, 1500);
    await session.click('button[aria-label="Collapse sidebar"]', () => true);
    await sleep(500);
    const rail = await session.eval(`(() => { const a = document.querySelector('nav[aria-label="Primary"] a[aria-label="Pages"]'); return a ? a.getAttribute("href") : null; })()`);
    context.rail = rail;
    checks.collapsedRailLinksToPages = rail === "/pages";
    await session.click('nav[aria-label="Primary"] button[aria-label="Search"]', () => true);
    await sleep(600);
    const palette = await session.eval(`(() => {
      const dialog = document.querySelector('[role="dialog"]');
      const text = dialog?.textContent ?? "";
      const entries = dialog ? [...dialog.querySelectorAll("button, [role=option]")].map((b) => b.textContent.trim()) : [];
      return { hasGoTo: /Go to/.test(text), pages: entries.includes("Pages") };
    })()`);
    context.palette = palette;
    checks.goToListsPages = palette.hasGoTo && palette.pages;
    await session.screenshot(resolve("scripts", "remus-reports-proof-palette.png"));
    await session.eval(`document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))`);
    await session.click('button[aria-label="Expand sidebar"]', () => true).catch(() => null);

    // --- #17: a LIVE page can be deleted from the page -------------------------
    await session.navigate(`${baseUrl}/pages/${SLUG}/${setup.doomed.path}`, 2500);
    const hasDelete = await session.eval(`Boolean(document.querySelector('button[aria-label="Delete page permanently"]'))`);
    await session.click('button[aria-label="Delete page permanently"]', () => true);
    await sleep(400);
    const dialog = await session.eval(`document.querySelector('[role="dialog"], [role="alertdialog"]')?.textContent?.trim() ?? null`);
    await session.click('[role="dialog"] button, [role="alertdialog"] button', (t) => t.trim() === "Delete");
    await sleep(1500);
    const gone = await session.eval(`(async () => { ${API} return { path: location.pathname, status: (await api("GET", "/pages/${setup.doomed.id}")).status }; })()`);
    context.deleted = { hasDelete, dialog, gone };
    checks.livePageOffersDeleteAndLandsOnTheSpace = hasDelete && /Archive keeps it restorable/.test(dialog ?? "") && gone.path === `/pages/${SLUG}` && gone.status === 404;
  } finally {
    await session.eval(`(async () => { ${API}
      ${spaceId ? `await api("DELETE", "/page-spaces/${spaceId}");` : ""}
      ${projectId ? `await api("DELETE", "/projects/${projectId}");` : ""}
    })()`).catch(() => null);
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
