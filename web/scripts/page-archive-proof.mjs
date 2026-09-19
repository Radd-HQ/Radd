#!/usr/bin/env node
/**
 * RADD-1228 proof (GitHub #7): archived wiki pages can be browsed, opened
 * read-only, and restored from the UI.
 *
 *   node web/scripts/page-archive-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Builds a throwaway space (Root > Mid > Leaf, plus Other) through the API,
 * archives Mid and Other, then measures in a REAL browser that:
 *   1. the tree hides the archived subtree and the rail's "Archived pages"
 *      link counts 2 (Leaf is hidden WITH Mid, not archived itself);
 *   2. `?archived=1` lists exactly Mid and Other, with path + subpage count;
 *   3. opening Mid shows the archived banner and NO editing chrome (title
 *      read-only, no Edit / Archive / Change-URL), while Restore is offered;
 *   6. search narrows the rows, select-all selects what is shown, bulk restore;
 *   7. bulk delete removes what it may and reports the refused row (RADD-1249);
 *   4. Restore from the browser puts Mid AND Leaf back in the tree and the
 *      count drops to 1;
 *   5. archiving Leaf when Mid is archived too, then restoring Leaf, warns
 *      about the ancestor and brings the chain back.
 * The space is deleted at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: page-archive-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9491;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-page-archive-proof");
const SLUG = `archive-proof-${Date.now().toString(36).slice(-5)}`;

const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, {
      method, headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
`;

const TREE = `(() => {
  const tree = document.querySelector("[data-page-tree]");
  const titles = tree ? [...tree.querySelectorAll("a")].map((a) => a.textContent.trim()) : null;
  const link = document.querySelector("[data-archived-pages-link]");
  const count = link?.querySelector("span")?.textContent?.trim() ?? null;
  const panel = document.querySelector("[data-archived-pages]");
  const rows = panel ? [...panel.querySelectorAll("[data-archived-page]")].map((li) => ({
    title: li.querySelector("a")?.textContent?.trim() ?? null,
    meta: li.querySelector("div > div")?.textContent?.trim() ?? null,
    restore: [...li.querySelectorAll("button")].map((b) => b.textContent.trim()).find((t) => /Restor/.test(t)) ?? null,
  })) : null;
  return { titles, archiveLink: Boolean(link), count, rows, dialog: document.querySelector('[role="dialog"]')?.textContent?.trim() ?? null };
})()`;

const PAGE = `(() => {
  const banner = document.querySelector("[data-archived-banner]");
  const title = document.querySelector('input[aria-label="Page title"]');
  const labels = [...document.querySelectorAll("button, a")].map((b) => (b.getAttribute("aria-label") || b.textContent).trim());
  return {
    banner: banner?.textContent?.trim() ?? null,
    bannerRestore: banner ? [...banner.querySelectorAll("button")].some((b) => /Restore/.test(b.textContent)) : false,
    bannerArchiveLink: Boolean(banner?.querySelector("a")),
    titleReadOnly: title ? title.readOnly : null,
    hasEdit: labels.some((l) => /^Edit$|^Edit page$/.test(l)),
    hasArchive: labels.includes("Archive page"),
    hasChangeUrl: labels.includes("Change URL"),
    hasDeletePermanently: labels.includes("Delete page permanently"),
  };
})()`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { slug: SLUG };
  let spaceId = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    context.login = await session.login(baseUrl, adminEmail, adminPassword);

    const setup = await session.eval(`(async () => { ${API}
      const space = await api("POST", "/page-spaces", { name: "Archive proof", slug: ${JSON.stringify(SLUG)} });
      const sid = space.body.id;
      const mk = async (title, parent_id) => (await api("POST", "/pages", { space_id: sid, title, body: "body of " + title, parent_id })).body;
      const root = await mk("Root", null);
      const mid = await mk("Mid", root.id);
      const leaf = await mk("Leaf", mid.id);
      const other = await mk("Other", root.id);
      const a1 = await api("DELETE", "/pages/" + mid.id);
      const a2 = await api("DELETE", "/pages/" + other.id);
      return { sid, root, mid, leaf, other, archived: [a1.status, a2.status] };
    })()`);
    spaceId = setup.sid;
    context.setup = { archived: setup.archived };
    checks.setupArchived = setup.archived.every((s) => s === 204);
    const spaceUrl = `${baseUrl}/pages/${SLUG}`;

    // 1. tree + rail link
    await session.navigate(spaceUrl, 2500);
    let t = await session.eval(TREE);
    context.tree = t;
    checks.treeHidesArchivedSubtree = Array.isArray(t.titles) && t.titles.includes("Root") && !t.titles.includes("Mid") && !t.titles.includes("Leaf") && !t.titles.includes("Other");
    checks.railLinkCountsArchivedPages = t.archiveLink && t.count === "2";

    // 2. the browser
    await session.click("[data-archived-pages-link]", () => true);
    await sleep(1500);
    t = await session.eval(TREE);
    context.browser = t;
    checks.browserListsExactlyTheArchived = Array.isArray(t.rows) && t.rows.map((r) => r.title).sort().join(",") === "Mid,Other";
    const midRow = t.rows?.find((r) => r.title === "Mid");
    checks.rowShowsPathAndSubpages = Boolean(midRow) && /Root/.test(midRow.meta) && /1 subpage/.test(midRow.meta) && /Archived/.test(midRow.meta);
    checks.browserUrlIsCarried = await session.eval(`location.search.includes("archived")`);
    await session.screenshot(resolve("scripts", "page-archive-proof-browser.png"));

    // 3. open Mid read-only
    await session.click("[data-archived-page] a", (text) => text.trim() === "Mid");
    await sleep(2000);
    const p = await session.eval(PAGE);
    context.page = p;
    checks.archivedPageShowsBanner = /archived/.test(p.banner ?? "") && p.bannerRestore && p.bannerArchiveLink;
    checks.archivedPageIsReadOnly = p.titleReadOnly === true && !p.hasEdit && !p.hasArchive && !p.hasChangeUrl;
    checks.managerKeepsPermanentDelete = p.hasDeletePermanently === true;
    await session.screenshot(resolve("scripts", "page-archive-proof-readonly.png"));

    // 4. restore Mid from the browser: Mid AND Leaf come back, Other stays.
    await session.navigate(spaceUrl + "?archived=1", 2500);
    await session.eval(`(() => {
      const li = [...document.querySelectorAll("[data-archived-page]")].find((el) => el.querySelector("a")?.textContent.trim() === "Mid");
      li?.querySelector("button")?.click();
    })()`);
    await sleep(1500);
    t = await session.eval(TREE);
    context.afterRestore = t;
    // A restored page leaves the list on refetch — the row is gone, not "Restored".
    checks.restoredRowLeavesTheList = t.rows?.map((r) => r.title).join(",") === "Other";
    await session.navigate(spaceUrl, 2500);
    // Expand Root so its children are in the DOM.
    await session.click('button[aria-label="Expand Root"]', () => true).catch(() => null);
    await sleep(300);
    await session.click('button[aria-label="Expand Mid"]', () => true).catch(() => null);
    await sleep(300);
    t = await session.eval(TREE);
    context.treeAfterRestore = t;
    checks.restoreBringsSubtreeBack = t.titles?.includes("Mid") && t.titles?.includes("Leaf") && !t.titles?.includes("Other");
    checks.countDropsAfterRestore = t.count === "1";

    // 5. a restore under an archived ancestor warns and restores the chain
    const nested = await session.eval(`(async () => { ${API}
      const l = await api("DELETE", "/pages/${setup.leaf.id}");
      const m = await api("DELETE", "/pages/${setup.mid.id}");
      return [l.status, m.status];
    })()`);
    context.nested = nested;
    await session.navigate(spaceUrl + "?archived=1", 2500);
    t = await session.eval(TREE);
    context.nestedRows = t.rows;
    const leafRow = t.rows?.find((r) => r.title === "Leaf");
    checks.nestedRowsBothListed = Boolean(leafRow) && Boolean(t.rows?.find((r) => r.title === "Mid"));
    await session.eval(`(() => {
      const li = [...document.querySelectorAll("[data-archived-page]")].find((el) => el.querySelector("a")?.textContent.trim() === "Leaf");
      li?.querySelector("button")?.click();
    })()`);
    await sleep(500);
    t = await session.eval(TREE);
    context.confirm = t.dialog;
    checks.restoreUnderArchivedAncestorWarns = /Mid/.test(t.dialog ?? "") && /restored with it/.test(t.dialog ?? "");
    await session.click('[role="dialog"] button', (text) => text.trim() === "Restore");
    await sleep(1500);
    await session.navigate(spaceUrl, 2500);
    await session.click('button[aria-label="Expand Root"]', () => true).catch(() => null);
    await sleep(300);
    await session.click('button[aria-label="Expand Mid"]', () => true).catch(() => null);
    await sleep(300);
    t = await session.eval(TREE);
    context.treeAfterChain = t;
    checks.chainRestored = t.titles?.includes("Mid") && t.titles?.includes("Leaf");

    // 6. RADD-1249: search, select, restore many. Archive Leaf and (still) Other;
    //    "Le" narrows to Leaf; select-all selects what is shown; bulk restore.
    await session.eval(`(async () => { ${API} await api("DELETE", "/pages/${setup.leaf.id}"); })()`);
    await session.navigate(spaceUrl + "?archived=1", 2500);
    await session.eval(`(() => {
      const el = document.querySelector("[data-archived-search]");
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, "Le");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(300);
    const searched = await session.eval(`[...document.querySelectorAll("[data-archived-page] a")].map((a) => a.textContent.trim())`);
    context.searched = searched;
    checks.searchNarrowsTheRows = searched.join(",") === "Leaf";
    await session.click("[data-archived-select-all]", () => true);
    await sleep(200);
    const selectedCount = await session.eval(`document.querySelector("[data-archived-selected-count]")?.textContent?.trim() ?? null`);
    context.selectedCount = selectedCount;
    checks.selectAllSelectsTheShownRows = selectedCount === "1 selected";
    await session.click("[data-archived-bulk-restore]", () => true);
    await sleep(400);
    await session.click('[role="dialog"] button', (text) => text.trim() === "Restore");
    await sleep(1500);
    // The search still narrows to "Le": with Leaf restored nothing matches, and
    // clearing the box shows what is left — Other.
    const noMatch = await session.eval(`Boolean(document.querySelector("[data-archived-no-match]"))`);
    await session.eval(`(() => {
      const el = document.querySelector("[data-archived-search]");
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, "");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(300);
    t = await session.eval(TREE);
    context.afterBulkRestore = { noMatch, rows: t.rows };
    checks.bulkRestoreRemovesTheRestoredRow = noMatch === true && t.rows?.map((r) => r.title).join(",") === "Other";

    // 7. Bulk delete with a skip: Mid archived while Leaf is live under it is
    //    refused per page; Other goes. The refused row says why and stays.
    await session.eval(`(async () => { ${API} await api("DELETE", "/pages/${setup.mid.id}"); })()`);
    await session.navigate(spaceUrl + "?archived=1", 2500);
    await session.click("[data-archived-select-all]", () => true);
    await sleep(200);
    const twoSelected = await session.eval(`document.querySelector("[data-archived-selected-count]")?.textContent?.trim() ?? null`);
    await session.click("[data-archived-bulk-delete]", () => true);
    await sleep(400);
    const deleteDialog = await session.eval(`document.querySelector('[role="dialog"]')?.textContent ?? ""`);
    await session.click('[role="dialog"] button', (text) => text.trim() === "Delete");
    await sleep(1500);
    const afterDelete = await session.eval(`(async () => { ${API}
      const rows = [...document.querySelectorAll("[data-archived-page]")].map((li) => ({ title: li.querySelector("a")?.textContent.trim(), skipped: li.querySelector("[data-archived-skipped]")?.textContent ?? null }));
      const other = (await api("GET", "/pages/${setup.other.id}")).status;
      const mid = (await api("GET", "/pages/${setup.mid.id}")).status;
      return { rows, other, mid };
    })()`);
    context.afterBulkDelete = { twoSelected, deleteDialog: /permanently/.test(deleteDialog), ...afterDelete };
    checks.bulkDeleteRemovesWhatItMayAndReportsTheRest =
      twoSelected === "2 selected" && afterDelete.other === 404 && afterDelete.mid === 200 &&
      afterDelete.rows.length === 1 && afterDelete.rows[0].title === "Mid" && /non-archived child/.test(afterDelete.rows[0].skipped ?? "");
  } finally {
    if (spaceId) {
      await session.eval(`(async () => { ${API} return (await api("DELETE", "/page-spaces/${spaceId}?force=true")).status; })()`).catch(() => null);
    }
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
