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
import { useRealtime } from "../lib/realtime";

/**
 * Authenticated app shell (Cairn-inspired bands): two FULL-WIDTH bars — the
 * top bar (brand, query slot, avatar) then the pins row (pinned tabs + the
 * always-there New item button) — with the sidebar + content split UNDER
 * them. Plus the global toast stack (403 permission surprises surface here
 * from the api client).
 * The auth gate lives in this route's beforeLoad (see router.tsx).
 * One realtime socket per shell keeps every surface live (spec 27).
 * StorageChoiceProvider hosts the one "where should this file be stored?"
 * modal every upload seam awaits (spec 102).
 * Routes size themselves with `h-full` against the outlet wrapper — the two
 * bars own the top of the viewport, so `h-screen` inside a route would
 * overflow by exactly their height.
 */
export function AppLayout() {
  useRealtime();
  return (
    <StorageChoiceProvider>
      <TopBarSlotProvider>
        <div className="flex h-dvh flex-col bg-base text-fg">
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
