// RADD-1527: a chunk that fails to load reloads the tab onto the new build, ONCE.
//   node --test web/scripts/stale-build.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { importTs } from "./lib/load-ts.mjs";

const { shouldReloadForStaleBuild, buildIsStale, STALE_BUILD_RELOAD_WINDOW_MS } = await importTs("web/src/lib/stale-build.ts");

test("the first chunk failure reloads; a second inside the window does not loop", () => {
  const now = 1_700_000_000_000;
  assert.equal(shouldReloadForStaleBuild(null, now), true);
  assert.equal(shouldReloadForStaleBuild(now - 1_000, now), false, "a broken build must not reload forever");
  assert.equal(shouldReloadForStaleBuild(now - STALE_BUILD_RELOAD_WINDOW_MS, now), false);
  assert.equal(shouldReloadForStaleBuild(now - STALE_BUILD_RELOAD_WINDOW_MS - 1, now), true, "a later deploy reloads again");
});

test("only a build the server has moved on from is stale", () => {
  const shell = (entry) => `<!doctype html><script type="module" src="${entry}"></script>`;
  assert.equal(buildIsStale("/assets/index-OLD.js", shell("/assets/index-NEW.js")), true);
  // Same build: the chunk failed for another reason (a plugin bundle down) — do not reload.
  assert.equal(buildIsStale("/assets/index-NEW.js", shell("/assets/index-NEW.js")), false);
  // A dev server has no hashed entry: never reload on its behalf.
  assert.equal(buildIsStale(null, shell("/assets/index-NEW.js")), false);
});
