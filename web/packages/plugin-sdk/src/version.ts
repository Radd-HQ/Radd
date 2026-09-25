/**
 * The frontend SDK contract version (docs/plugin-platform.md §9/§14). A plugin's UI is built
 * against a specific major; the host runtime loader refuses to load a remote whose declared
 * `ui_api_version` requires a newer version or a different MAJOR — a clean version gate, mirroring the backend
 * `api_version` gate. Bump the major on a breaking SDK change; the minor on additive changes.
 */
export const UI_API_VERSION = "1.7.0";

function versionParts(version: string): number[] | null {
  if (!/^\d+\.\d+(?:\.\d+)?$/.test(version)) return null;
  return version.split(".").map(Number);
}

/** A remote requires its declared SDK version. Same-major older consumers remain compatible. */
export function isUiApiCompatible(pluginUiApiVersion: string): boolean {
  const wanted = versionParts(pluginUiApiVersion);
  const offered = versionParts(UI_API_VERSION)!;
  if (!wanted || wanted[0] !== offered[0]) return false;
  return wanted[1] < offered[1] || (wanted[1] === offered[1] && (wanted[2] ?? 0) <= (offered[2] ?? 0));
}
