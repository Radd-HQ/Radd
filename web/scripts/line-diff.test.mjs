/** Unit cases for the version diff (RADD-720). */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "linediff-"));
const file = join(dir, "line-diff.ts");
writeFileSync(file, readFileSync("web/src/lib/line-diff.ts", "utf8"));
const { diffLines, collapseUnchanged, diffStats } = await import(file);

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

check("identical text has no changes", diffStats(diffLines("a\nb", "a\nb")), { added: 0, removed: 0 });

check(
  "a changed line is one removal and one addition",
  diffLines("a\nb\nc", "a\nB\nc").map((l) => l.op),
  ["same", "remove", "add", "same"],
);

check(
  "an insertion does not rewrite the lines around it",
  diffLines("a\nc", "a\nb\nc").map((l) => `${l.op}:${l.text}`),
  ["same:a", "add:b", "same:c"],
);

check("a pure deletion", diffStats(diffLines("a\nb\nc", "a\nc")), { added: 0, removed: 1 });

check(
  "line numbers track each side independently",
  diffLines("a\nb", "a\nx\nb").map((l) => [l.op, l.oldLine, l.newLine]),
  [["same", 1, 1], ["add", null, 2], ["same", 2, 3]],
);

// The reason collapsing exists: a one-word fix in a long page.
const long = Array.from({ length: 60 }, (_, i) => `line ${i}`).join("\n");
const edited = long.replace("line 30", "line thirty");
const collapsed = collapseUnchanged(diffLines(long, edited));
check(
  "long unchanged stretches collapse",
  collapsed.filter((r) => r.op === "skip").length > 0,
  true,
);
check(
  "and the change itself survives",
  collapsed.some((r) => r.op === "add" && r.text === "line thirty"),
  true,
);
check(
  "a 60-line page with one edit renders far fewer than 60 rows",
  collapsed.length < 20,
  true,
);

check("appending to an empty document", diffStats(diffLines("", "hello")), { added: 1, removed: 1 });

console.log(failures ? `\n${failures} FAILED` : "\nall passed");
process.exit(failures ? 1 : 0);
