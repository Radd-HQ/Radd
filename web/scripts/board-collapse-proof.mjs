#!/usr/bin/env node
/**
 * RADD-1175 proof: empty board columns collapse to a rail that is still a drop
 * target, and a hidden column is gone — both saved on the view.
 *
 *   node web/scripts/board-collapse-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Signs in as an admin, creates a throwaway project (default workflow), a
 * state-axis board and ONE issue (so every other state is empty), then checks
 * in a REAL browser that:
 *   1. with the switch off, every state is a full-width column;
 *   2. with `collapse_empty_columns` on, each empty column is a rail measurably
 *      narrower than a column, and the occupied one is not;
 *   3. hovering a rail expands it in place;
 *   4. starting a drag on the card expands EVERY rail, and dropping the card on
 *      a rail moves the issue to that state (API read-back);
 *   5. a key in `hidden_columns` removes that column from the board and the
 *      Order menu lists it with its eye toggle pressed.
 * Every check is a measurement (getBoundingClientRect, DOM state, API read-back).
 * The throwaway project is deleted at the end through RADD-1174's endpoint.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: board-collapse-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9485;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-board-collapse-proof");
const KEY = `BC${Date.now().toString(36).slice(-4).toUpperCase()}`;

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

const COLUMNS = `(() => [...document.querySelectorAll("[data-board-column]")].map((el) => ({
  key: el.dataset.boardColumn, collapsed: el.dataset.collapsed, width: Math.round(el.getBoundingClientRect().width),
})))()`;

async function columns(session) {
  return session.eval(COLUMNS);
}

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1600, height: 1000 });
  const checks = {};
  const context = { key: KEY };
  let projectId = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);

    // --- setup: project + state board + one issue ---
    const setup = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Collapse proof" });
      const view = await api("POST", "/views", { project_id: project.body.id, name: "Collapse board", view_type: "board", group_by: "state" });
      const item = await api("POST", "/items", { project_id: project.body.id, title: "the only card" });
      const states = await api("GET", "/states?project_id=" + project.body.id);
      return { project: project.body, view: view.body, item: item.body, states: states.body, statuses: [project.status, view.status, item.status, states.status] };
    })()`);
    context.setup = setup.statuses;
    checks.setupCreated = setup.statuses.every((s) => s === 201 || s === 200);
    const { project, view, item, states } = setup;
    projectId = project.id;
    const occupied = item.state.id;
    const emptyStates = states.filter((s) => s.id !== occupied);
    context.states = states.length;

    // --- 1. switch off: every state a full column ---
    await session.navigate(`${baseUrl}/p/${KEY}/v/${view.id}`, 2500);
    let cols = await columns(session);
    context.off = cols;
    checks.everyStateIsAColumn = cols.length === states.length && cols.every((c) => c.collapsed === "false" && c.width >= 300);

    // --- 2. switch on: empty ones are rails ---
    const on = await session.eval(`(async () => { ${API} return (await api("PATCH", "/views/${view.id}", { collapse_empty_columns: true })).status; })()`);
    checks.switchSaved = on === 200;
    await session.navigate(`${baseUrl}/p/${KEY}/v/${view.id}`, 2500);
    cols = await columns(session);
    context.on = cols;
    const rails = cols.filter((c) => c.key !== occupied);
    const full = cols.find((c) => c.key === occupied);
    checks.emptyColumnsAreRails = rails.length === emptyStates.length && rails.every((c) => c.collapsed === "true" && c.width <= 48);
    checks.occupiedColumnIsFull = Boolean(full && full.collapsed === "false" && full.width >= 300);
    await session.screenshot(resolve("scripts", "board-collapse-proof-rails.png"));

    // --- 3. hover expands one rail in place ---
    const target = emptyStates[0];
    context.targetProbe = await session.eval(`(() => ({
      keys: [...document.querySelectorAll("[data-board-column]")].map((el) => el.dataset.boardColumn),
      target: ${JSON.stringify(target.id)}, occupied: ${JSON.stringify(occupied)},
      found: Boolean(document.querySelector('[data-board-column="${target.id}"]')),
    }))()`);
    await session.hover(`[data-board-column="${target.id}"]`);
    await sleep(400);
    cols = await columns(session);
    const hovered = cols.find((c) => c.key === target.id);
    context.hovered = hovered;
    checks.hoverExpandsTheRail = Boolean(hovered && hovered.collapsed === "false" && hovered.width >= 300);
    checks.otherRailsStayCollapsed = cols.filter((c) => c.key !== occupied && c.key !== target.id).every((c) => c.collapsed === "true");
    await session.hover("h1, header");
    await sleep(400);

    // --- 4. a drag expands every rail; the drop lands on the empty state ---
    const dragged = await session.eval(`(() => {
      const card = document.querySelector("[data-board-column='${occupied}'] [draggable]");
      if (!card) return "no card";
      const dt = new DataTransfer();
      card.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: dt }));
      window.__proofDt = dt;
      return "started";
    })()`);
    context.dragged = dragged;
    await sleep(300);
    cols = await columns(session);
    context.midDrag = cols;
    checks.dragExpandsEveryRail = cols.every((c) => c.collapsed === "false" && c.width >= 300);
    const dropped = await session.eval(`(() => {
      const rail = document.querySelector("[data-board-column='${target.id}']");
      if (!rail) return "no target";
      const dt = window.__proofDt;
      rail.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt }));
      rail.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
      const card = document.querySelector("[draggable]");
      card?.dispatchEvent(new DragEvent("dragend", { bubbles: true, cancelable: true, dataTransfer: dt }));
      return "dropped";
    })()`);
    context.dropped = dropped;
    await sleep(1500);
    const moved = await session.eval(`(async () => { ${API} const r = await api("GET", "/items/${item.id}"); return r.body.state; })()`);
    context.movedTo = moved;
    checks.dropMovedTheIssueIntoTheEmptyState = moved && moved.id === target.id;
    cols = await columns(session);
    checks.previousColumnCollapsesAfterTheMove = cols.some((c) => c.key === occupied && c.collapsed === "true");
    await session.screenshot(resolve("scripts", "board-collapse-proof-after-drop.png"));

    // --- 5. a hidden column is gone, and the menu says so ---
    const hide = emptyStates[1] ?? emptyStates[0];
    const hid = await session.eval(`(async () => { ${API} return (await api("PATCH", "/views/${view.id}", { hidden_columns: [${JSON.stringify(hide.id)}] })).status; })()`);
    checks.hiddenSaved = hid === 200;
    await session.navigate(`${baseUrl}/p/${KEY}/v/${view.id}`, 2500);
    cols = await columns(session);
    checks.hiddenColumnAbsent = !cols.some((c) => c.key === hide.id) && cols.length === states.length - 1;
    await session.click("button", (t) => t.trim() === "Order");
    await sleep(400);
    const menu = await session.eval(`(() => {
      const row = document.querySelector("[data-bucket-row='${hide.id}']");
      const toggle = row?.querySelector("button[aria-pressed]");
      const box = [...document.querySelectorAll("input[type=checkbox]")].find((i) => i.parentElement?.textContent.includes("Collapse empty"));
      return { rowPresent: Boolean(row), pressed: toggle?.getAttribute("aria-pressed"), label: toggle?.getAttribute("aria-label"), collapseChecked: box?.checked };
    })()`);
    context.menu = menu;
    checks.menuListsHiddenColumnAsHidden = menu.rowPresent && menu.pressed === "true" && /^Show /.test(menu.label ?? "");
    checks.menuShowsSwitchOn = menu.collapseChecked === true;
    await session.screenshot(resolve("scripts", "board-collapse-proof-menu.png"));
    await session.click(`[data-bucket-row='${hide.id}'] button[aria-pressed]`, () => true);
    await sleep(1200);
    cols = await columns(session);
    checks.eyeToggleBringsItBack = cols.some((c) => c.key === hide.id);
  } catch (error) {
    console.error("proof aborted:", error.message, JSON.stringify(context, null, 2));
    throw error;
  } finally {
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
