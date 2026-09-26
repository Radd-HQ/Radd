/**
 * Generate the "shared singleton" shim modules for native-ESM federation (spec 94).
 *
 * Each remote build EXTERNALIZES the shared deps, keeping bare `import ... from "react"` specifiers.
 * The host's index.html import map maps those specifiers to these generated `/shared/*.js` files,
 * each of which re-exports the host's SINGLETON instance read from `globalThis.__RADD_SHARED__`
 * (populated by web/src/shared-runtime.ts at boot). Result: one React, one query client, one slot
 * registry across host + every remote — no module-federation plugin, just standard ES modules.
 *
 * Run: `node scripts/gen-shared-shims.mjs` (idempotent; re-run after upgrading a shared dep).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { SDK_SHIM, lazyShimSource, sdkShimSource, shimSource, valueExports } from "./sdk-exports.mjs";
import { EAGER_MODULES, LAZY_MODULES } from "./shared-modules.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../public/shared");

// The list lives in shared-modules.mjs, to which the boundary test holds the import map, the SDK's
// remote build config and the host's publisher.

// The SDK's names are read from its source (`sdk-exports.mjs`), not listed here: a hand-kept list
// drifted silently, and a missing name is `undefined` in every remote.

mkdirSync(outDir, { recursive: true });

for (const [id, slug] of EAGER_MODULES) {
  const mod = await import(id);
  const names = Object.keys(mod);
  const hasDefault = "default" in mod;
  writeFileSync(resolve(outDir, `${slug}.js`), shimSource(id, names, hasDefault));
  console.log(`  ${id} -> shared/${slug}.js (${names.length} exports)`);
}

// The editor runtime (RADD-1397). The names come from the module the HOST publishes — the one a
// remote's import resolves to at runtime.
for (const [id, slug, hostSpecifier] of LAZY_MODULES) {
  const names = Object.keys(await import(hostSpecifier));
  writeFileSync(resolve(outDir, `${slug}.js`), lazyShimSource(id, names));
  console.log(`  ${id} -> shared/${slug}.js (${names.length} exports, loaded with the editor)`);
}

writeFileSync(SDK_SHIM, sdkShimSource());
console.log(`  @radd/plugin-sdk -> shared/radd-plugin-sdk.js (${valueExports().length} exports)`);
console.log("shared shims generated in", outDir);
