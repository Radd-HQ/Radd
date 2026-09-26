/**
 * Browser proof for RADD-1394: the SLA timers on lists, board cards and the issue rail are the
 * slas plugin's — contributed through the SDK's item attribute (column + card cell) and the
 * issue.panel.section slot, drawn by /plugins/slas/, with the host holding no SLA code at all.
 * Against the REAL backend:
 *
 *   1. over REST: a throwaway project, two ENABLED policies with long targets (nothing breaches
 *      or warns while the proof runs, so a worker elsewhere has nothing to do), three issues —
 *      one per policy and one no policy matches — and a list view with the `slas.timer` column
 *      and a board view whose card layout places the cell;
 *   2. the list's SLA cells and the board's SLA cells show exactly the timers a direct
 *      POST /items/sla/batch returns (the nearest-to-breach chip, ±1 minute of clock), the
 *      unmatched issue shows the dash / no cell, and the page asked the batch endpoint;
 *   3. the issue rail's SLA section equals GET /items/{id}/sla;
 *   4. the chips came from the remote: /plugins/slas/remoteEntry.js was loaded, and only the
 *      remote's bundle carries the `data-sla-cell` hook — the host bundle has none;
 *   5. no console errors; the views and the project are deleted again (issues and policies cascade).
 *
 * Usage (from web/): node scripts/sla-columns-proof.mjs <baseUrl> [email] [password]
 * The backend must come from this checkout (it serves web/dist and the plugin remotes).
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8114", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9514;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-sla-columns-proof-profile");
const HERE = dirname(fileURLToPath(import.meta.url));
const key = `SC${Date.now().toString(36).slice(-4).toUpperCase()}`;

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

/** The chip the remote must draw for a batch entry — its own rules, restated as the oracle. */
function expectedChip(timers) {
  if (!timers?.length) return null;
  const urgency = (t) => (t.breached && !t.met_at ? 0 : t.remaining_seconds !== null ? 1 : t.paused ? 2 : t.met_at && t.breached ? 3 : 4);
  const nearest = timers.reduce((best, t) => (urgency(t) < urgency(best) || (urgency(t) === urgency(best)
    && t.remaining_seconds !== null && best.remaining_seconds !== null && t.remaining_seconds < best.remaining_seconds) ? t : best));
  if (nearest.met_at) return nearest.breached ? "Met late" : "Met";
  if (nearest.breached) return "Breached";
  if (nearest.paused) return "Paused";
  return { minutes: Math.max(0, Math.round(nearest.remaining_seconds / 60)) };
}
/** "9h 58m left" → 598; anything else stays a word. */
const minutesOf = (label) => {
  const match = /^(?:(\d+)d|(?:(\d+)h )?(\d+)m) left$/.exec(label ?? "");
  if (!match) return label;
  return match[1] ? Number(match[1]) * 1440 : Number(match[2] ?? 0) * 60 + Number(match[3]);
};
/** A UI label agrees with the oracle — countdowns within a minute of clock between the two reads. */
function agrees(label, expected) {
  if (expected === null) return label === null;
  if (typeof expected === "string") return label === expected;
  const minutes = minutesOf(label);
  return typeof minutes === "number" && (minutes >= 2880 ? Math.abs(minutes - Math.floor(expected.minutes / 1440) * 1440) === 0
    : Math.abs(minutes - expected.minutes) <= 1);
}

const { session, close } = await openBrowser({ port: PORT, profile: PROFILE });
let world = null;
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);

  // 1. The world, over REST.
  world = await session.eval(`(async () => { ${API}
    const project = await api("POST", "/projects", { key: ${JSON.stringify(key)}, name: "SLA columns proof" });
    const id = project.body.id;
    const gold = await api("POST", "/sla-policies", { project_id: id, name: "Gold", priorities: ["high"],
      response_minutes: 600, resolution_minutes: 2880, enabled: true });
    const silver = await api("POST", "/sla-policies", { project_id: id, name: "Silver", priorities: ["normal"],
      response_minutes: 125, resolution_minutes: 1440, enabled: true });
    const high = await api("POST", "/items", { project_id: id, title: "SLA columns proof: gold", priority: "high" });
    const normal = await api("POST", "/items", { project_id: id, title: "SLA columns proof: silver", priority: "normal" });
    const low = await api("POST", "/items", { project_id: id, title: "SLA columns proof: no policy", priority: "low" });
    const list = await api("POST", "/views", { project_id: id, name: "SLA columns list", view_type: "list",
      columns: ["priority", "slas.timer", "state"] });
    const board = await api("POST", "/views", { project_id: id, name: "SLA columns board", view_type: "board",
      group_by: "state", card_layout: { v: 1, max_labels: 3, cells: [
        { attr: "title", row: 1, col: 0, span: 8 }, { attr: "slas.timer", row: 2, col: 0, span: 2 },
        { attr: "assignee", row: 2, col: 7, span: 1, align: "end" }] } });
    return { projectId: id, items: [high.body, normal.body, low.body].map((i) => ({ id: i?.id, key: i?.key })),
      listId: list.body?.id, boardId: board.body?.id, listColumns: list.body?.columns,
      status: [project.status, gold.status, silver.status, high.status, normal.status, low.status, list.status, board.status] };
  })()`);
  check("a throwaway project, two enabled policies, three issues and a list + board view exist",
    world.status.join() === "201,201,201,201,201,201,201,201", JSON.stringify(world.status));
  check("the list view stores the plugin's column id", JSON.stringify(world.listColumns) === '["priority","slas.timer","state"]',
    JSON.stringify(world.listColumns));

  const direct = async () => session.eval(`(async () => { ${API}
    const r = await api("POST", "/items/sla/batch", { item_ids: ${JSON.stringify(world.items.map((i) => i.id))} });
    return r.body; })()`);

  // 2a. The list view.
  await session.navigate(`${baseUrl}/p/${key}/v/${world.listId}`, 2500);
  await waitFor(session, `document.querySelectorAll('[data-sla-cell]').length === 2`);
  const listCells = await session.eval(`(() => {
    const header = [...document.querySelectorAll('[data-column]')].map((el) => el.dataset.column);
    return Object.fromEntries([...document.querySelectorAll('li')].map((row) => {
      const key = row.textContent.match(/${key}-\\d+/)?.[0];
      const cell = [...row.children].filter((el) => el.style.flexBasis)[header.indexOf('slas.timer')];
      return [key, cell ? cell.querySelector('[data-sla-chip]')?.textContent ?? cell.textContent.trim() : undefined];
    }).filter(([k]) => k)); })()`);
  const listTruth = await direct();
  check("GET-equivalent: the batch answers the two matched issues only",
    Object.keys(listTruth).length === 2 && !listTruth[world.items[2].id], JSON.stringify(listTruth));
  for (const [index, item] of world.items.entries()) {
    const expected = expectedChip(listTruth[item.id]);
    const shown = listCells[item.key];
    check(`list: ${item.key}'s SLA cell equals the batch (${JSON.stringify(expected)})`,
      index === 2 ? shown === "—" : agrees(shown, expected), `${shown} vs ${JSON.stringify(expected)}`);
  }
  const resources = await session.eval(`performance.getEntriesByType("resource").map((entry) => new URL(entry.name).pathname)`);
  check("the list asked POST /items/sla/batch", resources.includes("/api/v1/items/sla/batch"), JSON.stringify(resources.filter((r) => r.includes("sla"))));
  check("the cells are loaded from /plugins/slas/", resources.includes("/plugins/slas/remoteEntry.js"),
    JSON.stringify(resources.filter((r) => r.startsWith("/plugins/"))));
  await session.screenshot(resolve(TMP, "sla-columns-proof-list.png"));

  // 2b. The board view.
  await session.navigate(`${baseUrl}/p/${key}/v/${world.boardId}`, 2500);
  await waitFor(session, `document.querySelectorAll('[role=button][draggable=true]').length === 3 && document.querySelectorAll('[data-sla-cell]').length === 2`);
  const cardCells = await session.eval(`Object.fromEntries([...document.querySelectorAll('[role=button][draggable=true]')]
    .map((card) => [card.textContent.match(/${key}-\\d+/)?.[0], card.querySelector('[data-sla-chip]')?.textContent ?? null]))`);
  const boardTruth = await direct();
  for (const item of world.items) {
    const expected = expectedChip(boardTruth[item.id]);
    check(`board: ${item.key}'s card cell equals the batch (${JSON.stringify(expected)})`,
      agrees(cardCells[item.key], expected), `${cardCells[item.key]} vs ${JSON.stringify(expected)}`);
  }
  await session.screenshot(resolve(TMP, "sla-columns-proof-board.png"));

  // 3. The issue rail.
  const gold = world.items[0];
  await session.navigate(`${baseUrl}/issues/${gold.key}`, 2500);
  await waitFor(session, `document.querySelectorAll('[data-plugin-section="slas"] [data-sla-chip]').length === 2`);
  const rail = await session.eval(`[...document.querySelectorAll('[data-plugin-section="slas"] li')]
    .map((li) => [li.firstElementChild.textContent.trim(), li.querySelector('[data-sla-chip]').textContent])`);
  const itemSla = await session.eval(`(async () => { ${API} return (await api("GET", "/items/${gold.id}/sla")).body; })()`);
  const railWanted = itemSla.entries.flatMap((entry) => entry.timers.map((t) => [t.kind, expectedChip([{ ...t, policy_name: entry.policy_name }])]));
  check("rail: the SLA section (issue.panel.section) equals GET /items/{id}/sla",
    rail.length === railWanted.length && rail.every(([kind, label], i) => kind === railWanted[i][0] && agrees(label, railWanted[i][1])),
    `${JSON.stringify(rail)} vs ${JSON.stringify(railWanted)}`);

  // 4. Only the remote carries the cell's hook.
  const assets = resolve(HERE, "../dist/assets");
  const hostHooks = readdirSync(assets).filter((f) => f.endsWith(".js") && readFileSync(resolve(assets, f), "utf8").includes("data-sla-cell"));
  const remoteHook = readFileSync(resolve(HERE, "../../server/src/radd/modules/slas/ui/dist/remoteEntry.js"), "utf8").includes("data-sla-cell");
  check("the host bundle has no SLA cell code; the slas remote does", hostHooks.length === 0 && remoteHook, JSON.stringify(hostHooks));

  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors));
} finally {
  // 5. Clean up: issues, policies and default views cascade with the project.
  if (world?.projectId) {
    const cleaned = await session.eval(`(async () => { ${API}
      const views = [${JSON.stringify(world.listId ?? "")}, ${JSON.stringify(world.boardId ?? "")}].filter(Boolean);
      const v = await Promise.all(views.map((id) => api("DELETE", "/views/" + id)));
      const p = await api("DELETE", "/projects/" + ${JSON.stringify(world.projectId)});
      const gone = await api("GET", "/projects/by-key/" + ${JSON.stringify(key)});
      return [...v.map((r) => r.status), p.status, gone.status];
    })()`);
    check("the views and the project are deleted again", cleaned.join() === "204,204,204,404", JSON.stringify(cleaned));
  }
  await close();
}
const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "SLA columns (RADD-1394)", key },
);
process.exit(failed ? 1 : 0);
