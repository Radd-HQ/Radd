/** The federation's shared singletons, in ONE place: the import map, the SDK remote config, the
 *  host publisher and the shims must agree, and plugin-boundaries.test.mjs holds them to this file.
 *  EAGER = published at boot. LAZY = the editor runtime: the host registers a loader and the shim
 *  awaits it, so a remote gets the host's ProseMirror instances on demand. */

/** [bare specifier remotes import, shim slug] */
export const EAGER_MODULES = [
  ["react", "react"],
  ["react/jsx-runtime", "react-jsx-runtime"],
  ["react-dom", "react-dom"],
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
