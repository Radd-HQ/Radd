// The timesheet's Team view (RADD-1574): who draws attention, and why, in words
// a manager can take to the person.
//
//   node --test web/scripts/timelog-team.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { importTs } from "./lib/load-ts.mjs";

const team = await importTs("web/src/components/timelog/team.ts");

// Mon 2026-11-09 .. Sun 2026-11-15, judged from the Monday after.
const WEEK = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"];
const RULES = {
  workDays: ["mon", "tue", "wed", "thu", "fri"],
  hoursPerDay: 8,
  dayMaxHours: 10,
  lowPercent: 75,
  highPercent: 125,
  daysPercent: 75,
  dayStartHour: 9,
  today: "2026-11-16",
};
const H = 3600;
const person = { id: "p", name: "Pat" };
const log = (day, hours, id = "p") => ({ user: { id, name: id }, worked_on: day, time_spent_seconds: hours * H });
const flags = (row) => row.attention.map((item) => item.flag);
const none = new Map();

test("eight hours a working day draws no attention", () => {
  const row = team.teamRow(person, WEEK, WEEK.slice(0, 5).map((day) => log(day, 8)), none, RULES);
  assert.deepEqual(flags(row), []);
  assert.equal(row.percent, 100);
  assert.equal(row.daysLogged, 5);
  assert.equal(row.workingDays, 5);
});

test("a week booked on one day is flagged twice: too few days, and a day nobody works", () => {
  const row = team.teamRow(person, WEEK, [log("2026-11-13", 40)], none, RULES);
  assert.deepEqual(flags(row), [team.TeamFlag.fewDays, team.TeamFlag.longDay]);
  assert.equal(row.percent, 100); // the total is right, which is why the total alone is not enough
  assert.match(row.attention[0].reason, /Time on 1 of 5 working days; 40h of it on /);
  assert.match(row.attention[1].reason, /1 day over 10h: .*\(40h\)/);
});

test("nothing logged is its own flag, not a percentage", () => {
  const row = team.teamRow(person, WEEK, [], none, RULES);
  assert.deepEqual(flags(row), [team.TeamFlag.nothing]);
  assert.equal(row.attention[0].reason, "Nothing logged in 5 working days");
});

test("well under and well over expected are flagged with the figures", () => {
  const under = team.teamRow(person, WEEK, WEEK.slice(0, 5).map((day) => log(day, 4)), none, RULES);
  assert.deepEqual(flags(under), [team.TeamFlag.under]);
  assert.equal(under.attention[0].reason, "20h logged of 40h expected (50%)");
  const over = team.teamRow(person, WEEK, WEEK.slice(0, 5).map((day) => log(day, 10.5)), none, RULES);
  assert.deepEqual(flags(over), [team.TeamFlag.over, team.TeamFlag.longDay]);
  const edge = team.teamRow(person, WEEK, WEEK.slice(0, 5).map((day) => log(day, 6)), none, RULES);
  assert.deepEqual(flags(edge), []); // 75% is not under 75%
});

test("leave lowers what is expected, so a short week with leave in it is not flagged", () => {
  const leave = new Map([["2026-11-12", team.WHOLE_DAY], ["2026-11-13", team.WHOLE_DAY]]);
  const row = team.teamRow(person, WEEK, WEEK.slice(0, 3).map((day) => log(day, 8)), leave, RULES);
  assert.equal(row.expectedSeconds, 24 * H);
  assert.equal(row.workingDays, 3);
  assert.deepEqual(flags(row), []);
  const whole = team.teamRow(person, WEEK, [], new Map(WEEK.map((day) => [day, team.WHOLE_DAY])), RULES);
  assert.equal(whole.percent, null);
  assert.deepEqual(flags(whole), []); // a week of leave with nothing logged is as it should be
});

test("leave for part of a day takes its overlap with the working window, not the day", () => {
  // 8h from 09:00: the window is 09:00-17:00.
  assert.equal(team.awayHours({ from: "13:00" }, RULES), 4);
  assert.equal(team.awayHours({ until: "12:00" }, RULES), 3);
  assert.equal(team.awayHours({ from: "10:00", until: "12:00" }, RULES), 2);
  assert.equal(team.awayHours({ from: "18:00" }, RULES), 0); // an evening is not working time
  assert.equal(team.awayHours({ from: "08:00", until: "17:30" }, RULES), team.WHOLE_DAY);
  assert.equal(team.awayHours({}, RULES), team.WHOLE_DAY);
  // A later, shorter day moves the window with it.
  assert.equal(team.awayHours({ from: "13:00" }, { dayStartHour: 10, hoursPerDay: 6 }), 3);
});

test("a half day expects half, and a half day with nothing on it is a day missed", () => {
  const friday = "2026-11-13";
  const off = new Map([[friday, 4]]);
  const worked = team.teamRow(person, WEEK, [...WEEK.slice(0, 4).map((day) => log(day, 8)), log(friday, 4)], off, RULES);
  assert.equal(worked.expectedSeconds, 36 * H);
  assert.equal(worked.percent, 100);
  assert.equal(worked.workingDays, 5); // still a working day
  assert.deepEqual(flags(worked), []);
  const tile = worked.days.find((day) => day.day === friday);
  assert.equal(tile.partial, true);
  assert.equal(tile.exempt, false);
  assert.equal(tile.expectedSeconds, 4 * H);

  const skipped = team.teamRow(person, WEEK, WEEK.slice(0, 4).map((day) => log(day, 8)), off, RULES);
  assert.equal(skipped.daysLogged, 4);
  assert.equal(skipped.percent, 89); // 32h of 36h: the morning counts against them

  // Two absences on one day add up to the whole of it.
  const both = team.teamRow(person, WEEK, [], new Map([[friday, 4 + 4]]), RULES);
  assert.equal(both.days.find((day) => day.day === friday).exempt, true);
  assert.equal(both.workingDays, 4);
});

test("days that are not over yet are shown and never judged", () => {
  const midweek = { ...RULES, today: "2026-11-11" }; // Wednesday
  const row = team.teamRow(person, WEEK, [log("2026-11-09", 8), log("2026-11-10", 8), log("2026-11-11", 2)], none, midweek);
  assert.equal(row.workingDays, 2);
  assert.equal(row.loggedSeconds, 16 * H);
  assert.deepEqual(flags(row), []);
  assert.equal(row.days.find((day) => day.day === "2026-11-11").open, true);
  const untouched = team.teamRow(person, WEEK, [], none, { ...RULES, today: "2026-11-09" });
  assert.deepEqual(flags(untouched), []); // Monday morning flags nobody
});

test("weekend time counts toward the total but a weekend is not a day owed", () => {
  const row = team.teamRow(person, WEEK, [...WEEK.slice(0, 5).map((day) => log(day, 8)), log("2026-11-14", 4)], none, RULES);
  assert.equal(row.loggedSeconds, 44 * H);
  assert.equal(row.workingDays, 5);
  assert.deepEqual(flags(row), []);
});

test("flagged people come first, the furthest from expected first; a roster member with no time is listed", () => {
  const people = [{ id: "a", name: "Ada" }, { id: "b", name: "Bo" }, { id: "c", name: "Cy" }];
  const entries = [
    ...WEEK.slice(0, 5).map((day) => log(day, 8, "a")),
    ...WEEK.slice(0, 5).map((day) => log(day, 4, "c")),
    log("2026-11-10", 1, "z"), // logged time, not on the roster
  ];
  const rows = team.teamRows(people, WEEK, entries, new Map(), RULES);
  assert.deepEqual(rows.map((row) => row.id), ["z", "b", "c", "a"]);
  assert.deepEqual(flags(rows[1]), [team.TeamFlag.nothing]);
});
