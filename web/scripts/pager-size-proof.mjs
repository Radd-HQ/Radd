#!/usr/bin/env node
/**
 * RADD-1177 proof: the list pager's page-size picker is real, personal, and
 * remembered.
 *
 *   node web/scripts/pager-size-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Signs in as an admin, creates a throwaway project with 60 issues and a list
 * view, then checks in a REAL browser that:
 *   1. the default page holds all 60 rows (200 per page) and the picker reads 200;
 *   2. picking 25 refetches with `limit=25` (read off the browser's own
 *      resource timing), shows 25 rows, page 1 of 3, and the total stays 60;
 *   3. a reload keeps 25 (localStorage), and page 3 holds the remaining 10.
 * Every check is a measurement. The project is deleted at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: pager-size-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9487;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-pager-size-proof");
const KEY = `PG${Date.now().toString(36).slice(-4).toUpperCase()}`;
const TOTAL = 60;

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

const STATE = (key) => `(() => {
  const main = document.querySelector("main") ?? document.body;
  const keys = new Set(main.innerText.match(new RegExp(${JSON.stringify("\\b" + key + "-\\d+\\b")}, "g")) ?? []);
  const pager = document.querySelector('nav[aria-label="Pagination"]');
  const current = pager?.querySelector('[aria-current="page"]')?.textContent?.trim() ?? null;
  const pages = [...(pager?.querySelectorAll('button[aria-label^="Page "]') ?? [])].map((b) => b.textContent.trim());
  const totalSpan = [...(pager?.querySelectorAll("span") ?? [])].find((el) => /items$/.test(el.textContent.trim()));
  const total = totalSpan ? totalSpan.textContent.replace(/[^\\d]/g, "") : null;
  const picker = pager?.querySelector("[data-page-size] button")?.textContent?.trim() ?? null;
  const limits = performance.getEntriesByType("resource")
    .map((e) => e.name).filter((n) => n.includes("/api/v1/items?"))
    .map((n) => new URL(n).searchParams.get("limit"));
  return { rows: keys.size, current, pages, total, picker, lastLimit: limits[limits.length - 1] ?? null };
})()`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { key: KEY };
  let projectId = null;
  const state = () => session.eval(STATE(KEY));
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);
    await session.eval(`localStorage.removeItem("radd.itemsPageSize")`);

    const setup = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Pager proof" });
      const view = await api("POST", "/views", { project_id: project.body.id, name: "Pager list", view_type: "list" });
      let created = 0;
      for (let i = 1; i <= ${TOTAL}; i += 1) {
        const r = await api("POST", "/items", { project_id: project.body.id, title: "row " + i });
        if (r.status === 201) created += 1;
      }
      return { project: project.body, view: view.body, created, statuses: [project.status, view.status] };
    })()`);
    context.setup = { statuses: setup.statuses, created: setup.created };
    checks.setupCreated = setup.statuses.every((s) => s === 201) && setup.created === TOTAL;
    projectId = setup.project.id;
    const url = `${baseUrl}/p/${KEY}/v/${setup.view.id}`;

    // 1. the default: one page of everything
    await session.navigate(url, 3000);
    let s = await state();
    context.default = s;
    checks.defaultPageHoldsEverything = s.rows === TOTAL && s.picker === "200" && s.lastLimit === "200";

    // 2. pick 25
    await session.click("[data-page-size] button", () => true);
    await sleep(300);
    await session.click('[role="option"]', (t) => t.trim() === "25");
    await sleep(1500);
    s = await state();
    context.after25 = s;
    checks.pickerRefetchesWithLimit25 = s.lastLimit === "25";
    checks.pageShows25Rows = s.rows === 25;
    checks.pageOneOfThree = s.current === "1" && s.pages.includes("3") && !s.pages.includes("4");
    checks.totalUnchanged = s.total === String(TOTAL);
    await session.screenshot(resolve("scripts", "pager-size-proof.png"));

    // 3. reload keeps it; the last page holds the remainder
    await session.navigate(url, 3000);
    s = await state();
    context.reloaded = s;
    checks.reloadKeeps25 = s.rows === 25 && s.picker === "25";
    await session.click('button[aria-label="Last page"]', () => true);
    await sleep(1500);
    s = await state();
    context.lastPage = s;
    checks.lastPageHoldsTheRemainder = s.current === "3" && s.rows === TOTAL - 50;
  } finally {
    await session.eval(`localStorage.removeItem("radd.itemsPageSize")`).catch(() => null);
    if (projectId) {
      await session.eval(`(async () => { ${API} return (await api("DELETE", "/projects/${projectId}")).status; })()`).catch(() => null);
    }
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
