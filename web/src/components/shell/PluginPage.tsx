import { useLocation } from "@tanstack/react-router";
import { SlotId, useSlotMatch, useDisabledNavPaths, Spinner } from "@radd/plugin-sdk";
import { MissingPluginType } from "./MissingPluginType";

/**
 * Host mount point for a plugin's full-page UI (spec 94, the `route.page` slot). The router's
 * catch-all lands here; the plugin whose `route.page` contribution `match`es the current pathname
 * renders its page. Reactive: while the owning remote is still loading, this shows a spinner and
 * swaps to the page the instant the remote registers (no reload). If the page has been TURNED OFF
 * (per-user or instance-wide), we show a clear notice rather than spinning forever. Base views know
 * no plugin — this is the only host code that renders a plugin page, and it names none.
 */
export function PluginPage() {
  const pathname = useLocation({ select: (l) => l.pathname });
  const match = useSlotMatch(SlotId.routePage, pathname);
  const disabled = useDisabledNavPaths().has(pathname);
  if (!match) {
    if (disabled) return <MissingPluginType typeKey={pathname} kind="page" disabled />;
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "4rem" }}>
        <Spinner />
      </div>
    );
  }
  return <>{match.contribution.render({ path: pathname })}</>;
}
