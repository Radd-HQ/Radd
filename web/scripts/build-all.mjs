/**
 * Build the whole federated frontend (spec 94):
 *   1. prepare-federation (link @radd/plugin-sdk into web/node_modules, regenerate /shared shims)
 *   2. host: tsc -b && vite build  ->  web/dist
 *   3. every plugin's colocated UI remote -> that plugin's own `ui/dist/remoteEntry.js`
 *
 * A plugin's UI lives IN the plugin's directory (`<plugin>/ui/`), builtin or external, and builds to
 * `<plugin>/ui/dist/` — which Radd serves at /plugins/<name>/ straight from there. This script
 * discovers every `ui/vite.config.mjs` under the server modules and the examples, symlinks each ui's
 * node_modules to the shared web toolchain (npm-install is unavailable in this sandbox), and builds
 * it. Run: `node web/scripts/build-all.mjs`. Pass `--host-only` to skip the remotes.
 */
import { execFileSync } from "node:child_process";
import { readdirSync, existsSync, mkdirSync, rmSync, symlinkSync, lstatSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(here, "..");
const repoRoot = resolve(webRoot, "..");
const sharedNodeModules = resolve(webRoot, "node_modules");
const bin = (name) => resolve(webRoot, "node_modules/.bin", name);
const run = (cmd, args, cwd = webRoot) => execFileSync(cmd, args, { cwd, stdio: "inherit" });

/** Directories to scan for plugin `ui/` remotes: the builtin plugin modules + the examples. */
const SCAN_ROOTS = [
  resolve(repoRoot, "server/src/radd/modules"),
  resolve(repoRoot, "examples"),
];

/** Find every `<dir>/ui` that has a vite.config.mjs (recursively, shallowly for examples). */
function findUiDirs(root, depth = 0) {
  if (!existsSync(root) || depth > 4) return [];
  const out = [];
  for (const e of readdirSync(root, { withFileTypes: true })) {
    if (!e.isDirectory() || e.name === "node_modules" || e.name === "dist") continue;
    const child = resolve(root, e.name);
    if (e.name === "ui" && existsSync(resolve(child, "vite.config.mjs"))) {
      out.push(child);
    } else {
      out.push(...findUiDirs(child, depth + 1));
    }
  }
  return out;
}

function ensureNodeModules(uiDir) {
  const link = resolve(uiDir, "node_modules");
  try {
    if (lstatSync(link, { throwIfNoEntry: false })) rmSync(link, { recursive: true, force: true });
  } catch { /* absent */ }
  symlinkSync(sharedNodeModules, link, "dir");
}

console.log("== prepare federation ==");
run(process.execPath, [resolve(here, "prepare-federation.mjs")]);

console.log("\n== build host ==");
run(bin("tsc"), ["-b"]);
run(bin("vite"), ["build"]);

if (process.argv.includes("--host-only")) {
  console.log("\n(host-only) done.");
  process.exit(0);
}

const uiDirs = SCAN_ROOTS.flatMap((r) => findUiDirs(r)).sort();
for (const uiDir of uiDirs) {
  const label = uiDir.replace(repoRoot + "/", "");
  console.log(`\n== build remote: ${label} ==`);
  ensureNodeModules(uiDir);
  run(bin("tsc"), ["-p", resolve(uiDir, "tsconfig.json")]);
  run(bin("vite"), ["build"], uiDir);
}

console.log(`\nbuilt host + ${uiDirs.length} plugin UI remote(s).`);
