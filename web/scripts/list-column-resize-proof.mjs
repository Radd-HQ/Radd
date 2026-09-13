/**
 * RADD-1110 proof: the list view's Item column (select/star/kind/flag/key/title)
 * can be resized by dragging its header handle, every row follows the header,
 * and the width survives a reload (per-user localStorage).
 *
 * It was flex-1 before — it absorbed whatever the configured columns left, its
 * handle changed only the NEXT column, and with no columns there was no handle
 * at all. Zero-dep CDP over lib/cdp.mjs; the drag is real pointer input.
 *
 *   node scripts/list-column-resize-proof.mjs <baseUrl> <email> <password>
 *
 * Two layouts, because they exercise different halves of the handle:
 *   - WIDE (1900px): the trailing spacer holds slack, so the Item column grows
 *     by exactly the drag distance and the stored width IS the rendered one;
 *   - TIGHT (1500px, the default columns on a laptop): the spacer is empty, so
 *     growth is borrowed from the next column down to its minimum — the Item
 *     column still gets wider, and the row still fits the container.
 * Picks the first list-type view of the first project that has one and holds
 * items, so an empty list cannot pass for a resized one.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, email, password] = process.argv.slice(2);
const PORT = 9481;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-list-column-resize-proof");
const DRAG_PX = 120;
const WIDE = 1900;
const TIGHT = 1500;

const ITEM_HEADER = '[data-column="title"]';
const ITEM_HANDLE = '[data-resize-column="title"]';
const ROW_ITEM_ZONE = 'li[class*="group/row"] > span:first-child';

const MEASURE = `(() => {
  const header = document.querySelector(${JSON.stringify(ITEM_HEADER)});
  const rows = [...document.querySelectorAll(${JSON.stringify(ROW_ITEM_ZONE)})];
  const handle = document.querySelector(${JSON.stringify(ITEM_HANDLE)});
  const next = header ? header.nextElementSibling : null;
  const round = (n) => Math.round(n * 10) / 10;
  // The LIST's scroller (the header's own ancestor) — a bare selector would
  // match the sidebar rail first and make the fit check pass on nothing.
  const scroller = header ? header.closest(".overflow-y-auto") : null;
  return {
    header: header ? round(header.getBoundingClientRect().width) : null,
    rows: rows.slice(0, 5).map((r) => round(r.getBoundingClientRect().width)),
    rowCount: rows.length,
    // The handle straddles the cell's right edge and the cell clips overflow,
    // so only its inner half is hit-testable: press just inside.
    handle: handle ? (() => { const r = handle.getBoundingClientRect(); return { x: r.left + 1, y: r.top + r.height / 2 }; })() : null,
    next: next && next.dataset.column ? { id: next.dataset.column, width: round(next.getBoundingClientRect().width) } : null,
    scrollWidth: scroller ? scroller.scrollWidth : null,
    clientWidth: scroller ? scroller.clientWidth : null,
  };
})()`;

async function drag(session, { x, y }, dx) {
  await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  await session.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  for (let step = 1; step <= 6; step++) {
    await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x + (dx * step) / 6, y, button: "left" });
    await sleep(30);
  }
  await session.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: x + dx, y, button: "left", clickCount: 1 });
  await sleep(300);
}

/** Fresh layout at `width`, one drag, one reload — the numbers for both layouts. */
async function scenario(session, url, storageKey, width) {
  await session.send("Emulation.setDeviceMetricsOverride", { width, height: 1000, deviceScaleFactor: 1, mobile: false });
  await session.navigate(url, 2500);
  await session.eval(`localStorage.removeItem(${JSON.stringify(storageKey)})`);
  await session.navigate(url, 2500);
  const before = await session.eval(MEASURE);
  if (!before.handle) throw new Error("no Item column handle in the header");
  if (before.rowCount === 0) throw new Error("no rows rendered");
  await drag(session, before.handle, DRAG_PX);
  const after = await session.eval(MEASURE);
  const stored = await session.eval(`JSON.parse(localStorage.getItem(${JSON.stringify(storageKey)}) || "{}").title ?? null`);
  await session.navigate(url, 2500);
  const reloaded = await session.eval(MEASURE);
  return { width, before, after, stored, reloaded };
}

const near = (a, b, tolerance = 1) => a !== null && b !== null && Math.abs(a - b) <= tolerance;
const rowsMatch = (m) => m.rows.every((w) => near(w, m.header));
const fits = (m) => m.scrollWidth !== null && m.scrollWidth <= m.clientWidth + 1;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: WIDE, height: 1000, scale: 1 });
  await session.navigate(baseUrl + "/", 1000);
  const status = await session.login(baseUrl, email, password);
  if (status >= 300) throw new Error(`login failed: ${status}`);

  const target = await session.eval(`(async () => {
    const j = (r) => r.json();
    const projects = await j(await fetch("/api/v1/projects?limit=50", {credentials:"include"}));
    const rows = Array.isArray(projects) ? projects : (projects.rows || []);
    for (const p of rows) {
      const views = await j(await fetch("/api/v1/views?project_id=" + p.id, {credentials:"include"}));
      const list = (Array.isArray(views) ? views : (views.rows || [])).find((v) => v.view_type === "list");
      if (!list) continue;
      const items = await j(await fetch("/api/v1/items?project_id=" + p.id + "&limit=1", {credentials:"include"}));
      const found = Array.isArray(items) ? items : (items.rows || []);
      if (found.length) return { projectKey: p.key, viewId: list.id, storageKey: "radd.view." + list.id + ".column-widths" };
    }
    return null;
  })()`);
  if (!target) throw new Error("no project with a list view and items");
  const url = `${baseUrl}/p/${target.projectKey}/v/${target.viewId}`;

  const wide = await scenario(session, url, target.storageKey, WIDE);
  const tight = await scenario(session, url, target.storageKey, TIGHT);
  await session.eval(`localStorage.removeItem(${JSON.stringify(target.storageKey)})`);

  const checks = {
    "hover-capable browser": await session.hoverCapable(),
    // Wide: slack exists, so the drag is exact and the stored width is the rendered one.
    "wide: the Item header grew by the drag distance (±2px)": near(wide.after.header - wide.before.header, DRAG_PX, 2),
    "wide: the next column kept its width": wide.after.next && near(wide.after.next.width, wide.before.next.width),
    "wide: every row's Item zone matches the header": rowsMatch(wide.after),
    "wide: the width is stored under the title pseudo-column": near(wide.stored, wide.after.header),
    "wide: the width survives a reload, rows included": near(wide.reloaded.header, wide.after.header) && rowsMatch(wide.reloaded),
    "wide: the table still fits the container": fits(wide.after),
    // Tight: no slack, so growth is borrowed from the next column.
    "tight: the Item header still grew": tight.after.header - tight.before.header >= 20,
    "tight: the next column lent the width": tight.after.next && tight.after.next.width < tight.before.next.width,
    "tight: every row's Item zone matches the header": rowsMatch(tight.after),
    "tight: the width survives a reload, rows included": near(tight.reloaded.header, tight.after.header) && rowsMatch(tight.reloaded),
    "tight: the table still fits the container (no horizontal scroll)": fits(tight.after),
    "no console errors": session.consoleErrors.length === 0,
  };
  const failed = report(checks, { url, wide, tight, consoleErrors: session.consoleErrors });
  process.exit(failed ? 1 : 0);
}

main().catch((error) => { console.error(error); process.exit(1); });
