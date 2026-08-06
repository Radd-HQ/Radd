import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Bell, PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";
import { openCommandPalette } from "../CommandPalette";
import { RoutePath } from "../../lib/constants";
import { useCurrentUser } from "../../lib/hooks";
import { notificationsBadgeQuery } from "../../lib/queries";
import { Avatar } from "../Avatar";
import { RaddTile } from "../RaddMark";
import { toggleInboxPeek } from "./InboxPeek";
import { useSidebarPrefs } from "./sidebar-prefs";
import { useTopBarSlotHost } from "./TopBarSlot";
import { modShortcut } from "../../lib/platform";

/**
 * The global top bar, FIRST row (Cairn-inspired), full viewport width: the
 * sidebar toggle + brand on the left, the prominent QUERY BAR in the middle —
 * a view page portals its live SLQ filter here (TopBarQuery); everything else
 * gets the search-the-app pill that opens the palette — and the profile
 * avatar on the right. Pinned tabs live on the SECOND row (PinsBar).
 */
export function TopBar() {
  const { setEl, occupied } = useTopBarSlotHost();
  const { prefs, toggleRail } = useSidebarPrefs();
  const user = useCurrentUser();
  const railed = prefs.railCollapsed;

  return (
    // relative z-50: the bar hosts floating UI (autocomplete, validation
    // hints) that must paint OVER everything below — the pins row (z-[45]),
    // sticky in-page headers and plugin-contributed header widgets (z-40) —
    // and a TIE loses to later DOM order. Modals/palette/peek are also z-50
    // but render AFTER <main>, so they still cover the bar — the tie resolves
    // correctly there.
    <div className="relative z-50 flex h-12 shrink-0 items-center gap-3 border-b border-subtle bg-base px-4">
      <button
        type="button"
        onClick={toggleRail}
        aria-expanded={!railed}
        aria-label={railed ? "Expand sidebar" : "Collapse sidebar"}
        title={railed ? "Expand sidebar" : "Collapse sidebar"}
        className="cursor-pointer rounded-md p-1 text-fg-muted hover:bg-overlay hover:text-fg focus-visible:outline-2 focus-visible:outline-focus"
      >
        {railed ? <PanelLeftOpen size={16} aria-hidden /> : <PanelLeftClose size={15} aria-hidden />}
      </button>
      <Link
        to={RoutePath.home}
        className="flex shrink-0 items-center gap-2 rounded-md focus-visible:outline-2 focus-visible:outline-focus"
      >
        <RaddTile className="size-5 rounded" />
        <span className="hidden text-sm font-semibold text-heading sm:inline">Radd</span>
      </Link>

      {/* The query slot: filled by the page (view SLQ bar) or the palette pill. */}
      <div ref={setEl} className={occupied ? "min-w-0 flex-1" : "hidden"} />
      {!occupied && (
        <button
          type="button"
          onClick={openCommandPalette}
          className="flex min-w-0 flex-1 cursor-text items-center gap-2 rounded-md border border-subtle bg-surface px-3 py-1.5 text-left text-[13px] text-fg-faint transition-colors hover:border-strong focus-visible:outline-2 focus-visible:outline-focus"
        >
          <Search size={13} aria-hidden className="shrink-0" />
          <span className="truncate">Search issues, docs — or ask…</span>
          <kbd className="ml-auto shrink-0 rounded border border-strong px-1.5 font-mono text-[10px] text-fg-muted">
            {modShortcut('K')}
          </kbd>
        </button>
      )}

      <InboxBell />
      {user && (
        <Link
          to={RoutePath.settingsProfile}
          title={`${user.name} — profile`}
          className="shrink-0 rounded-full focus-visible:outline-2 focus-visible:outline-focus"
        >
          <Avatar user={user} size="sm" />
        </Link>
      )}
    </div>
  );
}

/** The notifications bell: unread badge + click-to-peek (InboxPeek drawer). */
function InboxBell() {
  const { data } = useQuery(notificationsBadgeQuery);
  const unread = data?.unread_count ?? 0;
  return (
    <button
      type="button"
      onClick={toggleInboxPeek}
      aria-label={unread > 0 ? `Inbox, ${unread} unread` : "Inbox"}
      title={unread > 0 ? `Inbox — ${unread} unread` : "Inbox"}
      className="relative shrink-0 cursor-pointer rounded-md p-1.5 text-fg-muted hover:bg-overlay hover:text-fg focus-visible:outline-2 focus-visible:outline-focus"
    >
      <Bell size={16} aria-hidden />
      {unread > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-white">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </button>
  );
}
