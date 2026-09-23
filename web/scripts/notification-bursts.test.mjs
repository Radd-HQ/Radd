/**
 * RADD-1294: consecutive notifications that say the same thing collapse into one
 * inbox row — and ONLY neighbours do, so the inbox stays in time order.
 *
 * Run: node --test web/scripts/notification-bursts.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "bursts-"));
const file = join(dir, "notification-bursts.ts");
// The module imports only a type; strip it so plain node can load the file.
writeFileSync(file, readFileSync("web/src/lib/notification-bursts.ts", "utf8").replace(/^import type .*$/m, ""));
const { groupNotificationBursts } = await import(file);

const n = (id, type, actor, target, extra = {}) => ({
  id, type, actor: actor ? { id: actor, name: actor } : null, item_id: null, detail: { page_id: target }, read: false, ...extra,
});

test("a burst of the same edit by the same person on the same page is one row", () => {
  const bursts = groupNotificationBursts([n("1", "page_updated", "hj", "p1"), n("2", "page_updated", "hj", "p1"), n("3", "page_updated", "hj", "p1")]);
  assert.equal(bursts.length, 1);
  assert.deepEqual(bursts[0].members.map((m) => m.id), ["1", "2", "3"]);
});

test("only neighbours merge: edit, comment, edit stays three rows", () => {
  const bursts = groupNotificationBursts([n("1", "page_updated", "hj", "p1"), n("2", "commented", "hj", "p1"), n("3", "page_updated", "hj", "p1")]);
  assert.equal(bursts.length, 3);
});

test("a different person, target or kind breaks the run", () => {
  assert.equal(groupNotificationBursts([n("1", "page_updated", "hj", "p1"), n("2", "page_updated", "ab", "p1")]).length, 2);
  assert.equal(groupNotificationBursts([n("1", "page_updated", "hj", "p1"), n("2", "page_updated", "hj", "p2")]).length, 2);
});

test("notifications with no target never merge", () => {
  assert.equal(groupNotificationBursts([n("1", "automation", null, undefined), n("2", "automation", null, undefined)]).length, 2);
});
