// The roadmap row model's two readings (RADD-1511): grouped under epics, or
// FLAT — leaves only, in fetch order — plus the cycle bands on the axis.
//
//   node --test web/scripts/roadmap-rows.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { evaluateTs, importTs } from "./lib/load-ts.mjs";

const { formatIso, todayIso } = await importTs("web/packages/plugin-sdk/src/dates.ts");

// Local-midnight ISO, as lib/timesheet's toISODate does it.
const toISODate = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const dates = evaluateTs(
  readFileSync("web/src/components/roadmap/model/dates.ts", "utf8"),
  { toISODate },
  ["ROADMAP_DOMAIN_PAD_DAYS", "addDays", "daysBetween", "isScheduled", "parseDay", "startOfWeek"],
);
const { buildRoadmapModel } = evaluateTs(
  readFileSync("web/src/components/roadmap/model/rows.ts", "utf8"),
  { toISODate, ItemKind: { epic: "epic", issue: "issue", subtask: "subtask" }, ...dates, formatIso, todayIso },
  ["buildRoadmapModel"],
);
const { cycleBands } = evaluateTs(
  readFileSync("web/src/components/roadmap/model/cycles.ts", "utf8"),
  { daysBetween: dates.daysBetween, parseDay: dates.parseDay },
  ["cycleBands"],
);

const epic = { id: "e1", key: "PX-1", kind: "epic", start_date: "2026-09-01", target_date: "2026-09-30" };
const a = { id: "a", key: "PX-2", kind: "issue", parent: { id: "e1", key: "PX-1", title: "Epic" }, start_date: "2026-09-02", target_date: "2026-09-05" };
const lone = { id: "l", key: "PX-3", kind: "issue", parent: null, start_date: "2026-09-10", target_date: "2026-09-12" };
const b = { id: "b", key: "PX-4", kind: "issue", parent: { id: "e1", key: "PX-1", title: "Epic" }, start_date: "2026-09-06", target_date: "2026-09-08" };
const unscheduled = { id: "u", key: "PX-5", kind: "issue", parent: { id: "e1", key: "PX-1", title: "Epic" }, start_date: null, target_date: null };
const items = [epic, a, lone, b, unscheduled];

test("grouped: the epic row, its scheduled children beneath it, then the lone leaf", () => {
  const model = buildRoadmapModel(items, "2026-09-15");
  assert.deepEqual(model.rows.map((row) => [row.item.id, row.rowKind, row.parentEpicId]), [
    ["e1", "epic", null],
    ["a", "child", "e1"],
    ["b", "child", "e1"],
    ["l", "standalone", null],
  ]);
});

test("flat: no epic row, every scheduled leaf standalone, fetch order kept", () => {
  const model = buildRoadmapModel(items, "2026-09-15", undefined, true);
  assert.deepEqual(model.rows.map((row) => [row.item.id, row.rowKind, row.parentEpicId]), [
    ["a", "standalone", null],
    ["l", "standalone", null],
    ["b", "standalone", null],
  ]);
  assert.ok(model.rows.every((row) => row.children.length === 0 && row.childrenBounds === null));
});

test("flat: an epic with no scheduled children leaves nothing behind", () => {
  const model = buildRoadmapModel([epic, unscheduled], "2026-09-15", undefined, true);
  assert.deepEqual(model.rows, []);
  assert.equal(model.domainStart, null);
});

test("cycle bands: dated cycles overlapping the domain, clamped and start-ordered", () => {
  const model = buildRoadmapModel(items, "2026-09-15");
  const cycles = [
    { id: "late", name: "Sprint 3", start_date: "2026-09-20", end_date: "2026-10-03" },
    { id: "draft", name: "Draft", start_date: null, end_date: null },
    { id: "early", name: "Sprint 2", start_date: "2026-09-06", end_date: "2026-09-19" },
    { id: "gone", name: "Sprint 0", start_date: "2025-01-01", end_date: "2025-01-14" },
    { id: "wide", name: "Year", start_date: "2020-01-01", end_date: "2030-12-31" },
  ];
  const bands = cycleBands(cycles, model);
  assert.deepEqual(bands.map((band) => band.id), ["wide", "early", "late"]);
  const early = bands.find((band) => band.id === "early");
  assert.equal(early.startIndex, dates.daysBetween(model.domainStart, dates.parseDay("2026-09-06")));
  assert.equal(early.endIndex - early.startIndex + 1, 14, "a two-week sprint spans 14 day columns");
  const wide = bands.find((band) => band.id === "wide");
  assert.deepEqual([wide.startIndex, wide.endIndex], [0, model.domainDays - 1], "clamped to the domain");
});

test("cycle bands: an empty model draws none", () => {
  const model = buildRoadmapModel([], "2026-09-15");
  assert.deepEqual(cycleBands([{ id: "x", name: "X", start_date: "2026-09-01", end_date: "2026-09-14" }], model), []);
});
