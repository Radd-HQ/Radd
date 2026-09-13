// The roadmap draft fold (RADD-1151): a plan's patch that carries the full item
// draws a row the base set lacks — the same INSERT a tray drop uses — while a
// patch without one stays a no-op for an absent item (nothing to draw).
//
//   node --test web/scripts/roadmap-draft.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const dir = mkdtempSync(join(tmpdir(), "draft-ops-"));
const file = join(dir, "draft-ops.ts");
writeFileSync(file, readFileSync("web/src/components/roadmap/model/draft-ops.ts", "utf8"));
const { applyOp } = await import(file);

const epic = { id: "e1", key: "PX-1", kind: "epic", start_date: "2026-09-01", target_date: "2026-09-20" };
const child = { id: "c1", key: "PX-2", kind: "issue", parent: { id: "e1", key: "PX-1" }, start_date: null, target_date: null };

test("a patch carrying the item inserts a row the base set lacks", () => {
  const drafted = applyOp([epic], {
    kind: "patch",
    label: "Bring PX-1's children in",
    patches: [{ itemId: "c1", after: { start_date: "2026-09-01", target_date: "2026-09-01" }, insert: child }],
  });
  assert.equal(drafted.length, 2);
  const row = drafted.find((item) => item.id === "c1");
  assert.equal(row.start_date, "2026-09-01");
  assert.equal(row.target_date, "2026-09-01");
  assert.equal(row.parent.id, "e1");
});

test("a patch without the item leaves an absent row undrawn", () => {
  const drafted = applyOp([epic], {
    kind: "patch",
    label: "Edit 1 item",
    patches: [{ itemId: "c1", after: { start_date: "2026-09-01" } }],
  });
  assert.equal(drafted.length, 1);
});

test("a patch on a present row edits it in place", () => {
  const drafted = applyOp([epic, { ...child, start_date: "2026-09-02", target_date: "2026-09-03" }], {
    kind: "patch",
    label: "Move PX-2",
    patches: [{ itemId: "c1", after: { start_date: "2026-09-05" }, insert: child }],
  });
  assert.equal(drafted.length, 2);
  assert.equal(drafted[1].start_date, "2026-09-05");
  assert.equal(drafted[1].target_date, "2026-09-03");
});
