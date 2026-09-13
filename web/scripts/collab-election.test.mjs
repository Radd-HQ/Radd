/**
 * Unit cases for the collab saver election + presence model (spec 122).
 *
 * `electSaver` is the whole agreement between clients about who writes the
 * page: it runs on every tab from the same awareness map with no round trip,
 * so two tabs that computed different answers would double-save or never
 * save — and nothing on the wire would say so. The model file has no imports
 * for exactly this reason: it loads under node as-is.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "collab-"));
const file = join(dir, "model.ts");
writeFileSync(file, readFileSync("web/src/components/editor/collab/model.ts", "utf8"));
const { electSaver, presenceSnapshot, CollabRole, EMPTY_PRESENCE } = await import(file);

const ann = { id: "u-ann", name: "Ann", color: "var(--chart-todo)", emoji: null };
const bob = { id: "u-bob", name: "Bob", color: "#336699", emoji: "🦊" };
const editor = (user) => ({ user, role: CollabRole.editor });
const observer = (user) => ({ user, role: CollabRole.observer });

test("the saver is the connected editor with the lowest client id", () => {
  const states = new Map([
    [42, editor(bob)],
    [7, observer(ann)],
    [19, editor(ann)],
  ]);
  assert.equal(electSaver(states), 19);
});

test("observers never save, even with the lowest id", () => {
  assert.equal(electSaver(new Map([[1, observer(ann)], [2, observer(bob)]])), null);
  assert.equal(electSaver(new Map()), null);
});

test("a departure re-elects by the same rule", () => {
  const states = new Map([[3, editor(ann)], [8, editor(bob)]]);
  assert.equal(electSaver(states), 3);
  states.delete(3);
  assert.equal(electSaver(states), 8);
});

test("iteration order does not matter", () => {
  const a = [[9, editor(bob)], [4, editor(ann)]];
  const b = [[4, editor(ann)], [9, editor(bob)]];
  assert.equal(electSaver(a), electSaver(b));
});

test("states without a role, or null states, are not editors", () => {
  const states = new Map([
    [1, null],
    [2, { user: ann }],
    [3, { user: bob, role: "something-else" }],
    [5, editor(bob)],
  ]);
  assert.equal(electSaver(states), 5);
});

test("presence folds several tabs of one account into one person", () => {
  const states = new Map([
    [30, observer(ann)],
    [10, editor(bob)],
    [20, editor(ann)],
  ]);
  const snapshot = presenceSnapshot(states, "u-ann");
  assert.deepEqual(
    snapshot.people.map((person) => [person.user.id, person.role, person.clientIds, person.self]),
    [
      ["u-bob", CollabRole.editor, [10], false],
      ["u-ann", CollabRole.editor, [20, 30], true],
    ],
  );
  assert.equal(snapshot.saver, 10);
});

test("a person is an editor if ANY of their tabs edits", () => {
  const states = new Map([[1, observer(ann)], [2, editor(ann)]]);
  const [person] = presenceSnapshot(states, null).people;
  assert.equal(person.role, CollabRole.editor);
});

test("states without a usable user are skipped, not crashed on", () => {
  const states = new Map([
    [1, { role: CollabRole.editor }],
    [2, { user: "ann", role: CollabRole.editor }],
    [3, { user: { id: 5, name: "x" }, role: CollabRole.editor }],
    [4, editor(bob)],
  ]);
  const snapshot = presenceSnapshot(states, null);
  assert.deepEqual(snapshot.people.map((person) => person.user.id), ["u-bob"]);
  // The election still counts every editor state — a peer without a user
  // record is still a client the server accepts writes from.
  assert.equal(snapshot.saver, 1);
});

test("the empty snapshot is what an absent room reports", () => {
  assert.deepEqual(presenceSnapshot(new Map(), null), EMPTY_PRESENCE);
});
