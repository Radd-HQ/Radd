// One date control (RADD-1563): a bare `<input type="date">` is the SDK's
// DateInput and nothing else. Seven hand-styled copies had drifted into four
// looks, two of them pinning a dark picker onto the light theme.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { test } from "node:test";

const ROOT = new URL("../..", import.meta.url).pathname;
const TREES = ["web/src", "web/packages/plugin-sdk/src", "server/src/radd/modules"];
const OWNER = "web/packages/plugin-sdk/src/DateField.tsx";

function* sources(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "dist") continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* sources(path);
    else if (path.endsWith(".tsx")) yield path;
  }
}

test("a bare date input is the SDK's DateInput", () => {
  const offenders = [];
  let scanned = 0;
  for (const tree of TREES) {
    for (const path of sources(join(ROOT, tree))) {
      scanned += 1;
      const file = relative(ROOT, path);
      if (file === OWNER) continue;
      const text = readFileSync(path, "utf8");
      // A lowercase <input …> element carrying type="date"; <TextField type="date"> is the labelled form.
      for (const match of text.matchAll(/<input\b(?:(?!\/>)[\s\S])*?\/>/g)) {
        if (/type="date"/.test(match[0])) offenders.push(file);
      }
      if (/\[color-scheme:(dark|light)\]/.test(text)) offenders.push(`${file} (pinned color-scheme)`);
    }
  }
  // Not vacuous: the scan saw the tree, and the owner really holds the input.
  assert.ok(scanned > 300, `only ${scanned} files scanned`);
  assert.match(readFileSync(join(ROOT, OWNER), "utf8"), /type="date"/);
  assert.deepEqual(offenders, []);
});
