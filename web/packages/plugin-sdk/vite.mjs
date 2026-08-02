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

/** The deps the host provides as singletons via its index.html import map. Keep in sync with it. */
const SHARED = new Set([
  "react",
  "react-dom",
  "react-dom/client",
  "react/jsx-runtime",
  "react/jsx-dev-runtime",
  "@tanstack/react-query",
  "@tanstack/react-router",
  "@radd/plugin-sdk",
]);

/**
 * @param {string} configDir absolute dir of the plugin's ui/ (dirname of its vite.config.mjs)
 * @param {{ entry?: string }} [opts] entry override (default `src/index.tsx`)
 */
export function raddRemote(configDir, opts = {}) {
  return defineConfig({
    plugins: [react()],
    build: {
      lib: { entry: resolve(configDir, opts.entry ?? "src/index.tsx"), formats: ["es"] },
      rollupOptions: {
        external: (id) => SHARED.has(id),
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
