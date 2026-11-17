// The time-entry calendar's arithmetic (RADD-1541): weeks that start on Monday
// whatever the timezone, durations that snap to quarter hours, and typed
// durations read the way a person writes them.
//
//   node --test web/scripts/timelog-model.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { importTs } from "./lib/load-ts.mjs";

const model = await importTs("web/src/components/timelog/model.ts");

test("a week starts on its Monday, for a Sunday as for a Monday", () => {
  assert.equal(model.weekStart("2026-10-19"), "2026-10-19"); // a Monday
  assert.equal(model.weekStart("2026-10-25"), "2026-10-19"); // its Sunday
  assert.equal(model.weekStart("2026-11-01"), "2026-10-26"); // across a month end
  assert.deepEqual(model.weekDays("2026-10-19"), [
    "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25",
  ]);
});

test("a week shifted across a DST change is still seven days on", () => {
  // Europe leaves summer time on 2026-10-25; a local-midnight Date lands an hour short.
  assert.equal(model.shiftWeek("2026-10-19", 1), "2026-10-26");
  assert.equal(model.shiftWeek("2026-10-26", -1), "2026-10-19");
});

test("durations snap to quarter hours and never below one", () => {
  assert.equal(model.snapSeconds(100), 900);
  assert.equal(model.snapSeconds(3600 + 400), 3600);
  assert.equal(model.snapSeconds(3600 + 500), 4500);
  // Pulling a 1h card's edge down one hour-height doubles it; up past zero floors it.
  assert.equal(model.resizedSeconds(3600, model.HOUR_PX), 7200);
  assert.equal(model.resizedSeconds(3600, -10 * model.HOUR_PX), 900);
});

test("duration text is what the server parses", () => {
  assert.equal(model.durationText(900), "15m");
  assert.equal(model.durationText(3600), "1h");
  assert.equal(model.durationText(5400), "1h 30m");
});

test("a typed duration reads the ways people write one", () => {
  assert.equal(model.parseDuration("1h 30m"), 5400);
  assert.equal(model.parseDuration("90m"), 5400);
  assert.equal(model.parseDuration("1.5h"), 5400);
  assert.equal(model.parseDuration("1:30"), 5400);
  assert.equal(model.parseDuration("2"), 7200); // a bare number is hours
  assert.equal(model.parseDuration("soon"), null);
  assert.equal(model.parseDuration("1h later"), null);
  assert.equal(model.parseDuration("0m"), null);
});

test("entries group under their day with a total; other days stay empty", () => {
  const days = model.weekDays("2026-10-19");
  const grouped = model.byDay(days, [
    { worked_on: "2026-10-19", time_spent_seconds: 3600 },
    { worked_on: "2026-10-19", time_spent_seconds: 1800 },
    { worked_on: "2026-11-30", time_spent_seconds: 999 }, // outside the week
  ]);
  assert.equal(grouped.get("2026-10-19").seconds, 5400);
  assert.equal(grouped.get("2026-10-19").entries.length, 2);
  assert.equal(grouped.get("2026-10-20").seconds, 0);
});

test("only a past working day can be under; any day can be over", () => {
  const rule = { minHours: 6, maxHours: 10 };
  const day = (seconds, working, past) => model.dayLoad(seconds, { ...rule, working, past });
  assert.equal(day(0, true, true), "under");
  assert.equal(day(0, true, false), "empty"); // today is still being worked
  assert.equal(day(0, false, true), "empty"); // a weekend owes nothing
  assert.equal(day(4 * 3600, true, true), "under");
  assert.equal(day(4 * 3600, true, false), "ok");
  assert.equal(day(8 * 3600, true, true), "ok");
  assert.equal(day(11 * 3600, false, false), "over");
  assert.equal(model.isWorkingDay("2026-10-24", ["mon", "tue", "wed", "thu", "fri"]), false);
  assert.equal(model.isWorkingDay("2026-10-23", ["mon", "tue", "wed", "thu", "fri"]), true);
});
