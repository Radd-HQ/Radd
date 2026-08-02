/**
 * Unit cases for text-quote anchoring (RADD-728).
 *
 * The interesting ones are not "does it find the string". They are: does an edit
 * ABOVE the anchor leave it in place (the whole reason this is not an offset),
 * does a repeated phrase resolve by context, and does it refuse rather than
 * guess when the context cannot choose.
 *
 * Run: node --experimental-strip-types web/scripts/anchoring.test.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "anchor-"));
const file = join(dir, "anchoring.ts");
writeFileSync(file, readFileSync("web/src/lib/anchoring.ts", "utf8"));
const { makeAnchor, locateAnchor, orderByAnchor } = await import(file);

let failures = 0;
const check = (label, actual, expected) => {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    console.log(`FAIL ${label}\n  got      ${a}\n  expected ${e}`);
    failures++;
  } else {
    console.log(`ok   ${label}`);
  }
};

const BODY = "Intro paragraph.\n\nThe cache is invalidated on write.\n\nCloser.";
const start = BODY.indexOf("cache is invalidated");
const anchor = makeAnchor(BODY, start, start + "cache is invalidated".length);

check("an anchor captures the quote", anchor.quote, "cache is invalidated");
check("with context either side", [anchor.prefix.endsWith("The "), anchor.suffix.startsWith(" on write")], [true, true]);

check(
  "it locates in the unedited body",
  locateAnchor(BODY, anchor),
  { status: "located", start, end: start + anchor.quote.length },
);

// THE case this design exists for: inserting text ABOVE must not move it.
const EDITED_ABOVE = BODY.replace("Intro paragraph.", "Intro paragraph.\n\nA whole new section.");
const moved = locateAnchor(EDITED_ABOVE, anchor);
check("an edit ABOVE does not orphan it", moved.status, "located");
check(
  "and it still points at the same words",
  EDITED_ABOVE.slice(moved.start, moved.end),
  "cache is invalidated",
);

// Editing the quoted text away must orphan, not silently re-anchor.
check(
  "rewriting the quoted sentence orphans it",
  locateAnchor(BODY.replace("The cache is invalidated on write.", "Writes go straight through."), anchor),
  { status: "orphaned" },
);

// A repeated phrase resolves by context.
const REPEATED = "see below for detail\n\nmiddle\n\nsee below for caveats";
const secondAt = REPEATED.lastIndexOf("see below");
const second = makeAnchor(REPEATED, secondAt, secondAt + "see below".length);
const found = locateAnchor(REPEATED, second);
check("a repeated phrase resolves to the right one", found.start, secondAt);

// ...and refuses when it genuinely cannot tell.
const IDENTICAL = "xx yy\nxx yy";
const ambiguous = locateAnchor(IDENTICAL, { quote: "xx", prefix: "", suffix: " yy" });
check("identical context is ambiguous, not a guess", ambiguous.status, "ambiguous");

// Ordering for the rail.
const rows = [
  { id: "closer", anchor: makeAnchor(BODY, BODY.indexOf("Closer"), BODY.indexOf("Closer") + 6) },
  { id: "gone", anchor: { quote: "text that never existed", prefix: "", suffix: "" } },
  { id: "intro", anchor: makeAnchor(BODY, 0, 5) },
  { id: "thread", anchor: null },
];
check(
  "the rail orders by position, orphans last",
  orderByAnchor(BODY, rows).map((r) => r.row.id),
  ["intro", "closer", "gone", "thread"],
);

console.log(failures ? `\n${failures} FAILED` : "\nall passed");
process.exit(failures ? 1 : 0);
