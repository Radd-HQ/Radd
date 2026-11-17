// The date control's arithmetic and typed-entry parsing (RADD-1566).
import { test } from "node:test";
import assert from "node:assert/strict";
import { importTs } from "./lib/load-ts.mjs";

const m = await importTs(new URL("../packages/plugin-sdk/src/date-math.ts", import.meta.url).pathname);
const EN = m.localeMonthNames("en-US");

test("a month is always six Monday-first weeks that contain it", () => {
  for (const iso of ["2026-11-17", "2026-02-10", "2024-02-29", "2026-03-01", "2021-02-01"]) {
    const grid = m.monthGrid(iso);
    assert.equal(grid.length, 6);
    assert.ok(grid.every((week) => week.length === 7 && m.weekdayIndex(week[0]) === 0));
    const days = grid.flat();
    const first = `${iso.slice(0, 7)}-01`;
    assert.ok(days.includes(first) && days.includes(m.addDays(m.addMonths(first, 1), -1)), iso);
    assert.equal(new Set(days).size, 42);
  }
  // February 2021 starts on a Monday: the grid starts on the 1st itself.
  assert.equal(m.monthGrid("2021-02-14")[0][0], "2021-02-01");
});

test("stepping a month keeps the day, or the month's last when it has none", () => {
  assert.equal(m.addMonths("2026-01-31", 1), "2026-02-28");
  assert.equal(m.addMonths("2024-01-31", 1), "2024-02-29");
  assert.equal(m.addMonths("2026-03-31", -1), "2026-02-28");
  assert.equal(m.addMonths("2026-12-15", 1), "2027-01-15");
  assert.equal(m.addMonths("2026-01-15", -1), "2025-12-15");
  assert.equal(m.addDays("2026-12-31", 1), "2027-01-01");
  // Across the European DST change: one day is one day.
  assert.equal(m.addDays("2026-10-24", 1), "2026-10-25");
  assert.equal(m.addDays("2026-10-25", 1), "2026-10-26");
});

test("typed dates: ISO, the locale's numeric order, and a spelled month", () => {
  const dmy = (text) => m.parseTypedDate(text, "dmy", EN);
  const mdy = (text) => m.parseTypedDate(text, "mdy", EN);
  assert.equal(dmy("2026-11-22"), "2026-11-22");
  assert.equal(dmy("2026-1-5"), "2026-01-05");
  assert.equal(dmy("22/11/2026"), "2026-11-22");
  assert.equal(mdy("11/22/2026"), "2026-11-22");
  assert.equal(dmy("22.11.26"), "2026-11-22");
  assert.equal(m.parseTypedDate("2026/11/22", "ymd", EN), "2026-11-22");
  for (const text of ["22 Nov 2026", "Nov 22, 2026", "november 22 2026", "22 NOVEMBER 2026", "Nov 22 26"]) {
    assert.equal(dmy(text), "2026-11-22", text);
    assert.equal(mdy(text), "2026-11-22", text);
  }
  // The same digits mean different days in different orders: that is the point of asking.
  assert.equal(dmy("03/04/2026"), "2026-04-03");
  assert.equal(mdy("03/04/2026"), "2026-03-04");
});

test("what cannot be read is refused, never guessed", () => {
  const dmy = (text) => m.parseTypedDate(text, "dmy", EN);
  for (const text of ["", "  ", "tomorrow", "13/14/2026", "30/02/2026", "2026-02-30", "22/11", "no 22 2026", "22 Nov", "1/2/3/4", "22/xx/2026"]) {
    assert.equal(dmy(text), null, JSON.stringify(text));
  }
  assert.equal(m.isIsoDate("2026-02-30"), false);
  assert.equal(m.isIsoDate("2026-2-3"), false);
  assert.equal(m.isIsoDate("2024-02-29"), true);
});

test("range and locale order", () => {
  assert.equal(m.inRange("2026-11-17", "2026-11-17", "2026-11-17"), true);
  assert.equal(m.inRange("2026-11-16", "2026-11-17"), false);
  assert.equal(m.inRange("2026-11-18", undefined, "2026-11-17"), false);
  assert.equal(m.localeDateOrder("en-US"), "mdy");
  assert.equal(m.localeDateOrder("en-GB"), "dmy");
  assert.equal(m.localeDateOrder("sv-SE"), "ymd");
});
