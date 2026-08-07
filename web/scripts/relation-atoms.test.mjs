/**
 * Unit cases for relation-qualified atoms in the roles matrix (RADD-939).
 *
 * These two functions are the whole semantic contract between the matrix and
 * the server's `relations_held` / `relation_contains`, and getting them wrong
 * is SILENT: the first version returned a single value, which would have
 * dropped `item.read@participant` off the Baseline the moment anyone touched
 * that row — no error, no visible change, just a narrower floor for everyone on
 * the instance. That is the case this file exists for.
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "relatoms-"));
const file = join(dir, "permissions.ts");
writeFileSync(file, readFileSync("web/src/lib/types/permissions.ts", "utf8"));
const { heldRelations, withRelations, RELATION_ANY } = await import(file);

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

// The seeded Baseline, which is the shape that matters most.
const BASELINE = [
  "comment.delete@own",
  "worklog.delete@own",
  "attachment.delete@own",
  "label.read",
  "canned.read",
  "team.read",
  "cardpreset.read",
  "item.read@own",
  "item.read@participant",
  "comment.write@own",
  "comment.write@participant",
];

check("unheld atom reads as no relations", heldRelations(BASELINE, "item.update"), []);
check("unqualified atom reads as `any`", heldRelations(BASELINE, "label.read"), [RELATION_ANY]);
check(
  "an atom held under TWO qualifiers reports both",
  heldRelations(BASELINE, "item.read"),
  ["own", "participant"],
);
check(
  "a prefix collision is not a match (item.read vs item.read_internal)",
  heldRelations(["item.read_internal@own"], "item.read"),
  [],
);

check(
  "setting relations replaces every prior form of that atom",
  withRelations(["item.read@own", "item.read@participant", "label.read"], "item.read", ["team"]),
  ["label.read", "item.read@team"],
);
check(
  "clearing drops every form",
  withRelations(["item.read@own", "item.read@participant", "label.read"], "item.read", []),
  ["label.read"],
);
check(
  "`any` is exclusive — it subsumes the qualifiers, so it replaces them",
  withRelations(["item.read@own"], "item.read", [RELATION_ANY, "own"]),
  ["item.read"],
);
check(
  "several qualifiers round-trip",
  heldRelations(withRelations([], "item.read", ["own", "participant"]), "item.read"),
  ["own", "participant"],
);
check(
  "other atoms keep their order and their qualifiers",
  withRelations(BASELINE, "item.read", ["own"]),
  [
    "comment.delete@own",
    "worklog.delete@own",
    "attachment.delete@own",
    "label.read",
    "canned.read",
    "team.read",
    "cardpreset.read",
    "comment.write@own",
    "comment.write@participant",
    "item.read@own",
  ],
);
// The regression proper: an untouched atom must survive editing a DIFFERENT one.
check(
  "editing one atom leaves another's second qualifier alone",
  heldRelations(withRelations(BASELINE, "label.read", []), "comment.write"),
  ["own", "participant"],
);

console.log(failures ? `\n${failures} FAILED` : "\nall passed");
process.exit(failures ? 1 : 0);
