// RADD-1518: the type scale is ONE ladder of tokens on the root. An arbitrary `text-[NNpx]` anywhere
// the host's stylesheet is built from (the SPA, the plugin SDK, every core plugin's bundled UI) would
// put a size back outside the ladder, where the next bump cannot reach it.
//   node --test web/scripts/type-scale.test.mjs   (from the repo root)
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const ROOTS = ["web/src", "web/packages/plugin-sdk/src", "server/src/radd/modules"];
const SOURCE = /\.(tsx|ts)$/;
const PX_SIZE = /text-\[\d+px\]/g;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "dist") continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (SOURCE.test(name)) yield path;
  }
}

test("no arbitrary pixel text size survives outside the type-scale tokens", () => {
  const offenders = [];
  for (const root of ROOTS) {
    for (const file of walk(root)) {
      const hits = readFileSync(file, "utf8").match(PX_SIZE);
      if (hits) offenders.push(`${file}: ${[...new Set(hits)].join(" ")}`);
    }
  }
  assert.deepEqual(offenders, [], `use text-nano/micro/meta/xs/row/sm instead:\n${offenders.join("\n")}`);
});

test("the ladder is defined once, on the root theme, and never inside a theme block", () => {
  const css = readFileSync("web/src/index.css", "utf8");
  for (const token of ["--text-nano", "--text-micro", "--text-meta", "--text-xs", "--text-row", "--text-sm"]) {
    const definitions = css.match(new RegExp(`^\\s*${token}:`, "gm")) ?? [];
    assert.equal(definitions.length, 1, `${token} must be defined exactly once`);
  }
  const lightBlock = css.slice(css.indexOf("html.light {"));
  assert.doesNotMatch(lightBlock, /--text-(nano|micro|meta|xs|row|sm)\b/, "a size token inside html.light would differ by palette");
});
