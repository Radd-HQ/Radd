/** Build the whole frontend: prepare-federation, the host (tsc -b + vite build), then every remote
 *  plugin UI into its own `ui/dist/`. `--host-only` skips the remotes. */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { discover, repoRoot, webRoot } from "./plugin-packages.mjs";

const here = dirname(fileURLToPath(import.meta.url));
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
