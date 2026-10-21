// The roadmap plan verbs (RADD-1510): auto-schedule only GROWS the epic, the
// spread tiles the epic's window with equal slots, and a plan is ONE undo step.
//
//   node --test web/scripts/roadmap-planning.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { evaluateTs, importTs } from "./lib/load-ts.mjs";

const { shiftIsoDay } = await importTs("web/packages/plugin-sdk/src/dates.ts");
const { applyOp, flattenOps } = await importTs("web/src/components/roadmap/model/draft-ops.ts");

// `scheduling.ts` and `planning.ts` import the SDK and the host alias, which
// node cannot resolve — their imports are supplied by name instead.
const isoDaysBetween = (from, to) =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
const isScheduled = (item) => Boolean(item.start_date && item.target_date);
const ItemLinkType = { blocks: "blocks" };
const { epicGrowPatch, blocksEdges } = evaluateTs(
  readFileSync("web/src/components/roadmap/model/planning.ts", "utf8"),
  { shiftIsoDay, ROADMAP_CASCADE_MAX_ITEMS: 50, ItemLinkType, isoDaysBetween, isScheduled },
  ["epicGrowPatch", "blocksEdges"],
);
const { importChildrenPlan, spreadChildrenPlan } = evaluateTs(
  readFileSync("web/src/components/roadmap/model/scheduling.ts", "utf8"),
  { shiftIsoDay, ROADMAP_LEAF_SPAN_DAYS: 6, isoDaysBetween, epicGrowPatch },
  ["importChildrenPlan", "spreadChildrenPlan"],
);

const epic = (start, target) => ({ id: "e1", key: "PX-1", kind: "epic", start_date: start, target_date: target });
const child = (id, extra = {}) => ({ id, key: `PX-${id}`, kind: "issue", parent: { id: "e1" }, start_date: null, target_date: null, ...extra });
const children = [child("a"), child("b"), child("c")];
const patchFor = (plan, id) => plan.patches.find((entry) => entry.itemId === id)?.patch;

test("bring-children-in only grows the epic (outward-only), never shrinks it", () => {
  const plan = importChildrenPlan(children, epic("2026-08-01", "2026-12-01"), "2026-09-01", new Map());
  assert.equal(plan.importedCount, 3);
  assert.equal(patchFor(plan, "e1"), undefined);
});

test("the spread tiles the epic's window with equal back-to-back slots", () => {
  // 30 days, 3 children → 10-day slots.
  const plan = spreadChildrenPlan(children, [], epic("2026-09-01", "2026-09-30"));
  assert.equal(plan.spreadCount, 3);
  assert.deepEqual(plan.orderedIds, ["a", "b", "c"]);
  assert.deepEqual(patchFor(plan, "a"), { start_date: "2026-09-01", target_date: "2026-09-10" });
  assert.deepEqual(patchFor(plan, "b"), { start_date: "2026-09-11", target_date: "2026-09-20" });
  assert.deepEqual(patchFor(plan, "c"), { start_date: "2026-09-21", target_date: "2026-09-30" });
  assert.equal(patchFor(plan, "e1"), undefined, "the spread never touches the epic");
});

test("the spread absorbs a remainder without gaps or overlap", () => {
  // 31 days / 3 → slots of 10, 11, 10 (floor boundaries), still tiling exactly.
  const plan = spreadChildrenPlan(children, [], epic("2026-10-01", "2026-10-31"));
  const spans = plan.orderedIds.map((id) => patchFor(plan, id));
  assert.equal(spans[0].start_date, "2026-10-01");
  assert.equal(spans[2].target_date, "2026-10-31");
  for (let index = 1; index < spans.length; index++) {
    assert.equal(spans[index].start_date, shiftIsoDay(spans[index - 1].target_date, 1));
  }
});

test("the spread orders by blocks edges first, rank second", () => {
  // c blocks a: c must take the first slot.
  const plan = spreadChildrenPlan(children, [{ sourceId: "c", targetId: "a" }], epic("2026-09-01", "2026-09-30"));
  assert.deepEqual(plan.orderedIds, ["b", "c", "a"]);
});

test("the spread is empty for a date-less epic", () => {
  assert.deepEqual(spreadChildrenPlan(children, [], epic(null, null)), { patches: [], spreadCount: 0, orderedIds: [] });
});

test("a compound op applies its leaves in order and is one undo step", () => {
  const base = [epic("2026-09-01", "2026-09-30"), { ...child("b"), start_date: "2026-09-01", target_date: "2026-09-02" }];
  const compound = {
    kind: "compound",
    label: "Spread PX-1's children",
    ops: [
      {
        kind: "patch",
        label: "x",
        patches: [
          { itemId: "a", after: { start_date: "2026-09-03", target_date: "2026-09-04" }, insert: child("a") },
          { itemId: "b", after: { start_date: "2026-09-05", target_date: "2026-09-06" } },
        ],
      },
      { kind: "chain", label: "x", orderedIds: ["a", "b"] },
    ],
  };
  const drafted = applyOp(base, compound);
  assert.deepEqual(drafted.map((item) => item.id), ["e1", "a", "b"], "a now ranks before b");
  assert.equal(drafted[1].start_date, "2026-09-03");
  assert.equal(drafted[2].start_date, "2026-09-05");
  const leaves = flattenOps([compound, { kind: "reorder", label: "y", itemId: "b", afterId: null, beforeId: "a" }]);
  assert.deepEqual(leaves.map((op) => op.kind), ["patch", "chain", "reorder"]);
});
