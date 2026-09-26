/**
 * Build the whole federated frontend (spec 94):
 *   1. prepare-federation (link @radd/plugin-sdk into web/node_modules, regenerate /shared shims)
 *   2. host: tsc -b && vite build  ->  web/dist
 *   3. every plugin's colocated UI remote -> that plugin's own `ui/dist/remoteEntry.js`
 *
 * A plugin's UI lives IN the plugin's directory (`<plugin>/ui/`), builtin or external, and builds to
 * `<plugin>/ui/dist/` — which Radd serves at /plugins/<name>/ straight from there. This script
 * discovers every `ui/package.json` under the server modules and the examples, symlinks each ui's
 * node_modules to the shared web toolchain (npm-install is unavailable in this sandbox), and builds
 * it. Run: `node web/scripts/build-all.mjs`. Pass `--host-only` to skip the remotes.
 */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { discover } from "./plugin-packages.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(here, "..");
const repoRoot = resolve(webRoot, "..");
const bin = (name) => resolve(webRoot, "node_modules/.bin", name);
const run = (cmd, args, cwd = webRoot) => execFileSync(cmd, args, { cwd, stdio: "inherit" });

console.log("== prepare federation ==");
run(process.execPath, [resolve(here, "prepare-federation.mjs")]);
const packages = discover();

console.log("\n== build host ==");
run(bin("tsc"), ["-b"]);
run(bin("vite"), ["build"]);

if (process.argv.includes("--host-only")) {
  console.log("\n(host-only) done.");
  process.exit(0);
}

const remoteDirs = packages.filter((p) => p.remote).map((p) => p.dir);
for (const uiDir of remoteDirs) {
  const label = uiDir.replace(repoRoot + "/", "");
  console.log(`\n== build remote: ${label} ==`);
  run(bin("tsc"), ["-p", resolve(uiDir, "tsconfig.json")]);
  run(bin("vite"), ["build"], uiDir);
}

console.log(`\nbuilt host (with ${packages.filter((p) => p.bundled).length} bundled plugin UIs) + ${remoteDirs.length} plugin UI remote(s).`);
