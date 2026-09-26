/** A pinned link tab takes its icon from `LINK_ICONS` by path prefix (RADD-1420).
 *
 * The wiki moved from `/docs` to `/pages` (spec 124) and the table kept `/docs`, so a pinned page
 * drew the generic link icon. Checked against the address the pages plugin itself builds, so the
 * next move of that route fails here instead of silently falling back.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const pinsBar = readFileSync("web/src/components/shell/PinsBar.tsx", "utf8");
const links = readFileSync("server/src/radd/modules/pages/ui/src/links.ts", "utf8");

const pageRoute = Object.fromEntries(
  [...links.match(/export const PageRoute = \{([\s\S]*?)\} as const;/)[1].matchAll(/^\s*(\w+): "([^"]+)",/gm)]
    .map(([, name, path]) => [name, path]),
);

const table = pinsBar.match(/const LINK_ICONS[^=]*=\s*\[([\s\S]*?)\n\];/)[1];
const entries = [...table.matchAll(/\[\s*(?:"([^"]+)"|PageRoute\.(\w+))\s*,\s*(\w+)\s*\]/g)].map(
  ([, literal, routeName, icon]) => [literal ?? pageRoute[routeName], icon],
);

const iconFor = (path) => entries.find(([prefix]) => path.startsWith(prefix))?.[1] ?? "Link2";

test("a pinned wiki page gets the wiki icon, not the generic link", () => {
  assert.ok(entries.length > 5, "LINK_ICONS was parsed");
  assert.equal(pageRoute.pages, "/pages");
  assert.equal(iconFor(`${pageRoute.pages}/eng/onboarding`), "BookOpen");
  assert.equal(iconFor(pageRoute.pages), "BookOpen");
});
