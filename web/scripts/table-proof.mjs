/**
 * Proves RADD-750: the table chrome is ours, and inserting is a grid pick.
 *
 * The engine is deliberately NOT under test — `prosemirror-tables` is what every
 * ProseMirror editor uses and it is not what changed. What is under test is the
 * chrome: that sweeping a grid produces the size you swept, that a row and a
 * column can be added and removed from a handle, that alignment is settable per
 * column, and — the one that matters most — that the markdown ROUND-TRIPS, since
 * GFM is what this body is stored as.
 *
 * Usage: node scripts/table-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9456;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-table-proof");

/** A table with alignment already set, to prove it SURVIVES rather than that we
 *  can write it once. */
const SEED = [
  "before",
  "",
  "| Name | Qty | Notes |",
  "| :--- | ---: | :---: |",
  "| Bolt | 12 | steel |",
  "| Nut | 40 | brass |",
  "",
  "after",
  "",
].join("\n");

const SHAPE = `(() => {
  const t = document.querySelector(".ProseMirror [data-table-block] table");
  if (!t) return { present: false };
  const rows = [...t.querySelectorAll("tr")];
  return {
    present: true,
    rows: rows.length,
    cols: rows[0] ? rows[0].children.length : 0,
    text: rows.map((r) => [...r.children].map((c) => c.textContent.trim()).join("|")).join(" / "),
    columnHandles: document.querySelectorAll('[data-table-handle="column"]').length,
    rowHandles: document.querySelectorAll('[data-table-handle="row"]').length,
    crepeTables: document.querySelectorAll(".milkdown-table-block").length,
    // prosemirror-tables' own resizing plugin, which preset-gfm ships but does
    // not compose — its presence is a <col> element per column.
    hasColgroup: !!t.querySelector("colgroup"),
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "table-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Table proof", body }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  const before = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  // --- an untouched table must round-trip ---------------------------------
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 2500);
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);
  const opened = await session.eval(SHAPE);
  // Hovering the table is what reveals the handles.
  await session.hover("[data-table-block]");
  await sleep(400);
  const hovered = await session.eval(`(() => {
    const h = document.querySelector('[data-table-handle="column"]');
    return h ? { opacity: getComputedStyle(h).opacity, w: h.getBoundingClientRect().width } : null;
  })()`);

  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);
  const untouched = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  // --- add a row and a column from the handles ----------------------------
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(2500);
  await session.hover("[data-table-block]");
  await sleep(400);
  await session.click('[data-table-handle="column"][data-index="1"]');
  await sleep(500);
  await session.click('[role="menu"] [role="menuitem"]', (t) => t.includes("Insert column after"));
  await sleep(600);
  const afterAddColumn = await session.eval(SHAPE);

  await session.hover("[data-table-block]");
  await sleep(300);
  await session.click('[data-table-handle="row"][data-index="1"]');
  await sleep(500);
  await session.click('[role="menu"] [role="menuitem"]', (t) => t.includes("Insert row below"));
  await sleep(600);
  const afterAddRow = await session.eval(SHAPE);

  // --- alignment on a column ----------------------------------------------
  await session.hover("[data-table-block]");
  await sleep(300);
  await session.click('[data-table-handle="column"][data-index="0"]');
  await sleep(500);
  await session.click('[role="menu"] [role="menuitem"]', (t) => t.includes("Align right"));
  await sleep(600);

  // --- delete the column we added -----------------------------------------
  await session.hover("[data-table-block]");
  await sleep(300);
  await session.click('[data-table-handle="column"][data-index="2"]');
  await sleep(500);
  await session.click('[role="menu"] [role="menuitem"]', (t) => t.includes("Delete column"));
  await sleep(600);
  const afterDelete = await session.eval(SHAPE);

  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);
  const edited = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  // --- the grid picker ------------------------------------------------------
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(2500);
  await session.click('[role="toolbar"] button[data-toolbar-action="table"]');
  await sleep(600);
  const picker = await session.eval(`(() => {
    const d = document.querySelector('[role="dialog"][aria-label="Insert table"]');
    return d ? { open: true, cells: d.querySelectorAll('[data-grid-cell]').length } : { open: false };
  })()`);
  // Sweep to 3x4, then commit — the size must be the size that was swept.
  await session.hover('[data-grid-cell="3x4"]');
  await sleep(250);
  const sweep = await session.eval(`(() => {
    const lit = document.querySelectorAll('[data-grid-cell][data-on]').length;
    const label = document.querySelector('[role="dialog"][aria-label="Insert table"] p');
    return { lit, label: label ? label.textContent.trim() : null };
  })()`);
  await session.click('[data-grid-cell="3x4"]');
  await sleep(800);
  // The new table goes in at the CURSOR, which is at the top of a freshly
  // opened editor — so it is the first table, not the last. Identify it by the
  // one whose header cells are empty rather than by position, which is the only
  // way that stays true if the cursor is somewhere else.
  const inserted = await session.eval(`(() => {
    const tables = [...document.querySelectorAll(".ProseMirror [data-table-block] table")];
    const fresh = tables.find((t) =>
      [...(t.querySelector("tr")?.children ?? [])].every((c) => !c.textContent.trim()));
    const rows = fresh ? [...fresh.querySelectorAll("tr")] : [];
    return { tables: tables.length, rows: rows.length, cols: rows[0] ? rows[0].children.length : 0 };
  })()`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the table renders in our node view": opened.present === true && opened.crepeTables === 0,
    "the seeded shape is read correctly": opened.rows === 3 && opened.cols === 3,
    "column resizing is wired (a colgroup exists)": opened.hasColgroup === true,
    "handles exist, one per line": opened.columnHandles === 3 && opened.rowHandles === 3,
    "hovering the table reveals them": hovered?.opacity === "1" && (hovered?.w ?? 0) > 0,
    // The assertion that protects every reader of this markdown.
    "an untouched table round-trips byte-identically": untouched === before,
    "a column can be added from its handle": afterAddColumn.cols === 4,
    "a row can be added from its handle": afterAddRow.rows === 4,
    "a column can be deleted from its handle": afterDelete.cols === 3,
    "the edit is saved as a GFM table": /\|\s*Name\s*\|/.test(edited || ""),
    // Column 0 was seeded LEFT (`:---`) and set to right from its handle, so the
    // delimiter row must now open right-aligned. Asserting "some column is left
    // and some is right" would have passed without the change ever landing.
    "setting a column's alignment reaches the markdown":
      /^\|\s*-+:\s*\|/m.test(edited || "") && !/^\|\s*:-+\s*\|/m.test(edited || ""),
    "the other columns keep the alignment they had":
      /:\s*-+\s*:\s*\|/.test((edited || "").replace(/\s/g, " ")) || /:-+:/.test(edited || ""),
    "the added row is in the markdown": (edited || "").split("\n").filter((l) => l.startsWith("|")).length === 5,
    "the toolbar's table button opens a grid picker": picker.open === true && picker.cells >= 25,
    "sweeping lights exactly the swept cells": sweep.lit === 12 && sweep.label === "3 × 4",
    // The swept grid maps one square to one CELL, header included — so 3 × 4 is
    // a three-row table, not three rows plus a header. The label says the same.
    "picking inserts the size that was swept": inserted.rows === 3 && inserted.cols === 4,
    "no console errors": consoleErrors.length === 0,
  };

  return report(checks, { opened, hovered, afterAddColumn, afterAddRow, afterDelete, picker, sweep, inserted, before, untouched, edited, consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
