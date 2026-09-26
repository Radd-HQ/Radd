/**
 * The Vite config factory for a Radd plugin UI remote (spec 94), shipped WITH the SDK so a plugin's
 * build config is self-contained via its `@radd/plugin-sdk` dependency — no repo-relative helper.
 * A plugin's `vite.config.mjs` is just:
 *
 *   import { raddRemote } from "@radd/plugin-sdk/vite";
 *   import { dirname } from "node:path";
 *   import { fileURLToPath } from "node:url";
 *   export default raddRemote(dirname(fileURLToPath(import.meta.url)));
 *
 * It externalizes the shared singletons (keeping the bare specifiers the host import map resolves)
 * and emits a single `remoteEntry.js` into the plugin's own `dist/` (served by Radd at
 * /plugins/<name>/ straight from the plugin directory).
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { esmExternalRequirePlugin } from "rolldown/plugins";

/** The deps the host provides as singletons via its index.html import map (`web/scripts/
 *  shared-modules.mjs` is the list; a boundary test holds this set to it). The `prosemirror-*`
 *  modules are the editor runtime (RADD-1397), loaded on demand: a remote that extends the host's
 *  editor must run against the host's instances, never a bundled copy. */
const SHARED = new Set([
  "react",
  "react-dom",
  "react-dom/client",
  "react/jsx-runtime",
  "react/jsx-dev-runtime",
  "@tanstack/react-query",
  "@tanstack/react-router",
  "@radd/plugin-sdk",
  "prosemirror-model",
  "prosemirror-state",
  "prosemirror-view",
]);

/**
 * @param {string} configDir absolute dir of the plugin's ui/ (dirname of its vite.config.mjs)
 * @param {{ entry?: string }} [opts] entry override (default `src/index.tsx`)
 */
export function raddRemote(configDir, opts = {}) {
  return defineConfig({
    // This plugin must own externals; a duplicate rollupOptions.external rule
    // bypasses its conversion of CommonJS requires into browser ESM imports.
    plugins: [react(), esmExternalRequirePlugin({ external: [...SHARED] })],
    // Library mode otherwise leaves this Node global in bundled dependencies
    // (e.g. React Flow's external-store shim), crashing the browser remote.
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      lib: { entry: resolve(configDir, opts.entry ?? "src/index.tsx"), formats: ["es"] },
      rollupOptions: {
        output: {
          entryFileNames: "remoteEntry.js",
          chunkFileNames: "[name].js",
          assetFileNames: "[name][extname]",
        },
      },
      outDir: resolve(configDir, "dist"),
      emptyOutDir: true,
      minify: true,
      target: "es2022",
    },
  });
}
