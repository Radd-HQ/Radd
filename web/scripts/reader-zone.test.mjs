/** Unit cases for the reader-zone seam in lib/dates (RADD-1008).
 *
 * The profile timezone used to be stored and never read. Every formatter now
 * goes through one module-level zone, so this asserts the two rules that make
 * it correct rather than merely present: a TIMESTAMP moves with the zone, a
 * DATE-ONLY value never does, and "today" is the reader's calendar day.
 *
 * Pure module, no DOM — tested here for the same reason plain-text.test.mjs is.
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "reader-zone-"));
const file = join(dir, "dates.ts");
writeFileSync(file, readFileSync("web/src/lib/dates.ts", "utf8"));
const {
  setReaderTimeZone, readerTimeZone, formatIso, formatDate, formatDateTime,
  shortDate, isoDayOf, todayIso, shiftIsoDay, isoDaysAgo,
} = await import(file);

let failures = 0;
const check = (label, actual, expected) => {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) console.log(`ok   ${label}`);
  else { failures++; console.log(`FAIL ${label}\n     got      ${a}\n     expected ${e}`); }
};

// 2026-07-06T09:41:12Z — 21:41 the same day in Auckland (UTC+12), 02:41 in Los Angeles (UTC−7).
const AT = "2026-07-06T09:41:12Z";
const hourOf = (s) => new Intl.DateTimeFormat("en-US", { hour: "numeric", hour12: false, timeZone: s }).format(new Date(AT));

setReaderTimeZone("Pacific/Auckland");
check("the zone is stored", readerTimeZone(), "Pacific/Auckland");
check("a timestamp renders in the reader's zone (Auckland)",
  formatIso(AT, { hour: "numeric", hour12: false }), hourOf("Pacific/Auckland"));
check("the calendar day of an instant follows the zone (Auckland)", isoDayOf(new Date("2026-07-06T13:00:00Z")), "2026-07-07");

setReaderTimeZone("America/Los_Angeles");
check("a timestamp renders in the reader's zone (Los Angeles)",
  formatIso(AT, { hour: "numeric", hour12: false }), hourOf("America/Los_Angeles"));
check("the calendar day of an instant follows the zone (Los Angeles)", isoDayOf(new Date("2026-07-06T05:00:00Z")), "2026-07-05");
check("formatDate on a timestamp is the reader's calendar day", formatDate("2026-07-06T05:00:00Z"), formatDate("2026-07-05"));

// A date-only value is a calendar date: identical at UTC+14 and UTC−11.
const DAY = "2026-07-06";
setReaderTimeZone("Pacific/Kiritimati");
const east = [formatDate(DAY), shortDate(DAY), formatIso(DAY, { weekday: "long" })];
setReaderTimeZone("Pacific/Pago_Pago");
const west = [formatDate(DAY), shortDate(DAY), formatIso(DAY, { weekday: "long" })];
check("a date-only value renders the same day in every zone", west, east);
check("a date-only value is the day it says", formatIso(DAY, { day: "numeric", month: "numeric" }).includes("6"), true);

check("an unknown zone falls back to the browser's", (setReaderTimeZone("Mars/Olympus_Mons"), readerTimeZone()), "");
check("an empty zone is the browser's", (setReaderTimeZone(""), readerTimeZone()), "");

check("shiftIsoDay is calendar math", shiftIsoDay("2026-03-28", 3), "2026-03-31");
check("shiftIsoDay crosses a month backward", shiftIsoDay("2026-03-01", -1), "2026-02-28");
check("isoDaysAgo(0) is today", isoDaysAgo(0), todayIso());
check("todayIso is the reader's day", todayIso(), isoDayOf(new Date()));
check("formatDateTime carries a time", /\d:\d\d/.test(formatDateTime(AT)), true);

if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log("\nall passed");
