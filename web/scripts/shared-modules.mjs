/**
 * The shared singletons of the native-ESM federation (spec 94), in ONE place.
 *
 * A remote externalizes each of these and keeps the bare specifier; the host's index.html import
 * map resolves it to `/shared/<slug>.js`, a generated shim re-exporting the host's own instance.
 * Four things must agree on the list — the import map, the SDK's remote build config
 * (`packages/plugin-sdk/vite.mjs`), the host's publisher (`src/shared-runtime.ts`) and the shims
 * (`gen-shared-shims.mjs`) — and `plugin-boundaries.test.mjs` holds them to this file.
 *
 *   - EAGER modules are published at boot: React, the router, the query client, the SDK.
 *   - LAZY modules are the editor runtime (RADD-1397). The host loads its editor engine on first
 *     use, so publishing it at boot would ship it to every page; instead the host registers a
 *     loader, and the shim awaits it (top-level await). A remote that imports one loads the
 *     host's copy on demand — the SAME module instances the host's editor runs, which is what
 *     makes a plugin's ProseMirror plugins, keys and nodes work in the host's editor.
 */

/** [bare specifier remotes import, shim slug] */
export const EAGER_MODULES = [
  ["react", "react"],
  ["react/jsx-runtime", "react-jsx-runtime"],
  ["react/jsx-dev-runtime", "react-jsx-dev-runtime"],
  ["react-dom", "react-dom"],
  ["react-dom/client", "react-dom-client"],
  ["@tanstack/react-query", "tanstack-react-query"],
  ["@tanstack/react-router", "tanstack-react-router"],
];

/** [bare specifier remotes import, shim slug, the specifier the HOST loads it through] */
export const LAZY_MODULES = [
  ["prosemirror-model", "prosemirror-model", "@milkdown/kit/prose/model"],
  ["prosemirror-state", "prosemirror-state", "@milkdown/kit/prose/state"],
  ["prosemirror-view", "prosemirror-view", "@milkdown/kit/prose/view"],
];

export const SDK_MODULE = ["@radd/plugin-sdk", "radd-plugin-sdk"];

/** Every specifier a remote must leave external, in import-map order. */
export const SHARED_SPECIFIERS = [...EAGER_MODULES, SDK_MODULE, ...LAZY_MODULES].map(([id]) => id);

/** The import map the host's index.html must carry. */
export function importMap() {
  return Object.fromEntries([...EAGER_MODULES, SDK_MODULE, ...LAZY_MODULES].map(([id, slug]) => [id, `/shared/${slug}.js`]));
}
