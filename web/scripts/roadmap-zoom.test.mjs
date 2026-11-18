// The roadmap zoom model (RADD-1520): one day width drives the row pitch, the axis tier, the
// in-row chrome and the fit-all width; and the axis ticks carry the year once a domain spans
// several.
//
//   node --test web/scripts/roadmap-zoom.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { evaluateTs, importTs } from "./lib/load-ts.mjs";

const { formatIso, todayIso } = await importTs("web/packages/plugin-sdk/src/dates.ts");
const constants = await importTs("web/src/lib/constants/roadmap.ts");
const geometry = await importTs("web/src/components/roadmap/model/geometry.ts");
const zoom = evaluateTs(
  readFileSync("web/src/components/roadmap/model/zoom.ts", "utf8"),
  { ...constants, ...geometry },
  [
    "ROADMAP_ROW_MIN_H",
    "roadmapRowMetrics",
    "roadmapLabelTier",
    "roadmapAxisTiers",
    "primaryAxisTicks",
    "ROADMAP_AXIS_LABEL_PX",
    "clampDayWidth",
    "fitDayWidth",
    "zoomPercentLabel",
    "visibleRowRange",
  ],
);
const { ROADMAP_DAY_WIDTH, ROADMAP_DAY_WIDTH_MIN, ROADMAP_DAY_WIDTH_MAX } = constants;
const { ROADMAP_ROW_H, barInfoTier, barShowsAvatar } = geometry;

test("rows keep the comfortable pitch at and above the default day width", () => {
  for (const width of [ROADMAP_DAY_WIDTH, 14, ROADMAP_DAY_WIDTH_MAX]) {
    assert.deepEqual(zoom.roadmapRowMetrics(width), { rowH: ROADMAP_ROW_H, leafBarH: 30, epicBarH: 34 });
  }
});

test("below the default the pitch shrinks by the day-width factor, in whole pixels, to the floor", () => {
  assert.equal(zoom.roadmapRowMetrics(6).rowH, Math.round(ROADMAP_ROW_H * (6 / 9)));
  assert.equal(zoom.roadmapRowMetrics(2).rowH, 10);
  const floor = zoom.roadmapRowMetrics(ROADMAP_DAY_WIDTH_MIN);
  assert.equal(floor.rowH, zoom.ROADMAP_ROW_MIN_H);
  assert.ok(floor.leafBarH >= 2 && floor.leafBarH < floor.rowH, "a bar still fits the strip");
  assert.ok(floor.epicBarH > floor.leafBarH, "epics stay the taller bar");
  for (let width = 0.25; width <= 9; width += 0.05) {
    assert.equal(zoom.roadmapRowMetrics(width).rowH % 1, 0, `pitch at ${width} is a whole pixel`);
  }
});

test("the label cell steps full → mini → none with the pitch", () => {
  assert.equal(zoom.roadmapLabelTier(44), "full");
  assert.equal(zoom.roadmapLabelTier(22), "full");
  assert.equal(zoom.roadmapLabelTier(21), "mini");
  assert.equal(zoom.roadmapLabelTier(14), "mini");
  assert.equal(zoom.roadmapLabelTier(13), "none");
});

test("in-bar info needs height as well as width; the avatar needs more than the pill", () => {
  assert.equal(barInfoTier(120, 30), "full");
  assert.equal(barInfoTier(120, 21), "compact", "too short for the title line, still room for the pill");
  assert.equal(barInfoTier(120, 17), "none");
  assert.equal(barInfoTier(60, 30), "compact");
  assert.equal(barInfoTier(40, 30), "none");
  assert.equal(barShowsAvatar(26), true);
  assert.equal(barShowsAvatar(25), false);
});

test("axis tiers follow the pixel pitch a label needs: the shortest month, quarter or week clears its label", () => {
  assert.deepEqual(zoom.roadmapAxisTiers(9), { primary: "month", weeks: "all" });
  assert.deepEqual(zoom.roadmapAxisTiers(6), { primary: "month", weeks: "all" });
  assert.deepEqual(zoom.roadmapAxisTiers(5), { primary: "month", weeks: "alternate" });
  assert.deepEqual(zoom.roadmapAxisTiers(2.5), { primary: "month", weeks: "none" });
  assert.deepEqual(zoom.roadmapAxisTiers(2), { primary: "quarter", weeks: "none" }, "February at 2px is 56px, under a 'Jan 2026' label");
  assert.deepEqual(zoom.roadmapAxisTiers(1), { primary: "quarter", weeks: "none" });
  assert.deepEqual(zoom.roadmapAxisTiers(0.5), { primary: "year", weeks: "none" });
  assert.deepEqual(zoom.roadmapAxisTiers(0.25), { primary: "year", weeks: "none" });
  assert.ok(28 * 2.5 >= zoom.ROADMAP_AXIS_LABEL_PX.month, "a 28-day month clears the month label at the month tier's floor");
});

test("the opening tick is drawn only when the first real tick is a label's width away at this zoom", () => {
  const model = {
    months: [{ index: 0, label: "Oct 2024", opening: true }, { index: 18, label: "Nov" }],
    quarters: [{ index: 0, label: "Q4 2024", opening: true }, { index: 79, label: "Q1 2025" }],
    years: [{ index: 0, label: "2024", opening: true }, { index: 79, label: "2025" }],
  };
  assert.deepEqual(zoom.primaryAxisTicks(model, "month", 9).map((t) => t.label), ["Oct 2024", "Nov"], "18 days at 9px = 162px: both fit");
  assert.deepEqual(zoom.primaryAxisTicks(model, "month", 2.5).map((t) => t.label), ["Nov"], "18 days at 2.5px = 45px: the opening label would overlap");
  assert.deepEqual(zoom.primaryAxisTicks(model, "quarter", 1).map((t) => t.label), ["Q4 2024", "Q1 2025"]);
  assert.deepEqual(zoom.primaryAxisTicks(model, "quarter", 0.65).map((t) => t.label), ["Q1 2025"]);
  assert.deepEqual(zoom.primaryAxisTicks(model, "year", 0.25).map((t) => t.label), ["2025"], "79 days at the floor is 20px");
  assert.deepEqual(zoom.primaryAxisTicks({ ...model, years: [{ index: 0, label: "2025" }] }, "year", 0.25).map((t) => t.label), ["2025"], "a real tick at day 0 is never dropped");
});

test("fit puts the domain in the pane width, clamped to the zoom range", () => {
  assert.equal(zoom.fitDayWidth(1000, 400), 2.5);
  assert.equal(zoom.fitDayWidth(1000, 40000), ROADMAP_DAY_WIDTH_MIN, "a domain past the floor still overflows");
  assert.equal(zoom.fitDayWidth(1000, 7), ROADMAP_DAY_WIDTH_MAX, "a week never fills a pane");
  assert.equal(zoom.fitDayWidth(1000, 0), ROADMAP_DAY_WIDTH);
  assert.equal(zoom.clampDayWidth(0.01), ROADMAP_DAY_WIDTH_MIN);
  assert.equal(zoom.clampDayWidth(99), ROADMAP_DAY_WIDTH_MAX);
});

test("the virtual row window covers the pane plus the overscan, clamped to the rows", () => {
  // Header 40, pitch 44, 306 rows, a 776px pane at the top: rows 0..16 intersect, +6 overscan.
  assert.deepEqual(zoom.visibleRowRange(0, 776, 40, 44, 306, 6), { first: 0, last: 23 });
  // Scrolled 4000px: (4000-40)/44 = 90 → 84 .. ceil((3960+776)/44)=108 + 6.
  assert.deepEqual(zoom.visibleRowRange(4000, 776, 40, 44, 306, 6), { first: 84, last: 114 });
  // The bottom: never past the row count.
  assert.deepEqual(zoom.visibleRowRange(13000, 776, 40, 44, 306, 6), { first: 288, last: 306 });
  // At the 8px floor the same pane holds ~100 rows.
  const floor = zoom.visibleRowRange(0, 776, 40, 8, 306, 6);
  assert.equal(floor.first, 0);
  assert.ok(floor.last >= 97 && floor.last <= 110, `${floor.last}`);
  assert.deepEqual(zoom.visibleRowRange(0, 776, 40, 44, 0, 6), { first: 0, last: 0 });
  assert.deepEqual(zoom.visibleRowRange(0, 776, 40, 44, 5, 6), { first: 0, last: 5 }, "fewer rows than the pane: all of them");
});

test("an off-preset level reads as a share of the default", () => {
  assert.equal(zoom.zoomPercentLabel(ROADMAP_DAY_WIDTH), "100%");
  assert.equal(zoom.zoomPercentLabel(2), "22%");
  assert.equal(zoom.zoomPercentLabel(0.25), "3%");
});

// --- axis ticks (rows.ts): the year on January and the opening label, quarters, years -------
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

test("a multi-year domain labels January with its year, and every quarter and year start", () => {
  const long = { id: "l", key: "PX-1", kind: "issue", parent: null, start_date: "2024-11-15", target_date: "2026-03-10" };
  const model = buildRoadmapModel([long], "2026-01-15");
  const monthLabels = model.months.map((tick) => tick.label);
  assert.ok(monthLabels.includes("Jan 2025") && monthLabels.includes("Jan 2026"), `January carries its year: ${monthLabels}`);
  assert.ok(monthLabels.includes("Nov") && monthLabels.includes("Feb"), "other months stay short");
  assert.match(monthLabels[0], /^Oct 2024$|^Nov 2024$/, "the opening label carries the year too");
  assert.deepEqual(
    model.quarters.map((tick) => tick.label),
    ["Q4 2024", "Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026"].filter((label) =>
      model.quarters.some((tick) => tick.label === label),
    ),
  );
  assert.ok(model.quarters.some((tick) => tick.label === "Q1 2025"), "a quarter per quarter start");
  // The domain opens ~79 days before 2025-01-01: the model offers "2024" as an OPENING tick at
  // day 0 and the timeline decides, per zoom, whether it fits beside January 2025.
  assert.deepEqual(model.years.map((tick) => [tick.label, tick.opening ?? false]), [["2024", true], ["2025", false], ["2026", false]]);
  assert.equal(model.years[0].index, 0);
  // Ticks are index-ordered and inside the domain.
  for (const ticks of [model.months, model.quarters, model.years]) {
    for (let i = 1; i < ticks.length; i++) assert.ok(ticks[i].index > ticks[i - 1].index);
    assert.ok(ticks.every((tick) => tick.index >= 0 && tick.index < model.domainDays));
  }
});

test("a domain opening days before a boundary offers the opening tick, which no zoom can draw beside the real one", () => {
  const near = { id: "n", key: "PX-2", kind: "issue", parent: null, start_date: "2026-01-20", target_date: "2026-02-20" };
  const model = buildRoadmapModel([near], "2026-01-25");
  assert.deepEqual(model.years.map((tick) => [tick.label, tick.opening ?? false]), [["2025", true], ["2026", false]]);
  assert.ok(model.years[1].index > 0 && model.years[1].index < 30, "the real January is days in");
  assert.deepEqual(zoom.primaryAxisTicks(model, "year", 0.6).map((t) => t.label), ["2026"]);
  assert.deepEqual(zoom.primaryAxisTicks(model, "quarter", 2).map((t) => t.label), ["Q1 2026"]);
});
