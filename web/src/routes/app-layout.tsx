import { Outlet } from "@tanstack/react-router";
import { StorageChoiceProvider } from "../components/attachments/StorageChoiceProvider";
import { CommandPalette } from "../components/CommandPalette";
import { IssuePanel } from "../components/items/IssuePanel";
import { InboxPeek } from "../components/shell/InboxPeek";
import { PinsBar } from "../components/shell/PinsBar";
import { PluginRemotes } from "../components/shell/PluginRemotes";
import { Sidebar } from "../components/shell/Sidebar";
import { TopBar } from "../components/shell/TopBar";
import { TopBarSlotProvider } from "../components/shell/TopBarSlot";
import { ViewAsBanner } from "../components/shell/ViewAsBanner";
import { Toaster } from "../components/Toaster";
import { useIsAuthenticated } from "../lib/hooks";
import { useRealtime } from "../lib/realtime";

/**
 * The app shell: two FULL-WIDTH bars (top bar, pins row) above the sidebar + content split, the
 * toast stack, one realtime socket, and the storage-choice modal every upload awaits. The auth
 * gate is the route's beforeLoad. Routes size with `h-full` against the outlet — `h-screen`
 * would overflow by exactly the two bars' height.
 */
/** The live-update socket, mounted only for a signed-in account (spec 121:
 *  the server closes an unauthenticated socket, and a visitor would otherwise
 *  sit in a reconnect loop). */
function RealtimeBridge() {
  useRealtime();
  return null;
}

export function AppLayout() {
  const authenticated = useIsAuthenticated();
  return (
    <StorageChoiceProvider>
      <TopBarSlotProvider>
        <div className="flex h-dvh flex-col bg-base text-fg">
          {authenticated && <RealtimeBridge />}
          <ViewAsBanner />
          <TopBar />
          <PinsBar />
          <div className="flex min-h-0 flex-1">
            <Sidebar />
            <main className="flex h-full min-w-0 flex-1 flex-col">
              {/* The wrapper owns page scrolling: routes that fill it (`h-full`
                  + internal scroll) never overflow it, and plain-flow routes
                  (inbox, my-work, settings forms) scroll here instead of the
                  window — which the h-screen shell no longer lets scroll. */}
              <div className="min-h-0 flex-1 overflow-y-auto">
                <Outlet />
              </div>
            </main>
          </div>
          <InboxPeek />
          <IssuePanel />
          <CommandPalette />
          <Toaster />
          <PluginRemotes />
        </div>
      </TopBarSlotProvider>
    </StorageChoiceProvider>
  );
}
