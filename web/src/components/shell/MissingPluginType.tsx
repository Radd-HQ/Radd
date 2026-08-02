/**
 * Shown where a plugin-contributed surface can't render:
 *  - a saved view / dashboard widget references a plugin TYPE that's no longer available because the
 *    plugin was disabled or uninstalled (spec 94), or
 *  - a plugin page/component has been TURNED OFF via its per-contribution toggle (`disabled`) — the
 *    plugin is still installed, but this piece is switched off (per-user or instance-wide).
 * Either way we replace a broken/empty/endless-spinner render with a clear explanation.
 */
export function MissingPluginType({
  typeKey,
  kind,
  disabled = false,
}: {
  typeKey: string;
  kind: "view" | "widget" | "page";
  disabled?: boolean;
}) {
  return (
    <div
      data-plugin-missing={disabled ? undefined : kind}
      data-plugin-disabled={disabled ? kind : undefined}
      className="m-4 rounded-lg border border-dashed border-amber-500/40 bg-amber-500/5 p-6 text-center text-sm text-amber-300"
    >
      {disabled ? (
        <>
          This {kind} has been turned off.
          <span className="mt-1 block text-xs text-amber-300/70">
            Re-enable it on your Profile, or ask an instance admin if it was disabled for everyone.
          </span>
        </>
      ) : (
        <>
          The “{typeKey}” {kind} type is no longer available — the plugin that provided it was
          disabled or uninstalled.
          <span className="mt-1 block text-xs text-amber-300/70">Check with your instance admin.</span>
        </>
      )}
    </div>
  );
}
