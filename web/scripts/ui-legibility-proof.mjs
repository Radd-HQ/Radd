#!/usr/bin/env node
/**
 * RADD-1516 proof — the UI legibility round, measured in a real browser:
 *
 *   RADD-1517  the dark ramp separates: panel/page ≥ 1.12, subtle border/page ≥ 1.7, strong/page ≥ 2.4,
 *              every state colour ≥ 3:1 on panel and elevated, body text ≥ 10:1; light untouched; the
 *              cycle page's status boxes are framed in the strong border
 *   RADD-1518  one type ladder: a row title is 14px, its key 12px, a text-xs label 13px — identical
 *              under html.light and dark
 *   RADD-1519  every row leads kind · priority · key · title (cycle page, list, planning, board card),
 *              the priority is a 16px icon with no label text in the row, the key sits in secondary ink
 *
 *   node web/scripts/ui-legibility-proof.mjs http://127.0.0.1:8001 admin@example.com change-me
 *
 * Creates a throwaway project (one issue per priority, one flagged, a cycle holding them, list +
 * planning + board views), measures, deletes the cycle then the project.
 */
import { resolve } from "node:path";
import { PAGE_API, report, sleep } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PORT = 9502;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ui-legibility-proof");
const KEY = `UL${Date.now().toString(36).slice(-4).toUpperCase()}`;

/** A computed colour (rgb / color(srgb); tokens come back as hex, 3 or 6 digits) as 0–255. */
const parseColor = (text) => {
  let m = String(text).trim().match(/^#([0-9a-f]{6})$/i);
  if (m) return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
  m = String(text).trim().match(/^#([0-9a-f]{3})$/i); // the light panel resolves as #fff
  if (m) return [...m[1]].map((c) => parseInt(c + c, 16));
  m = String(text).match(/^rgba?\(([\d.]+), ([\d.]+), ([\d.]+)/);
  if (m) return [m[1], m[2], m[3]].map((v) => Math.round(Number(v)));
  m = String(text).match(/^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)/);
  if (m) return [m[1], m[2], m[3]].map((v) => Math.round(Number(v) * 255));
  return null;
};
const luminance = (rgb) => {
  const [r, g, b] = rgb.map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  if (!a || !b) return 0;
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return +((hi + 0.05) / (lo + 0.05)).toFixed(2);
};
const same = (a, b) => Boolean(a && b) && a.every((v, i) => Math.abs(v - b[i]) <= 1);

/** The theme's tokens as the page resolves them right now. */
const TOKENS = `(() => {
  const s = getComputedStyle(document.documentElement);
  const read = (name) => s.getPropertyValue(name).trim();
  return { light: document.documentElement.classList.contains("light"),
    base: read("--color-zinc-950"), surface: read("--color-zinc-900"), elevated: read("--color-zinc-850"), overlay: read("--color-zinc-825"),
    subtle: read("--color-zinc-800"), strong: read("--color-zinc-700"), emphasis: read("--color-zinc-600"), muted: read("--color-zinc-500"),
    secondary: read("--color-zinc-400"), fg: read("--color-zinc-200"), heading: read("--color-zinc-100"),
    triage: read("--chart-triage"), backlog: read("--chart-backlog"), todo: read("--chart-todo"), progress: read("--chart-progress"), done: read("--chart-done") };
})()`;

/** The first item row on the page: its lead's x-order, sizes and colours. */
const ROW = `(() => {
  const keyEl = document.querySelector("main a[title^='Open ']");
  if (!keyEl) return null;
  let row = keyEl;
  while (row.parentElement && !(row.querySelector("span[title^='Priority:']") && row.querySelector("a[title^='Open ']") && row.matches("li, [role=row], article, div"))) row = row.parentElement;
  const x = (el) => (el ? Math.round(el.getBoundingClientRect().left) : null);
  const kind = row.querySelector("span[title='Issue'] svg, span[title='Epic'] svg, span[title='Subtask'] svg, span[title^='Type:']");
  const prio = row.querySelector("span[title^='Priority:'] svg");
  const key = row.querySelector("a[title^='Open ']");
  const title = [...row.querySelectorAll("span, p")].find((el) => el.childElementCount === 0 && (el.textContent || "").trim().length > 12 && !/^(Priority|Type):/.test(el.getAttribute("title") || ""));
  const labelWords = [...row.querySelectorAll("span")].filter((el) => el.childElementCount === 0 && /^(Blocker|High|Normal|Low)$/.test((el.textContent || "").trim())).length;
  const xs = [...row.querySelectorAll(".text-xs")].map((el) => getComputedStyle(el).fontSize)[0] ?? null;
  return {
    order: { kind: x(kind), priority: x(prio), key: x(key), title: x(title) },
    priorityPx: prio ? Math.round(prio.getBoundingClientRect().width) : null,
    keyPx: key ? getComputedStyle(key).fontSize : null, keyColor: key ? getComputedStyle(key).color : null,
    titlePx: title ? getComputedStyle(title).fontSize : null, titleText: title ? title.textContent.trim().slice(0, 30) : null,
    xsPx: xs, labelWords,
  };
})()`;

const ordered = (o) => o && [o.kind, o.priority, o.key, o.title].every((v) => v !== null) && o.kind < o.priority && o.priority < o.key && o.key < o.title;

async function main() {
  const { session, close, baseUrl, finish, check } = await startProof({ port: PORT, profile: PROFILE, width: 1500, height: 900 });
  const context = { key: KEY };
  let projectId = null;
  let cycleId = null;
  try {
    // --- setup -------------------------------------------------------------------------------
    const setup = await session.eval(`(async () => { ${PAGE_API}
      const project = (await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "UI legibility proof" })).body;
      const cycle = (await api("POST", "/cycles", { name: "Sprint L", project_id: project.id, start_date: "2026-10-19", end_date: "2026-11-01" })).body;
      const item = async (body) => (await api("POST", "/items", { project_id: project.id, cycle_id: cycle.id, ...body })).body;
      const items = [];
      items.push(await item({ title: "A blocker that stops the pipeline cold", priority: "blocker", flagged: true }));
      items.push(await item({ title: "A high priority task with a long title", priority: "high" }));
      items.push(await item({ title: "A normal priority task with a long title", priority: "normal" }));
      items.push(await item({ title: "A low priority task with a long title", priority: "low" }));
      const view = async (view_type, name) => (await api("POST", "/views", { project_id: project.id, name, view_type })).body;
      return { project, cycle, items, list: await view("list", "List L"), planning: await view("planning", "Planning L"), board: await view("board", "Board L") };
    })()`);
    const { project, cycle, items, list, planning, board } = setup;
    projectId = project?.id ?? null;
    cycleId = cycle?.id ?? null;
    check("setup created the project, cycle, items and views", Boolean(projectId && cycleId && items?.length === 4 && list?.id && planning?.id && board?.id), JSON.stringify({ projectId, cycleId, items: items?.length, list: list?.id, planning: planning?.id, board: board?.id }));

    // --- RADD-1517: the dark ramp, read as the page resolves it -------------------------------
    await session.navigate(`${baseUrl}/cycles/${cycleId}`, 3000);
    const dark = await session.eval(TOKENS);
    const t = Object.fromEntries(Object.entries(dark).map(([k, v]) => [k, typeof v === "string" ? parseColor(v) : v]));
    const ratios = {
      panel: contrast(t.surface, t.base), elevated: contrast(t.elevated, t.surface), subtle: contrast(t.subtle, t.base), strong: contrast(t.strong, t.base),
      body: contrast(t.fg, t.surface), muted: contrast(t.muted, t.surface),
      states: Object.fromEntries(["triage", "backlog", "todo", "progress", "done"].map((k) => [k, [contrast(t[k], t.surface), contrast(t[k], t.elevated)]])),
    };
    context.dark = { tokens: dark, ratios };
    check("dark: panels and elevated surfaces step up from the page by ≥ 1.12", !dark.light && ratios.panel >= 1.12 && ratios.elevated >= 1.12, JSON.stringify(ratios));
    check("dark: the subtle border is ≥ 1.7:1 and the strong border ≥ 2.4:1 on the page", ratios.subtle >= 1.7 && ratios.strong >= 2.4, JSON.stringify(ratios));
    check("dark: every state colour is ≥ 3:1 on the panel and on the elevated surface", Object.values(ratios.states).every(([a, b]) => a >= 3 && b >= 3), JSON.stringify(ratios.states));
    check("dark: body text is still ≥ 10:1 and muted text ≥ 5:1 on a panel", ratios.body >= 10 && ratios.muted >= 5, JSON.stringify(ratios));
    const box = await session.eval(`(() => { const ul = document.querySelector("main ul"); return ul ? getComputedStyle(ul).borderTopColor : null; })()`);
    context.box = box;
    check("the cycle page's status boxes are framed in the strong border", same(parseColor(box), t.strong), `${box} vs strong ${dark.strong}`);
    await session.eval(`document.documentElement.classList.add("light")`);
    await sleep(300);
    const light = await session.eval(TOKENS);
    const l = Object.fromEntries(Object.entries(light).map(([k, v]) => [k, typeof v === "string" ? parseColor(v) : v]));
    const lightRatios = { subtle: contrast(l.subtle, l.base), strong: contrast(l.strong, l.base), body: contrast(l.fg, l.surface) };
    context.light = { tokens: light, ratios: lightRatios };
    check("light is untouched: subtle 1.15, strong 1.35, body 14.1 on white (± 0.05)", light.light && Math.abs(lightRatios.subtle - 1.15) < 0.05 && Math.abs(lightRatios.strong - 1.35) < 0.05 && Math.abs(lightRatios.body - 14.11) < 0.05, JSON.stringify(lightRatios));
    await session.eval(`document.documentElement.classList.remove("light")`);
    await sleep(200);

    // --- RADD-1519 + RADD-1518 on the cycle page --------------------------------------------
    const cycleRow = await session.eval(ROW);
    context.cycleRow = cycleRow;
    check("cycle page row: kind · priority · key · title, left to right", ordered(cycleRow?.order), JSON.stringify(cycleRow?.order));
    check("cycle page row: the priority is a 16px icon and no priority word appears in the row", cycleRow?.priorityPx === 16 && cycleRow.labelWords === 0, JSON.stringify({ px: cycleRow?.priorityPx, words: cycleRow?.labelWords }));
    check("cycle page row: the title is 14px and the key 12px in secondary ink", cycleRow?.titlePx === "14px" && cycleRow.keyPx === "12px" && same(parseColor(cycleRow.keyColor), t.secondary), JSON.stringify({ title: cycleRow?.titlePx, key: cycleRow?.keyPx, color: cycleRow?.keyColor, secondary: dark.secondary }));

    // --- list view, both themes ---------------------------------------------------------------
    await session.navigate(`${baseUrl}/p/${KEY}/v/${list.id}`, 3000);
    const listRow = await session.eval(ROW);
    context.listRow = listRow;
    check("list row: kind · priority · key · title, left to right", ordered(listRow?.order), JSON.stringify(listRow?.order));
    check("list row: 16px priority icon, no priority word, 14px title, 12px key, 13px text-xs label", listRow?.priorityPx === 16 && listRow.labelWords === 0 && listRow.titlePx === "14px" && listRow.keyPx === "12px" && listRow.xsPx === "13px", JSON.stringify(listRow));
    await session.eval(`document.documentElement.classList.add("light")`);
    await sleep(300);
    const listRowLight = await session.eval(ROW);
    context.listRowLight = listRowLight;
    check("the same sizes under html.light: the ladder does not differ by palette", listRowLight?.titlePx === "14px" && listRowLight.keyPx === "12px" && listRowLight.xsPx === "13px" && listRowLight.priorityPx === 16, JSON.stringify(listRowLight));
    await session.eval(`document.documentElement.classList.remove("light")`);

    // --- planning view ------------------------------------------------------------------------
    await session.navigate(`${baseUrl}/p/${KEY}/v/${planning.id}`, 3000);
    const planRow = await session.eval(ROW);
    context.planRow = planRow;
    check("planning row: kind · priority · key · title, 16px icon, no priority word", ordered(planRow?.order) && planRow.priorityPx === 16 && planRow.labelWords === 0, JSON.stringify(planRow));

    // --- board card header --------------------------------------------------------------------
    await session.navigate(`${baseUrl}/p/${KEY}/v/${board.id}`, 3000);
    const card = await session.eval(ROW);
    context.card = card;
    check("board card header: kind-or-type · priority · key, then the title below or beside", Boolean(card?.order) && card.order.kind !== null && card.order.priority !== null && card.order.key !== null && card.order.kind < card.order.priority && card.order.priority < card.order.key && card.priorityPx === 16, JSON.stringify(card?.order));

    await session.screenshot("/tmp/ui-legibility-proof.png");
  } finally {
    if (projectId) {
      await session.eval(`(async () => { ${PAGE_API}
        ${cycleId ? `await api("DELETE", "/cycles/${cycleId}");` : ""}
        return (await api("DELETE", "/projects/${projectId}")).status; })()`).catch(() => undefined);
    }
    await close();
  }
  finish(context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
