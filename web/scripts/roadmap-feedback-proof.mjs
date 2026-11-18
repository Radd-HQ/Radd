#!/usr/bin/env node
/**
 * RADD-1504 proof — the roadmap feedback round, measured in a real browser:
 *
 *   RADD-1509  bar info tiers: a 2-day bar draws nothing, a 7-day bar the compact pill
 *              (priority icon + avatar, no title), a 14-day bar the full info
 *   RADD-1511  cycle bands sit at the right x on the axis; Flat hides the epic rows, chips the
 *              parent on every leaf, and survives a reload
 *   RADD-1510  Spread — the one layout verb since RADD-1514 — leaves the epic's bar untouched; ONE
 *              Undo reverts the dates and the order together; it tiles the epic with contiguous bars
 *   RADD-1508  child rows indent ≥ 24px under their epic with a tree guide; the group box is
 *              tinted with the epic's category colour
 *   RADD-1515  the group box border is 2px in the category's ink tier and ≥ 3:1 against the page in both themes
 *   RADD-1513  consecutive rows are exactly ROADMAP_ROW_H apart and the box ends on the last child
 *   RADD-1505  Save writes every child in one request and a reload shows them all; a refused save
 *              stays on the button with the draft intact; PATCH /items is all-or-nothing over HTTP
 *   RADD-1507  a tray drop lands on the axis header, on the empty space below the rows, and on the
 *              label gutter (first visible day)
 *   RADD-1506  a blocks link drawn from a DRAFTED (unsaved) row draws a connector without a reload
 *
 *   node web/scripts/roadmap-feedback-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * Creates a throwaway project (epic + three unscheduled children, three dated leaves, three
 * unscheduled leaves, one two-week cycle, one roadmap view), measures, and deletes the project.
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, sleep } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PORT = 9491;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-roadmap-feedback-proof");
const KEY = `RF${Date.now().toString(36).slice(-4).toUpperCase()}`;
const DAY_PX = 9; // ROADMAP_DAY_WIDTH at the default zoom
const ROW_PX = 44; // ROADMAP_ROW_H

const pad = (n) => String(n).padStart(2, "0");
/** Local calendar date `days` from today — the page's todayIso is local too. */
const iso = (days) => {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const BARS = `(() => Object.fromEntries([...document.querySelectorAll("[data-bar-item]")].map((el) => [
  el.dataset.barItem, {
    info: el.dataset.barInfo, left: parseFloat(el.style.left), width: parseFloat(el.style.width),
    title: Boolean(el.querySelector("[data-bar-title]")), svg: el.querySelectorAll("svg").length,
    avatar: Boolean(el.querySelector("[title^='Assignee:']")),
    borderColor: getComputedStyle(el).borderTopColor,
  },
])))()`;
const ROWS = `(() => [...document.querySelectorAll("[data-row-kind]")].map((el) => ({
  kind: el.dataset.rowKind, keyLeft: el.querySelector("a[title^='Open ']")?.getBoundingClientRect().left ?? null,
  key: el.querySelector("a[title^='Open ']")?.textContent ?? null, chip: el.querySelector("[data-parent-chip]")?.dataset.parentChip ?? null,
})))()`;
const SAVE = `(() => { const b = [...document.querySelectorAll("button")].find((x) => /^Sav/.test(x.textContent || "")); return b ? { text: b.textContent, disabled: b.disabled } : null; })()`;
/** A computed colour as 0–255 rgb + alpha; Chrome reports a color-mix() result as `color(srgb …)`. */
const parseColor = (text) => {
  let m = String(text).match(/^rgba?\(([\d.]+), ([\d.]+), ([\d.]+)(?:, ([\d.]+))?\)$/);
  if (m) return { rgb: [m[1], m[2], m[3]].map((v) => Math.round(Number(v))), a: m[4] === undefined ? 1 : Number(m[4]) };
  m = String(text).match(/^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)$/);
  if (m) return { rgb: [m[1], m[2], m[3]].map((v) => Math.round(Number(v) * 255)), a: m[4] === undefined ? 1 : Number(m[4]) };
  return null;
};
const sameHue = (a, b) => Boolean(a && b) && a.rgb.every((v, i) => Math.abs(v - b.rgb[i]) <= 2);
/** WCAG relative luminance and contrast, with the foreground composited over the page first. */
const luminance = ({ rgb }) => {
  const [r, g, b] = rgb.map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (fg, bg) => {
  if (!fg || !bg) return 0;
  const over = { rgb: fg.rgb.map((v, i) => Math.round(v * fg.a + bg.rgb[i] * (1 - fg.a))), a: 1 };
  const [hi, lo] = [luminance(over), luminance(bg)].sort((x, y) => y - x);
  return +((hi + 0.05) / (lo + 0.05)).toFixed(2);
};
const MENU_ON_EPIC = (id) => `(() => {
  const bar = document.querySelector("[data-bar-item='${id}']");
  const r = bar.getBoundingClientRect();
  bar.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: r.left + 20, clientY: r.top + r.height / 2, button: 2 }));
  return true;
})()`;

async function main() {
  const { session, close, baseUrl, finish, check } = await startProof({ port: PORT, profile: PROFILE, width: 1600, height: 1000 });
  const context = { key: KEY };
  let projectId = null;
  let cycleId = null;
  try {
    // --- setup -------------------------------------------------------------------------------
    const setup = await session.eval(`(async () => { ${PAGE_API}
      const me = (await api("GET", "/auth/me")).body;
      const project = (await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Roadmap feedback proof" })).body;
      const item = async (body) => (await api("POST", "/items", { project_id: project.id, ...body })).body;
      const epic = await item({ title: "Epic", kind: "epic", start_date: "${iso(-10)}", target_date: "${iso(20)}" });
      const c1 = await item({ title: "child one", parent_id: epic.id });
      const c2 = await item({ title: "child two", parent_id: epic.id });
      const c3 = await item({ title: "child three", parent_id: epic.id });
      const s2 = await item({ title: "two days", start_date: "${iso(1)}", target_date: "${iso(2)}" });
      const s7 = await item({ title: "one week", start_date: "${iso(3)}", target_date: "${iso(9)}", assignee_id: me.id });
      const s14 = await item({ title: "two weeks", start_date: "${iso(-5)}", target_date: "${iso(8)}" });
      const u1 = await item({ title: "drop header" });
      const u2 = await item({ title: "drop below" });
      const u3 = await item({ title: "drop gutter" });
      const cycle = (await api("POST", "/cycles", { name: "Sprint 1", project_id: project.id, start_date: "${iso(-3)}", end_date: "${iso(10)}" })).body;
      const view = (await api("POST", "/views", { project_id: project.id, name: "Feedback roadmap", view_type: "roadmap" })).body;
      return { project, epic, c1, c2, c3, s2, s7, s14, u1, u2, u3, cycle, view };
    })()`);
    const { project, epic, c1, c2, c3, s2, s7, s14, u1, u2, u3, cycle, view } = setup;
    projectId = project.id;
    cycleId = cycle?.id ?? null;
    check("setup created the project, items, cycle and view", Boolean(project?.id && epic?.id && cycle?.id && view?.id), JSON.stringify({ project: project?.id, epic: epic?.id, cycle: cycle?.id, view: view?.id }));
    const url = `${baseUrl}/p/${KEY}/v/${view.id}`;
    await session.navigate(url, 3000);

    // --- RADD-1509: bar tiers ----------------------------------------------------------------
    let bars = await session.eval(BARS);
    context.tiers = { s2: bars[s2.id], s7: bars[s7.id], s14: bars[s14.id] };
    check("a 2-day bar (18px) draws nothing", bars[s2.id]?.info === "none" && bars[s2.id].svg === 0 && !bars[s2.id].title, JSON.stringify(bars[s2.id]));
    check("a 7-day bar (63px) draws the compact pill: icon + avatar, no title", bars[s7.id]?.info === "compact" && bars[s7.id].svg >= 1 && bars[s7.id].avatar && !bars[s7.id].title, JSON.stringify(bars[s7.id]));
    check("a 14-day bar (126px) draws the full info with the title", bars[s14.id]?.info === "full" && bars[s14.id].title, JSON.stringify(bars[s14.id]));

    // --- RADD-1511: cycle bands --------------------------------------------------------------
    const band = await session.eval(`(() => {
      const band = document.querySelector("[data-cycle-band='${cycle.id}']");
      const today = document.querySelector("[title='Today']");
      const body = document.querySelector("[data-cycle-band-body='${cycle.id}']");
      return band && today ? { left: parseFloat(band.style.left), width: parseFloat(band.style.width), todayLeft: parseFloat(today.style.left), text: band.textContent, body: Boolean(body) } : null;
    })()`);
    context.band = band;
    check("the cycle band spans 14 day columns, labelled, with a body band", band && band.width === 14 * DAY_PX && band.text === "Sprint 1" && band.body, JSON.stringify(band));
    check("the cycle band starts 3 days before the today line", band && band.todayLeft - band.left === 3 * DAY_PX, JSON.stringify(band));

    // --- RADD-1510 / RADD-1514: Spread is the one layout verb; it never touches the epic; one Undo
    const epicWidthBefore = bars[epic.id]?.width;
    await session.eval(MENU_ON_EPIC(epic.id));
    await sleep(300);
    const verbs = await session.eval(`[...document.querySelectorAll("button")].map((b) => b.textContent || "").filter((t) => /children|Fit to/.test(t))`);
    context.verbs = verbs;
    check("the epic menu offers Spread and Bring-in, and nothing named auto-schedule", verbs.some((t) => t.includes("Spread children across the epic")) && verbs.some((t) => t.includes("Bring children into roadmap")) && !verbs.some((t) => /auto-?schedule/i.test(t)), JSON.stringify(verbs));
    await session.click("button", (t) => t.includes("Spread children across the epic"));
    await sleep(1500);
    let rows = await session.eval(ROWS);
    bars = await session.eval(BARS);
    context.afterSpread = { rows: rows.map((r) => [r.kind, r.key]), epicWidth: bars[epic.id]?.width, before: epicWidthBefore };
    check("spread drafted the three children in as child rows", rows.filter((r) => r.kind === "child").length === 3, JSON.stringify(rows.map((r) => r.kind)));
    check("spread left the epic's bar untouched", bars[epic.id]?.width === epicWidthBefore && epicWidthBefore === 31 * DAY_PX, `${epicWidthBefore} → ${bars[epic.id]?.width}`);
    const save = await session.eval(SAVE);
    check("the draft counts the three children, not the epic", save?.text === "Save · 3", JSON.stringify(save));
    await session.click("button[aria-label='Undo']");
    await sleep(300);
    rows = await session.eval(ROWS);
    const undo = await session.eval(`(() => ({ undo: document.querySelector("button[aria-label='Undo']").disabled, redo: document.querySelector("button[aria-label='Redo']").disabled }))()`);
    check("ONE Undo reverts the plan entirely (dates and order): no child rows, nothing left to undo", rows.filter((r) => r.kind === "child").length === 0 && undo.undo === true && undo.redo === false, JSON.stringify({ rows: rows.length, ...undo }));
    await session.click("button[aria-label='Redo']");
    await sleep(300);

    // --- RADD-1508: indent + tree guide + tint ------------------------------------------------
    rows = await session.eval(ROWS);
    const epicRow = rows.find((r) => r.kind === "epic");
    const childRows = rows.filter((r) => r.kind === "child");
    const indent = epicRow && childRows.length ? childRows[0].keyLeft - epicRow.keyLeft : null;
    context.indent = indent;
    check("a child's key sits at least 24px right of its epic's", indent !== null && indent >= 24, `indent ${indent}px`);
    const guide = await session.eval(`(() => { const g = [...document.querySelectorAll("[data-tree-guide]")]; return { count: g.length, border: g[0] ? getComputedStyle(g[0]).borderLeftWidth : null, height: g[0] ? g[0].getBoundingClientRect().height : null }; })()`);
    check("every child row carries a 1px tree guide the full row height", guide.count === 3 && guide.border === "1px" && guide.height >= 40, JSON.stringify(guide));
    const tint = await session.eval(`(() => {
      const region = document.querySelector("[data-epic-region='${epic.id}']");
      if (!region) return null;
      const s = getComputedStyle(region);
      const bar = getComputedStyle(document.querySelector("[data-bar-item='${epic.id}']"));
      return { bg: s.backgroundColor, border: s.borderTopColor, barBorder: bar.borderTopColor, barFill: bar.backgroundColor };
    })()`);
    context.tint = tint;
    const regionBg = parseColor(tint?.bg);
    const barBorder = parseColor(tint?.barBorder);
    const barFill = parseColor(tint?.barFill);
    check("the epic's group box is tinted with the epic bar's own colour at a visible alpha", sameHue(regionBg, barBorder) && regionBg.a > 0.08 && regionBg.a < 0.2, JSON.stringify(tint));
    check("the epic bar itself has a translucent fill of its category colour (the hex-alpha-on-a-token bug)", sameHue(barFill, barBorder) && barFill.a > 0.1 && barFill.a < 0.3, JSON.stringify(tint));

    // --- RADD-1515: the box border is 2px in the epic's hue and reads in BOTH themes ----------
    const BORDER = `(() => {
      const s = getComputedStyle(document.querySelector("[data-epic-region='${epic.id}']"));
      const bodyBg = getComputedStyle(document.body).backgroundColor;
      const page = bodyBg === "rgba(0, 0, 0, 0)" ? getComputedStyle(document.documentElement).backgroundColor : bodyBg;
      return { width: s.borderTopWidth, color: s.borderTopColor, page, light: document.documentElement.classList.contains("light") };
    })()`;
    const darkBorder = await session.eval(BORDER);
    await session.eval(`document.documentElement.classList.add("light")`);
    await sleep(300);
    const lightBorder = await session.eval(BORDER);
    await session.eval(`document.documentElement.classList.remove("light")`);
    await sleep(300);
    const ratio = (m) => contrast(parseColor(m.color), parseColor(m.page));
    context.border = { dark: { ...darkBorder, ratio: ratio(darkBorder) }, light: { ...lightBorder, ratio: ratio(lightBorder) } };
    const chroma = (c) => (c ? Math.max(...c.rgb) - Math.min(...c.rgb) : 0);
    check("the group box border is 2px and chromatic — the category's ink tier, not the grid's grey", darkBorder.width === "2px" && chroma(parseColor(darkBorder.color)) > 40 && chroma(parseColor(lightBorder.color)) > 40, JSON.stringify(context.border));
    check("the group box border reads against the page at ≥ 3:1 in dark AND in light", !darkBorder.light && lightBorder.light && ratio(darkBorder) >= 3 && ratio(lightBorder) >= 3, JSON.stringify(context.border));

    // --- RADD-1513: the row grid is exact — rows ROADMAP_ROW_H apart, box ends on the last child
    const grid = await session.eval(`(() => {
      const cells = [...document.querySelectorAll("[data-row-kind]")];
      const roots = cells.map((el) => el.parentElement.getBoundingClientRect());
      const kinds = cells.map((el) => el.dataset.rowKind);
      const pitches = [...new Set(roots.slice(1).map((r, i) => +(r.top - roots[i].top).toFixed(2)))];
      const region = document.querySelector("[data-epic-region='${epic.id}']")?.getBoundingClientRect() ?? null;
      const epicAt = kinds.indexOf("epic");
      const lastChildAt = kinds.lastIndexOf("child");
      return { pitches, regionTop: region?.top ?? null, regionBottom: region?.bottom ?? null, epicTop: roots[epicAt]?.top ?? null, lastChildBottom: roots[lastChildAt]?.bottom ?? null };
    })()`);
    context.grid = grid;
    check("consecutive rows are exactly ROADMAP_ROW_H apart (the separator lives inside the row)", grid.pitches.length === 1 && grid.pitches[0] === ROW_PX, JSON.stringify(grid));
    check("the group box starts on its epic row and ends on its last child row", grid.regionTop !== null && Math.abs(grid.regionTop - grid.epicTop) < 0.5 && Math.abs(grid.regionBottom - grid.lastChildBottom) < 0.5, JSON.stringify(grid));

    // --- RADD-1510: spread tiles the epic ----------------------------------------------------
    await session.eval(MENU_ON_EPIC(epic.id));
    await sleep(300);
    await session.click("button", (t) => t.includes("Spread children across the epic"));
    await sleep(1200);
    bars = await session.eval(BARS);
    const spread = [c1, c2, c3].map((c) => bars[c.id]).filter(Boolean).sort((a, b) => a.left - b.left);
    const epicBar = bars[epic.id];
    const contiguous = spread.length === 3 && spread.every((b, i) => i === 0 || b.left === spread[i - 1].left + spread[i - 1].width);
    context.spread = { spread, epic: epicBar };
    check("spread tiles the epic: first child starts with it, last ends with it, no gaps", contiguous && spread[0].left === epicBar.left && spread[2].left + spread[2].width === epicBar.left + epicBar.width, JSON.stringify(context.spread));
    await session.click("button[aria-label='Undo']");
    await sleep(300);

    // --- RADD-1505: one request, all written, a reload shows everything ----------------------
    await session.click("button", (t) => /^Save ·/.test(t));
    let saved = null;
    for (let i = 0; i < 40 && !(saved?.text === "Saved"); i++) { await sleep(250); saved = await session.eval(SAVE); }
    const saveError = await session.eval(`document.querySelector("[data-save-error]")?.textContent ?? null`);
    check("Save completes without a refusal", saved?.text === "Saved" && saveError === null, JSON.stringify({ saved, saveError }));
    const readBack = await session.eval(`(async () => { ${PAGE_API}
      const get = async (id) => (await api("GET", "/items/" + id)).body;
      const [e, a, b, c] = await Promise.all([get("${epic.id}"), get("${c1.id}"), get("${c2.id}"), get("${c3.id}")]);
      return { epic: [e.start_date, e.target_date], children: [a, b, c].map((x) => [x.start_date, x.target_date]) };
    })()`);
    context.readBack = readBack;
    check("every child has dates on the server and the epic's dates are unchanged", readBack.children.every((d) => d[0] && d[1]) && readBack.epic[0] === iso(-10) && readBack.epic[1] === iso(20), JSON.stringify(readBack));
    await session.navigate(url, 3000);
    rows = await session.eval(ROWS);
    bars = await session.eval(BARS);
    check("after a reload all three children are rows under the epic, which kept its bar", rows.filter((r) => r.kind === "child").length === 3 && bars[epic.id]?.width === 31 * DAY_PX, JSON.stringify({ kinds: rows.map((r) => r.kind), epic: bars[epic.id] }));
    await session.screenshot(outputPath("roadmap-feedback-proof.png"));

    // --- RADD-1507: drops anywhere -----------------------------------------------------------
    const geometry = await session.eval(`(() => {
      const root = document.querySelector("[data-roadmap-timeline]").getBoundingClientRect();
      const pane = document.querySelector("[data-roadmap-timeline]").parentElement;
      const header = document.querySelector("[data-roadmap-timeline] > div.sticky").getBoundingClientRect();
      const rowRects = [...document.querySelectorAll("[data-row-kind]")].map((el) => el.getBoundingClientRect());
      const label = rowRects[0];
      return { rootLeft: root.left, rootBottom: root.bottom, paneLeft: pane.getBoundingClientRect().left, paneBottom: pane.getBoundingClientRect().bottom,
        scrollLeft: pane.scrollLeft, headerTop: header.top, headerBottom: header.bottom, rowsBottom: Math.max(...rowRects.map((r) => r.bottom)), labelWidth: label.width };
    })()`);
    context.geometry = geometry;
    const dropAt = async (item, x, y) => {
      await session.eval(`(() => {
        const card = document.querySelector("[data-tray-item='${item.key}']");
        const dt = new DataTransfer();
        card.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: dt }));
        window.__proofDt = dt;
      })()`);
      await sleep(150);
      // The pane can re-anchor on today between drops (a drop that widens the
      // domain re-runs the anchor), so the expectation reads the geometry AT
      // the drop: the root's left (layout x) and the pane's scrollLeft.
      return session.eval(`(() => {
        const dt = window.__proofDt;
        const root = document.querySelector("[data-roadmap-timeline]");
        const pane = root.parentElement;
        const rootLeft = root.getBoundingClientRect().left;
        const scrollLeft = pane.scrollLeft;
        // A drop earlier than every bar re-pads the domain and shifts every
        // index, so positions are compared RELATIVE to the today line.
        const todayLeft = parseFloat(document.querySelector("[title='Today']").style.left);
        const target = document.elementFromPoint(${x}, ${y});
        const init = { bubbles: true, cancelable: true, dataTransfer: dt, clientX: ${x}, clientY: ${y} };
        const over = new DragEvent("dragover", init);
        target.dispatchEvent(over);
        const accepted = over.defaultPrevented;
        target.dispatchEvent(new DragEvent("drop", init));
        document.querySelector("[data-tray-item='${item.key}']")?.dispatchEvent(new DragEvent("dragend", { bubbles: true, cancelable: true, dataTransfer: dt }));
        return { accepted, target: target.tagName + "." + String(target.className).slice(0, 40), rootLeft, scrollLeft, todayLeft };
      })()`);
    };
    const TODAY_LEFT = `parseFloat(document.querySelector("[title='Today']").style.left)`;
    /** Days from today the drop should land on, from the drop-time geometry. */
    const expectOffset = (drop, x) => Math.floor((x - drop.rootLeft - geometry.labelWidth) / DAY_PX) - drop.todayLeft / DAY_PX;
    /** Days from today the new bar actually sits at, in the post-drop domain. */
    const actualOffset = async (item) => {
      bars = await session.eval(BARS);
      const todayLeft = await session.eval(TODAY_LEFT);
      return bars[item.id] ? (bars[item.id].left - todayLeft) / DAY_PX : null;
    };
    const headerX = geometry.paneLeft + geometry.labelWidth + 300;
    const headerDrop = await dropAt(u1, headerX, (geometry.headerTop + geometry.headerBottom) / 2);
    await sleep(400);
    context.headerDrop = { ...headerDrop, expected: expectOffset(headerDrop, headerX), actual: await actualOffset(u1) };
    check("a drop on the axis header schedules the item at the day under the pointer", headerDrop.accepted && context.headerDrop.actual === context.headerDrop.expected, JSON.stringify(context.headerDrop));
    const belowY = geometry.rowsBottom + 120;
    const belowX = geometry.paneLeft + geometry.labelWidth + 420;
    check("there is open pane below the rows to drop into", belowY < geometry.paneBottom - 10 && belowY < geometry.rootBottom, JSON.stringify({ belowY, rootBottom: geometry.rootBottom, paneBottom: geometry.paneBottom }));
    const belowDrop = await dropAt(u2, belowX, belowY);
    await sleep(400);
    context.belowDrop = { ...belowDrop, expected: expectOffset(belowDrop, belowX), actual: await actualOffset(u2) };
    check("a drop on the empty space below the rows schedules the item at the day under the pointer", belowDrop.accepted && context.belowDrop.actual === context.belowDrop.expected, JSON.stringify(context.belowDrop));
    const gutterDrop = await dropAt(u3, geometry.paneLeft + 40, belowY + 44);
    await sleep(400);
    const firstVisibleOffset = Math.floor(gutterDrop.scrollLeft / DAY_PX) - gutterDrop.todayLeft / DAY_PX;
    context.gutterDrop = { ...gutterDrop, expected: firstVisibleOffset, actual: await actualOffset(u3) };
    check("a drop on the label gutter schedules the item at the first visible day", gutterDrop.accepted && context.gutterDrop.actual === firstVisibleOffset, JSON.stringify(context.gutterDrop));

    // --- RADD-1506: a link from a drafted row draws without reload ---------------------------
    const edgesBefore = await session.eval(`document.querySelectorAll("[data-roadmap-connectors] path").length`);
    const linked = await session.eval(`(async () => { ${PAGE_API} return (await api("POST", "/items/${u1.id}/links", { target_id: "${s14.id}", link_type: "blocks" })).status; })()`);
    let edgesAfter = edgesBefore;
    for (let i = 0; i < 20 && edgesAfter <= edgesBefore; i++) { await sleep(250); edgesAfter = await session.eval(`document.querySelectorAll("[data-roadmap-connectors] path").length`); }
    context.link = { linked, edgesBefore, edgesAfter };
    check("a blocks link from the drafted (unsaved) row draws a connector without a reload", linked === 201 && edgesBefore === 0 && edgesAfter > 0, JSON.stringify(context.link));

    // --- RADD-1505: a refused save stays on the button; the draft stays ----------------------
    const deleted = await session.eval(`(async () => { ${PAGE_API} return (await api("DELETE", "/items/${u3.id}")).status; })()`);
    await session.click("button", (t) => /^Save ·/.test(t));
    let refusal = null;
    for (let i = 0; i < 40 && refusal === null; i++) { await sleep(250); refusal = await session.eval(`document.querySelector("[data-save-error]")?.textContent ?? null`); }
    const afterRefusal = await session.eval(SAVE);
    context.refusal = { deleted, refusal, afterRefusal };
    check("a refused save shows the reason beside the button and keeps the draft dirty", deleted === 204 && typeof refusal === "string" && /not found/i.test(refusal) && /^Save · \d/.test(afterRefusal?.text ?? "") && afterRefusal.disabled === false, JSON.stringify(context.refusal));
    const http = await session.eval(`(async () => { ${PAGE_API}
      const r = await api("PATCH", "/items", { patches: [
        { item_id: "${s2.id}", patch: { start_date: "${iso(30)}", target_date: "${iso(31)}" } },
        { item_id: "${s7.id}", patch: { start_date: "${iso(5)}", target_date: "${iso(1)}" } },
      ] });
      const s2 = (await api("GET", "/items/${s2.id}")).body;
      return { status: r.status, detail: r.body?.detail, s2Start: s2.start_date };
    })()`);
    context.http = http;
    check("PATCH /items is all-or-nothing: an inverted span on the 2nd item refuses with its key and leaves the 1st unwritten", http.status === 409 && String(http.detail).startsWith(`${s7.key}: `) && http.s2Start === iso(1), JSON.stringify(http));
    // Discard the refused draft (toolbar Discard → the dialog's Discard).
    await session.click("button", (t) => t.trim() === "Discard");
    await sleep(300);
    await session.click("[role='dialog'] button", (t) => t.trim() === "Discard");
    await sleep(400);
    const afterDiscard = await session.eval(SAVE);
    check("Discard clears the refused draft", afterDiscard?.text === "Saved", JSON.stringify(afterDiscard));

    // --- RADD-1511: Flat ---------------------------------------------------------------------
    await session.click("button", (t) => t.trim() === "Flat");
    await sleep(400);
    rows = await session.eval(ROWS);
    context.flat = rows.map((r) => [r.kind, r.key, r.chip]);
    check("Flat hides the epic row and lists every scheduled leaf standalone, children chipped with the epic", rows.every((r) => r.kind === "standalone") && rows.length === 6 && rows.filter((r) => r.chip === epic.key).length === 3, JSON.stringify(context.flat));
    await session.navigate(url, 3000);
    rows = await session.eval(ROWS);
    const flatPressed = await session.eval(`[...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Flat")?.getAttribute("aria-pressed")`);
    check("Flat survives a reload", flatPressed === "true" && rows.every((r) => r.kind === "standalone") && rows.length === 6, JSON.stringify({ flatPressed, kinds: rows.map((r) => r.kind) }));
    await session.click("button", (t) => t.trim() === "Flat");
    await sleep(400);
    rows = await session.eval(ROWS);
    check("Flat off restores the epic group", rows.filter((r) => r.kind === "epic").length === 1 && rows.filter((r) => r.kind === "child").length === 3, JSON.stringify(rows.map((r) => r.kind)));
  } finally {
    // The cycle is not deleted with its project (it is homed there, not owned), so drop it first.
    if (cycleId) {
      await session.eval(`(async () => { ${PAGE_API} return (await api("DELETE", "/cycles/${cycleId}")).status; })()`).catch(() => null);
    }
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
