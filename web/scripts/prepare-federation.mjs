/**
 * Prepare the workspace for a federation build (spec 94). Idempotent; run before building the host
 * or any remote. node_modules is gitignored, so the @radd/plugin-sdk workspace link must be
 * (re)created here rather than relying on `npm install` (which doesn't reliably link workspaces in
 * this environment). Also (re)generates the shared-singleton shims.
 */
import { existsSync, mkdirSync, rmSync, symlinkSync, lstatSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { execFileSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(here, "..");

function ensureLink(linkPath, target) {
  try {
    if (existsSync(linkPath) || lstatSync(linkPath, { throwIfNoEntry: false })) {
      rmSync(linkPath, { recursive: true, force: true });
    }
  } catch {
    /* not present */
  }
  symlinkSync(target, linkPath, "dir");
  console.log(`  linked ${linkPath} -> ${target}`);
}

// web/node_modules/@radd/plugin-sdk -> ../../packages/plugin-sdk
const scopeDir = resolve(webRoot, "node_modules/@radd");
mkdirSync(scopeDir, { recursive: true });
ensureLink(resolve(scopeDir, "plugin-sdk"), "../../packages/plugin-sdk");

// Regenerate the shared-singleton shims.
execFileSync(process.execPath, [resolve(here, "gen-shared-shims.mjs")], { stdio: "inherit" });

console.log("federation workspace prepared.");
