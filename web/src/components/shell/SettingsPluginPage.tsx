import { useLocation } from "@tanstack/react-router";
import { SlotId, useSlotMatch, useDisabledNavPaths, Spinner } from "@radd/plugin-sdk";
import { MissingPluginType } from "./MissingPluginType";

/**
 * Host mount point for a plugin's Settings page (spec 94, the `settings.page` slot). The settings
 * layout's catch-all lands here; the plugin whose `settings.page` contribution `match`es the current
 * pathname renders inside the Settings chrome (secondary nav intact). Reactive — spinner until the
 * owning remote loads; a clear "turned off" notice if the page has been disabled (per-user or
 * instance-wide) rather than an endless spinner. The settings tree names no plugin.
 */
export function SettingsPluginPage() {
  const pathname = useLocation({ select: (l) => l.pathname });
  const match = useSlotMatch(SlotId.settingsPage, pathname);
  const disabled = useDisabledNavPaths().has(pathname);
  if (!match) {
    if (disabled) return <MissingPluginType typeKey={pathname} kind="page" disabled />;
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "4rem" }}>
        <Spinner />
      </div>
    );
  }
  return <div style={{ padding: "1.5rem" }}>{match.contribution.render({ path: pathname })}</div>;
}
