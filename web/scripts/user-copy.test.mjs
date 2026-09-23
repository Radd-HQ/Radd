/**
 * RADD-1289: the SPA's visible copy names no spec or ticket.
 *
 * "(spec 121)" in a settings description tells a team lead nothing; internal
 * references belong in comments and commit messages. This strips comments
 * (line, block and JSX) from every web/src source and fails on a spec/RADD
 * reference in what remains — string literals and JSX text.
 *
 * Run: node --test web/scripts/user-copy.test.mjs
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src/", import.meta.url));
const REFERENCE = /\b(?:[Ss]pecs? \d+|RADD-\d+)\b/;

function sources(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(tsx?|mjs)$/.test(name) ? [path] : [];
  });
}

/** Drop comments: block and JSX comments, then `//` comments that are not part of a URL. */
export function withoutComments(code) {
  return code
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`\w])\/\/.*$/gm, "$1");
}

test("comment stripping keeps copy and drops comments", () => {
  const code = `// spec 1\nconst a = "visible spec 2"; /* spec 3 */\n{/* RADD-4 */}\nconst url = "https://x.y/z";`;
  const out = withoutComments(code);
  assert.ok(out.includes("visible spec 2") && out.includes("https://x.y/z"));
  assert.ok(!out.includes("spec 1") && !out.includes("spec 3") && !out.includes("RADD-4"));
});

test("no spec or ticket number in visible SPA copy", () => {
  const offenders = [];
  for (const path of sources(root)) {
    withoutComments(readFileSync(path, "utf8")).split("\n").forEach((line, index) => {
      if (REFERENCE.test(line)) offenders.push(`${path.slice(root.length)}:${index + 1}: ${line.trim().slice(0, 120)}`);
    });
  }
  assert.deepEqual(offenders, [], offenders.join("\n"));
});
