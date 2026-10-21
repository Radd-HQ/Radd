#!/usr/bin/env node
/**
 * RADD-1520 / 1521 / 1522 proof — the roadmap zoom, measured in a real browser:
 *
 *   RADD-1521  fewer rows are in the DOM than exist, the content height is unchanged, and scrolling
 *              to the bottom mounts the last row and unmounts the first
 *   RADD-1522  a tray drop takes the row it was dropped on: beside a top-level row, after an epic's
 *              block when dropped on one of its children, first child when a child is dropped on its
 *              epic — with the insertion line on the landing row while dragging; Undo reverts each
 *   RADD-1520  Fit puts a 3.5-year domain inside the pane with no overlapping axis labels; the rows
 *              scale with the day width (every row exactly `data-row-h` apart, the group box ending
 *              on its last child at that pitch); the floor is 0.25 px/day with 8 px rows; zooming
 *              back past the default returns 44 px rows; the label cell steps full → mini → none
 *              without clipping; a bar dragged at a fractional day width commits the rounded day
 *              delta; the zoom survives a reload; `A` fits from the keyboard
 *
 *   node web/scripts/roadmap-zoom-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * Creates a throwaway project (two epics with six children each, thirty standalone leaves spread
 * over 2024-02 → 2027-06, three unscheduled items for the tray, one roadmap view), measures, and
 * deletes the project.
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, report, sleep } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PORT = 9492;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-roadmap-zoom-proof");
const KEY = `RZ${Date.now().toString(36).slice(-4).toUpperCase()}`;
const DAY_PX = 9; // ROADMAP_DAY_WIDTH
const ROW_PX = 44; // ROADMAP_ROW_H
const DAY_MIN = 0.25; // ROADMAP_DAY_WIDTH_MIN
const ROW_MIN = 8; // ROADMAP_ROW_MIN_H
const WHEEL_FACTOR = 1.18; // ROADMAP_ZOOM_WHEEL_FACTOR

const pad = (n) => String(n).padStart(2, "0");
const isoAt = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const plusDays = (iso, days) => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return isoAt(d);
};

/** The pane, the timeline's data attributes and the row geometry in one probe. */
const STATE = `(() => {
  const root = document.querySelector("[data-roadmap-timeline]");
  const pane = root?.parentElement;
  if (!root || !pane) return null;
  const rows = [...document.querySelectorAll("[data-row-kind]")].map((cell) => {
    const row = cell.parentElement;
    const r = row.getBoundingClientRect();
    const text = cell.textContent.trim();
    const title = cell.querySelector("span[title]");
    return { kind: cell.dataset.rowKind, top: r.top, bottom: r.bottom, h: r.height, text,
      overflow: cell.scrollHeight > cell.clientHeight + 0.5,
      fontPx: title ? parseFloat(getComputedStyle(title).fontSize) : null,
      kindBadge: Boolean(cell.querySelector("[title^='Type:'], [title^='Kind:'], svg:not(button svg)")) };
  });
  const labels = [...root.querySelectorAll(".sticky.top-0 span.absolute.top-1")].map((s) => {
    const r = s.getBoundingClientRect(); return { text: s.textContent, left: r.left, right: r.right };
  }).sort((a, b) => a.left - b.left);
  const overlaps = labels.filter((l, i) => i > 0 && l.left < labels[i - 1].right - 0.5).length;
  const bars = [...document.querySelectorAll("[data-bar-item]")].map((el) => ({ id: el.dataset.barItem, h: el.getBoundingClientRect().height, w: el.getBoundingClientRect().width, left: parseFloat(el.style.left) }));
  const regions = [...document.querySelectorAll("[data-epic-region]")].map((el) => { const r = el.getBoundingClientRect(); return { id: el.dataset.epicRegion, top: r.top, bottom: r.bottom }; });
  const sel = document.querySelector("[aria-label='Zoom (day width)']");
  const windowFirst = Number((document.querySelector("[data-row-window]")?.dataset.rowWindow ?? "0-0").split("-")[0]);
  return {
    dayWidth: Number(root.dataset.dayWidth), rowH: Number(root.dataset.rowH), tier: root.dataset.axisTier, windowFirst,
    clientWidth: pane.clientWidth, clientHeight: pane.clientHeight, scrollWidth: pane.scrollWidth, scrollHeight: pane.scrollHeight,
    scrollTop: pane.scrollTop, paneTop: pane.getBoundingClientRect().top + pane.clientTop, labelWidth: parseFloat(root.querySelector(".sticky.top-0 > div").style.width),
    rows, labels: labels.length, overlaps, weekLabels: root.querySelectorAll(".sticky.top-0 span.absolute.top-5").length,
    bars, regions, zoomLabel: sel?.textContent ?? null, keys: rows.map((r) => r.text.slice(0, 12)),
  };
})()`;

/** One ctrl+wheel event on the pane; `steps` notches (negative = zoom in), fractional allowed. */
const WHEEL = (steps) => `(() => new Promise((done) => {
  const pane = document.querySelector("[data-roadmap-timeline]").parentElement;
  const r = pane.getBoundingClientRect();
  pane.dispatchEvent(new WheelEvent("wheel", { deltaY: ${steps} * 100, ctrlKey: true, bubbles: true, cancelable: true, clientX: r.left + 500, clientY: r.top + 300 }));
  requestAnimationFrame(() => requestAnimationFrame(() => done(true)));
}))()`;
/** Zoom to an exact day width through the wheel maths (factor ** steps). */
const stepsTo = (from, to) => -Math.log(to / from) / Math.log(WHEEL_FACTOR);

const SAVE = `(() => { const b = [...document.querySelectorAll("button")].find((x) => /^Sav/.test(x.textContent || "")); return b ? b.textContent : null; })()`;
const BAR_RECT = (id) => `(() => { const r = document.querySelector("[data-bar-item='${id}']")?.getBoundingClientRect(); return r ? { x: r.left, y: r.top, w: r.width, h: r.height } : null; })()`;

async function main() {
  const { session, close, baseUrl, finish, check } = await startProof({ port: PORT, profile: PROFILE, width: 1440, height: 1000 });
  const context = { key: KEY };
  let projectId = null;
  try {
    // --- setup: 2 epics × 6 children + 30 leaves over 2024-02 → 2027-06 (≈1,290 domain days) -------
    const leaves = [];
    for (let i = 0; i < 30; i++) {
      const start = plusDays("2024-03-04", i * 40);
      leaves.push({ title: `leaf ${pad(i + 1)}`, start_date: start, target_date: plusDays(start, 9) });
    }
    const setup = await session.eval(`(async () => { ${PAGE_API}
      const project = (await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Roadmap zoom proof" })).body;
      const item = async (body) => (await api("POST", "/items", { project_id: project.id, ...body })).body;
      const epic1 = await item({ title: "Epic one", kind: "epic", start_date: "2024-02-05", target_date: "2024-06-28" });
      const epic2 = await item({ title: "Epic two", kind: "epic", start_date: "2026-01-05", target_date: "2026-05-29" });
      const kids = [];
      for (let i = 0; i < 6; i++) {
        const s1 = new Date("2024-02-05T12:00:00"); s1.setDate(s1.getDate() + i * 24);
        const s2 = new Date("2026-01-05T12:00:00"); s2.setDate(s2.getDate() + i * 24);
        const iso = (d) => d.toISOString().slice(0, 10);
        const e1 = new Date(s1); e1.setDate(e1.getDate() + 13);
        const e2 = new Date(s2); e2.setDate(e2.getDate() + 13);
        kids.push(await item({ title: "one child " + (i + 1), parent_id: epic1.id, start_date: iso(s1), target_date: iso(e1) }));
        kids.push(await item({ title: "two child " + (i + 1), parent_id: epic2.id, start_date: iso(s2), target_date: iso(e2) }));
      }
      const leaves = [];
      for (const body of ${JSON.stringify(leaves)}) leaves.push(await item(body));
      const trayOne = await item({ title: "tray one" });
      const trayTwo = await item({ title: "tray two" });
      const trayChild = await item({ title: "tray child", parent_id: epic1.id });
      const view = (await api("POST", "/views", { project_id: project.id, name: "Zoom roadmap", view_type: "roadmap" })).body;
      return { project, epic1, epic2, kids, leaves, trayOne, trayTwo, trayChild, view };
    })()`);
    const { project, epic1, epic2, kids, leaves: leafItems, trayOne, trayTwo, trayChild, view } = setup;
    projectId = project?.id ?? null;
    check("setup created the project, 44 rows' worth of items and the view", Boolean(project?.id && epic1?.id && epic2?.id && view?.id && leafItems?.length === 30), JSON.stringify({ project: project?.id, view: view?.id, leaves: leafItems?.length }));
    const url = `${baseUrl}/p/${KEY}/v/${view.id}`;
    await session.navigate(url, 3000);

    // --- default zoom ----------------------------------------------------------------------------
    let s = await session.eval(STATE);
    context.default = s && { dayWidth: s.dayWidth, rowH: s.rowH, tier: s.tier, rows: s.rows.length, scrollWidth: s.scrollWidth, scrollHeight: s.scrollHeight, clientHeight: s.clientHeight };
    check("the default zoom is 9 px/day with 44 px rows, month labels and weekly ticks", s && s.dayWidth === DAY_PX && s.rowH === ROW_PX && s.tier === "month" && s.weekLabels > 0, JSON.stringify(context.default));
    const pitchOk = (state) => state.rows.every((row, i) => i === 0 || Math.abs(row.top - state.rows[i - 1].bottom) < 0.01) && state.rows.every((row) => Math.abs(row.h - state.rowH) < 0.01);
    check("rows are exactly one pitch apart at the default", s && pitchOk(s), JSON.stringify(s?.rows.slice(0, 3).map((r) => [r.top, r.h])));

    // --- RADD-1521: virtualized rows ---------------------------------------------------------------
    const total = 2 + 12 + 30;
    check("fewer rows are in the DOM than exist (44) while the content height counts them all", s && s.rows.length < total && s.rows.length >= Math.ceil((s.clientHeight - 40) / ROW_PX) && s.scrollHeight >= 40 + total * ROW_PX, JSON.stringify({ rendered: s?.rows.length, total, scrollHeight: s?.scrollHeight }));
    const firstKey = s?.keys[0];
    await session.eval(`(() => { const p = document.querySelector("[data-roadmap-timeline]").parentElement; p.scrollTop = p.scrollHeight; return p.scrollTop; })()`);
    await sleep(300);
    s = await session.eval(STATE);
    // At the bottom the last row ends one open drop lane (ROW_PX) above the pane's visible edge
    // (clientTop + clientHeight: inside the pane's border, above its horizontal scrollbar).
    const lastBottom = s ? Math.max(...s.rows.map((r) => r.bottom)) : NaN;
    const visibleBottom = s ? s.paneTop + s.clientHeight : NaN;
    check("scrolling to the bottom mounts the last row and unmounts the first", s && s.rows.length < total && !s.keys.includes(firstKey) && Math.abs(lastBottom - (visibleBottom - ROW_PX)) < 1, JSON.stringify({ first: firstKey, rendered: s?.rows.length, lastBottom, visibleBottom }));
    await session.eval(`(() => { const p = document.querySelector("[data-roadmap-timeline]").parentElement; p.scrollTop = 0; return true; })()`);
    await sleep(200);

    // --- RADD-1522: a tray drop lands on the row it was dropped on ----------------------------------
    // Absolute row indices: the rows block mounts a window (RADD-1521), so a DOM index is offset by
    // the window's first absolute index; -1 when the row is not mounted.
    const WINDOW_FIRST = `Number((document.querySelector("[data-row-window]")?.dataset.rowWindow ?? "0-0").split("-")[0])`;
    const ROW_INDEX = (key) => `(() => { const i = [...document.querySelectorAll("[data-row-kind]")].findIndex((cell) => { const t = cell.textContent.trim(); return t.startsWith(${JSON.stringify(key)}) && !/\\d/.test(t.charAt(${key.length})); }); return i < 0 ? -1 : ${WINDOW_FIRST} + i; })()`;
    const INDICATOR = `(() => { const i = [...document.querySelectorAll("[data-row-kind]")].findIndex((cell) => /shadow-\\[inset_0_-?2px/.test(cell.parentElement.className)); return i < 0 ? -1 : ${WINDOW_FIRST} + i; })()`;
    /** Scroll the pane so absolute row `index` is centred (and therefore mounted). */
    const scrollToRow = async (index) => {
      await session.eval(`(() => { const p = document.querySelector("[data-roadmap-timeline]").parentElement; p.scrollTop = Math.max(0, 40 + ${index} * ${ROW_PX} - p.clientHeight / 2); return p.scrollTop; })()`);
      await sleep(250);
    };
    /** The absolute index of the row with `key`, scanning the pane a screen at a time. */
    const rowIndex = async (key) => {
      const screens = await session.eval(`(() => { const p = document.querySelector("[data-roadmap-timeline]").parentElement; return Math.ceil(p.scrollHeight / p.clientHeight); })()`);
      for (let screen = 0; screen <= screens; screen++) {
        await session.eval(`(() => { const p = document.querySelector("[data-roadmap-timeline]").parentElement; p.scrollTop = ${screen} * p.clientHeight; return true; })()`);
        await sleep(200);
        const index = await session.eval(ROW_INDEX(key));
        if (index >= 0) return index;
      }
      return -1;
    };
    /** Drag a tray card and drop it on the `before` (top) or bottom half of the row at `index`. */
    const dropOnRow = async (item, index, before) => {
      await scrollToRow(index);
      const geometry = await session.eval(`(() => {
        const rowEl = document.querySelectorAll("[data-row-kind]")[${index} - ${WINDOW_FIRST}].parentElement;
        const row = rowEl.getBoundingClientRect();
        // The pane is scrolled to today, so the root's left is far off-screen: measure from the PANE.
        const pane = document.querySelector("[data-roadmap-timeline]").parentElement.getBoundingClientRect();
        return { x: pane.left + ${260 + 60}, y: ${before} ? row.top + row.height * 0.25 : row.top + row.height * 0.75 };
      })()`);
      await session.eval(`(() => {
        const card = document.querySelector("[data-tray-item='${item.key}']");
        const dt = new DataTransfer();
        card.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: dt }));
        window.__proofDt = dt;
      })()`);
      await sleep(150);
      const over = await session.eval(`(() => {
        const dt = window.__proofDt;
        const target = document.elementFromPoint(${geometry.x}, ${geometry.y});
        const init = { bubbles: true, cancelable: true, dataTransfer: dt, clientX: ${geometry.x}, clientY: ${geometry.y} };
        target.dispatchEvent(new DragEvent("dragover", init));
        return true;
      })()`);
      await sleep(100);
      const indicator = await session.eval(INDICATOR);
      await session.eval(`(() => {
        const dt = window.__proofDt;
        const target = document.elementFromPoint(${geometry.x}, ${geometry.y});
        const init = { bubbles: true, cancelable: true, dataTransfer: dt, clientX: ${geometry.x}, clientY: ${geometry.y} };
        target.dispatchEvent(new DragEvent("drop", init));
        document.querySelector("[data-tray-item='${item.key}']")?.dispatchEvent(new DragEvent("dragend", { bubbles: true, cancelable: true, dataTransfer: dt }));
        return true;
      })()`);
      await sleep(400);
      return { over, indicator, index: await session.eval(ROW_INDEX(item.key)), save: await session.eval(SAVE) };
    };
    // The default rank is newest first, so the thirty leaves lead and the two epic blocks follow;
    // rows are located by key, never assumed.
    const heightBefore = await session.eval(`document.querySelector("[data-roadmap-timeline]").parentElement.scrollHeight`);
    const d1 = await dropOnRow(trayOne, 15, true);
    check("a tray item dropped on the top half of row 15 IS row 15, with the insertion line there first", d1.indicator === 15 && d1.index === 15 && /Save · 1/.test(d1.save ?? ""), JSON.stringify(d1));
    const e1 = await rowIndex(epic1.key);
    const d2 = await dropOnRow(trayChild, e1, false);
    check("an epic's own child dropped on the epic row becomes its first child", e1 >= 0 && d2.indicator === e1 && d2.index === e1 + 1 && /Save · 2/.test(d2.save ?? ""), JSON.stringify({ e1, ...d2 }));
    const e2 = await rowIndex(epic2.key);
    const c2 = await rowIndex(kids[1].key); // "two child 1", somewhere in epic two's six-row block
    const d3 = await dropOnRow(trayTwo, c2, true);
    check("a top-level item dropped on a child row lands right after that epic's block, the line on its last child", e2 >= 0 && c2 > e2 && c2 <= e2 + 6 && d3.indicator === e2 + 6 && d3.index === e2 + 7 && /Save · 3/.test(d3.save ?? ""), JSON.stringify({ e2, c2, ...d3 }));
    for (let i = 0; i < 3; i++) {
      await session.eval(`(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true })); return true; })()`);
      await sleep(150);
    }
    const heightAfter = await session.eval(`document.querySelector("[data-roadmap-timeline]").parentElement.scrollHeight`);
    const undoneSave = await session.eval(SAVE);
    const trayRows = await Promise.all([trayOne, trayTwo, trayChild].map((item) => rowIndex(item.key)));
    check("three Undos remove the three drops and leave the draft clean", heightAfter === heightBefore && trayRows.every((index) => index === -1) && /^Saved/.test(undoneSave ?? ""), JSON.stringify({ undoneSave, heightBefore, heightAfter, trayRows }));
    await scrollToRow(0);

    // --- Fit ---------------------------------------------------------------------------------------
    await session.eval(`(() => { document.querySelector("button[aria-label='Fit the whole timeline']")?.click(); return true; })()`);
    await sleep(500);
    s = await session.eval(STATE);
    context.fit = s && { dayWidth: s.dayWidth, rowH: s.rowH, tier: s.tier, scrollWidth: s.scrollWidth, clientWidth: s.clientWidth, labels: s.labels, overlaps: s.overlaps, zoomLabel: s.zoomLabel, rows: s.rows.length };
    check("Fit puts the whole 3.5-year domain inside the pane", s && s.scrollWidth <= s.clientWidth + 1 && s.dayWidth < 1 && s.dayWidth >= DAY_MIN, JSON.stringify(context.fit));
    check("at that level the axis is years or quarters and no two labels overlap", s && (s.tier === "year" || s.tier === "quarter") && s.labels >= 3 && s.overlaps === 0 && s.weekLabels === 0, JSON.stringify(context.fit));
    check("the rows scaled down with the days: a pitch below 44, every row exactly that pitch, all 44 in view", s && s.rowH < ROW_PX && s.rowH >= ROW_MIN && pitchOk(s) && s.rows.length === total, JSON.stringify({ rowH: s?.rowH, rows: s?.rows.length, tops: s?.rows.slice(0, 3).map((r) => r.top) }));
    const boxOk = (state, epic) => {
      const region = state.regions.find((r) => r.id === epic.id);
      const epicIndex = state.rows.findIndex((r) => r.kind === "epic" && region && Math.abs(r.top - region.top) < 0.01);
      if (!region || epicIndex < 0) return false;
      let last = epicIndex;
      while (state.rows[last + 1]?.kind === "child") last++;
      return Math.abs(state.rows[last].bottom - region.bottom) < 0.01;
    };
    check("the group box still ends on its last child at the small pitch (RADD-1513 holds)", s && boxOk(s, epic1) && boxOk(s, epic2), JSON.stringify(s?.regions));
    check("bars still draw at the small pitch, shorter than the row", s && s.bars.length === total && s.bars.every((b) => b.h >= 2 && b.h < s.rowH), JSON.stringify(s?.bars.slice(0, 2)));
    check("the zoom Select reads the level as a percentage", s && /^\d+%$/.test(s.zoomLabel ?? ""), s?.zoomLabel);
    check("no label cell clips its text at the overview pitch", s && s.rows.every((r) => !r.overflow), JSON.stringify(s?.rows.filter((r) => r.overflow).slice(0, 3)));

    // --- the floor and back ------------------------------------------------------------------------
    for (let i = 0; i < 12; i++) await session.eval(WHEEL(1));
    s = await session.eval(STATE);
    check("ctrl+wheel out reaches the floor: 0.25 px/day, 8 px rows", s && s.dayWidth === DAY_MIN && s.rowH === ROW_MIN && pitchOk(s), JSON.stringify({ dayWidth: s?.dayWidth, rowH: s?.rowH }));
    await session.eval(WHEEL(stepsTo(DAY_MIN, 20)));
    await sleep(200);
    s = await session.eval(STATE);
    check("zooming past the default keeps the comfortable 44 px rows (20 px/day)", s && Math.abs(s.dayWidth - 20) < 0.01 && s.rowH === ROW_PX && s.tier === "month" && s.weekLabels > 0, JSON.stringify({ dayWidth: s?.dayWidth, rowH: s?.rowH, tier: s?.tier }));

    // --- the label tiers ---------------------------------------------------------------------------
    await session.eval(WHEEL(stepsTo(20, 3.5)));
    await sleep(300);
    s = await session.eval(STATE);
    const mini = s?.rows.find((r) => r.kind === "standalone");
    context.mini = s && { dayWidth: s.dayWidth, rowH: s.rowH, fontPx: mini?.fontPx, text: mini?.text, overflow: mini?.overflow };
    check("at 3.5 px/day the rows are 17 px and the label is the mini line: nano text, key + title, nothing clipped", s && s.rowH === 17 && mini && mini.fontPx === 10 && !mini.overflow && /leaf \d\d/.test(mini.text) && s.rows.every((r) => !r.overflow), JSON.stringify(context.mini));
    const epicRow = s?.rows.find((r) => r.kind === "epic");
    check("the epic row keeps its collapse chevron in the mini tier", Boolean(await session.eval(`Boolean(document.querySelector("[data-row-kind='epic'] button[aria-expanded]"))`)) && Boolean(epicRow), JSON.stringify(epicRow));

    // --- a drag at a fractional day width -----------------------------------------------------------
    const leaf = leafItems[10];
    // The bar may sit off-screen either way at this zoom — bring it to the pane's centre first.
    await session.eval(`(() => { document.querySelector("[data-bar-item='${leaf.id}']")?.scrollIntoView({ inline: "center", block: "center" }); return true; })()`);
    await sleep(300);
    const before = await session.eval(BAR_RECT(leaf.id));
    if (before) {
      const x = before.x + before.w / 2;
      const y = before.y + before.h / 2;
      const dx = 35; // 10 days at 3.5 px/day
      await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
      await session.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
      for (let i = 1; i <= 7; i++) {
        await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x + (dx * i) / 7, y, button: "left" });
        await sleep(30);
      }
      await session.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: x + dx, y, button: "left", clickCount: 1 });
      await sleep(400);
    }
    const after = await session.eval(BAR_RECT(leaf.id));
    const save = await session.eval(SAVE);
    context.drag = { before: before?.x, after: after?.x, save };
    check("a 35 px drag at 3.5 px/day commits exactly 10 days (35 px) into the draft", before && after && Math.abs(after.x - before.x - 35) < 0.6 && /Save · 1/.test(save ?? ""), JSON.stringify(context.drag));
    // Undo the move before reloading: a dirty draft arms beforeunload, and headless Chrome's
    // "leave site?" dialog would block Page.navigate for ever.
    await session.eval(`(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true })); return true; })()`);
    await sleep(300);
    const undone = await session.eval(SAVE);
    const restored = await session.eval(BAR_RECT(leaf.id));
    check("Undo reverts the drafted move and the bar returns to its day", /^Saved/.test(undone ?? "") && before && restored && Math.abs(restored.x - before.x) < 0.6, JSON.stringify({ undone, before: before?.x, restored: restored?.x }));

    // --- persistence and the keyboard verb ---------------------------------------------------------
    await session.navigate(url, 3000);
    s = await session.eval(STATE);
    check("a reload restores the zoom (3.5 px/day, 17 px rows)", s && Math.abs(s.dayWidth - 3.5) < 0.01 && s.rowH === 17, JSON.stringify({ dayWidth: s?.dayWidth, rowH: s?.rowH }));
    await session.eval(`(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true })); return true; })()`);
    await sleep(500);
    s = await session.eval(STATE);
    check("A fits the whole timeline from the keyboard", s && s.scrollWidth <= s.clientWidth + 1 && Math.abs(s.dayWidth - context.fit.dayWidth) < 0.01, JSON.stringify({ dayWidth: s?.dayWidth, fit: context.fit?.dayWidth, scrollWidth: s?.scrollWidth, clientWidth: s?.clientWidth }));
    await session.screenshot(outputPath("roadmap-zoom-proof.png"));
  } finally {
    if (projectId) {
      await session.eval(`(async () => { ${PAGE_API} return (await api("DELETE", "/projects/${projectId}")).status; })()`).catch(() => null);
    }
    await close();
  }
  finish(context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
