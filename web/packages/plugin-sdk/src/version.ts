/**
 * The frontend SDK contract version (docs/plugin-platform.md §9/§14). A plugin's UI is built
 * against a specific major; the host runtime loader refuses to load a remote whose declared
 * `ui_api_version` has a different MAJOR than this — a clean version gate, mirroring the backend
 * `api_version` gate. Bump the major on a breaking SDK change; the minor on additive changes.
 */
export const UI_API_VERSION = "1.0.0";

function major(version: string): number {
  const first = version.split(".")[0];
  const n = Number.parseInt(first ?? "", 10);
  return Number.isNaN(n) ? -1 : n;
}

/**
 * Is a remote built against `pluginUiApiVersion` loadable by this host? Compatible iff the major
 * versions match (semver: a major bump is breaking). An empty/garbage version is incompatible.
 */
export function isUiApiCompatible(pluginUiApiVersion: string): boolean {
  const wanted = major(pluginUiApiVersion);
  if (wanted < 0) return false;
  return wanted === major(UI_API_VERSION);
}
