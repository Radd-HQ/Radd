import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync("web/src/lib/item-interests.ts", "utf8");
const code = stripTypeScriptTypes(source).replaceAll("export ", "");
const { itemInterests } = Function(`${code}; return { itemInterests };`)();
assert.equal(itemInterests(undefined), undefined);
const item = { id: "self", parent: { id: "parent" }, epic: { id: "parent" }, links: {
  incoming: [{ item: { id: "related" } }], outgoing: [{ item: { id: "other" } }],
} };
assert.deepEqual(itemInterests(item), ["self", "parent", "related", "other"]);
item.links.outgoing = Array.from({ length: 129 }, (_, i) => ({ item: { id: String(i) } }));
assert.equal(itemInterests(item), undefined); // too many dependencies => broad, never truncated
console.log("ok exact issue interests retain embedded references and broad fallback");
