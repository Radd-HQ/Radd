/**
 * The wiki's tree walks (RADD-1421). "Print with subpages" listed pages in the server's order
 * while the rail, `radd:toc` and `radd:children` natural-sort siblings, because the print view
 * carried its own unsorted walk. Every walk now goes through `view/page-tree.ts`; these cases pin
 * its order and that no caller keeps a private copy.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const UI = "server/src/radd/modules/pages/ui/src";
const dir = mkdtempSync(join(tmpdir(), "page-tree-"));
const file = join(dir, "page-tree.ts");
writeFileSync(file, readFileSync(`${UI}/view/page-tree.ts`, "utf8"));
const { ancestorIds, buildTree, descendants, subtreeIds } = await import(file);

const row = (id, parent_id, title) => ({ id, parent_id, title });
// Listed the way the server hands them over — by position, which is not the order people read.
const ROWS = [
  row("root", null, "Releases"),
  row("r10", "root", "0.10.0"),
  row("r2", "root", "0.2.0"),
  row("r9", "root", "0.9.1"),
  row("r2b", "r2", "Notes b"),
  row("r2a", "r2", "notes A"),
  row("other", null, "Another root"),
];

const flatten = (nodes, level = 0) =>
  nodes.flatMap((node) => [{ id: node.row.id, level }, ...flatten(node.children, level + 1)]);

test("descendants list siblings in natural order, depth first", () => {
  assert.deepEqual(
    descendants(ROWS, "root").map(({ page, level }) => [page.title, level]),
    [["0.2.0", 0], ["notes A", 1], ["Notes b", 1], ["0.9.1", 0], ["0.10.0", 0]],
  );
});

test("the print walk and the rail's tree agree on order", () => {
  const rail = flatten(buildTree(ROWS)).filter(({ id }) => id !== "root" && id !== "other");
  const print = descendants(ROWS, "root").map(({ page, level }) => ({ id: page.id, level: level + 1 }));
  assert.deepEqual(print, rail);
});

test("depth, missing roots and bad rows are bounded", () => {
  assert.deepEqual(descendants(ROWS, "root", 1).map(({ page }) => page.id), ["r2", "r9", "r10"]);
  assert.deepEqual(descendants(ROWS, null), []);
  const cyclic = [row("a", "b", "A"), row("b", "a", "B")];
  assert.deepEqual([...subtreeIds(cyclic, "a")].sort(), ["a", "b"]);
  assert.equal(ancestorIds(new Map([["a", "b"], ["b", "a"]]), "a", 5).length, 5);
});

test("subtrees and ancestors", () => {
  assert.deepEqual([...subtreeIds(ROWS, "r2")].sort(), ["r2", "r2a", "r2b"]);
  const parentOf = new Map(ROWS.map((r) => [r.id, r.parent_id]));
  assert.deepEqual(ancestorIds(parentOf, "r2a", ROWS.length), ["r2", "root"]);
  assert.deepEqual(ancestorIds(parentOf, "root", ROWS.length), []);
});

test("an orphan (parent not listed) is a root of the rail", () => {
  assert.deepEqual(
    buildTree([row("x", "gone", "Orphan"), row("y", null, "Top")]).map((n) => n.row.id),
    ["x", "y"],
  );
});

test("no pages file keeps its own tree walk", () => {
  const files = [];
  const walk = (path) => {
    for (const name of readdirSync(path)) {
      const child = join(path, name);
      if (statSync(child).isDirectory()) walk(child);
      else if (/\.tsx?$/.test(name) && !child.endsWith("view/page-tree.ts")) files.push(child);
    }
  };
  walk(UI);
  const own = files.filter((path) =>
    /function (descendants|buildTree|subtreeIds|comparePagesNaturally)\b/.test(readFileSync(path, "utf8")),
  );
  assert.deepEqual(own, []);
  assert.match(readFileSync(`${UI}/routes/PagePrintPage.tsx`, "utf8"), /import \{ descendants \} from "\.\.\/view\/page-tree"/);
});
