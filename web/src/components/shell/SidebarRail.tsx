/** The slim (collapsed) sidebar: icon-only destinations, no sections.
 *
 *  Sections (Views / Dashboards / Pages / Cycles / project trees) are dropped on
 *  purpose — they are lists of NAMES, and a name does not survive being reduced
 *  to a 20px glyph. What stays is the fixed set of destinations, which is what
 *  a rail is good at. Everything else is one click away via the search shortcut, which is why
 *  Search is pinned first. */

import { useIsAuthenticated } from "../../lib/hooks";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  BarChart3,
  Clock,
  ConciergeBell,
  House,
  Inbox,
  Layers,
  Search,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { useNavFacts } from "../../lib/nav-facts";
import { RoutePath } from "../../lib/constants";
import { notificationsBadgeQuery } from "../../lib/queries";
import { openCommandPalette } from "../CommandPalette";
import { modShortcut } from "../../lib/platform";

/** Icon-button geometry, shared by rail links and the rail's own buttons. */
export const railButtonClasses =
  "relative flex size-9 items-center justify-center rounded-lg text-fg-secondary " +
  "hover:bg-overlay hover:text-heading focus-visible:outline-2 focus-visible:outline-focus " +
  "[&.active]:bg-elevated [&.active]:text-heading " +
  "[&.active]:before:absolute [&.active]:before:left-0 [&.active]:before:top-1/2 " +
  "[&.active]:before:h-5 [&.active]:before:w-0.5 [&.active]:before:-translate-y-1/2 " +
  "[&.active]:before:rounded-full [&.active]:before:bg-accent [&.active]:before:content-['']";

interface RailDestination {
  to: string;
  icon: LucideIcon;
  label: string;
  exact?: boolean;
}

/** Mirrors the primary destinations of the full sidebar, in the same order.
 * RADD-843: gated per-entry through the SAME useNavFacts predicate the full
 * sidebar consumes — the rail used to gate nothing, the parallel-code-path
 * defect class. */
const DESTINATIONS: RailDestination[] = [
  { to: RoutePath.home, icon: House, label: "My Work", exact: true },
  { to: RoutePath.portal, icon: ConciergeBell, label: "Submission Portal" },
  { to: RoutePath.projects, icon: Layers, label: "Projects", exact: true },
  { to: RoutePath.reports, icon: BarChart3, label: "Reports" },
  { to: RoutePath.timesheet, icon: Clock, label: "Timesheet" },
];

function RailInbox() {
  const { data } = useQuery({ ...notificationsBadgeQuery, enabled: useIsAuthenticated() });
  const unread = data?.unread_count ?? 0;
  return (
    <Link
      to={RoutePath.inbox}
      className={railButtonClasses}
      title={unread > 0 ? `Inbox — ${unread} unread` : "Inbox"}
      aria-label={unread > 0 ? `Inbox, ${unread} unread` : "Inbox"}
      data-pin-label="Inbox"
    >
      <Inbox size={17} aria-hidden />
      {unread > 0 && (
        // A count does not fit at rail width; a dot says "something is waiting"
        // and the tooltip carries the number.
        <span
          className="absolute right-1.5 top-1.5 size-2 rounded-full bg-accent ring-2 ring-base"
          aria-hidden
        />
      )}
    </Link>
  );
}

export function SidebarRail({ pluginNav }: { pluginNav: { key: string; path: string; label: string }[] }) {
  const navFacts = useNavFacts();
  return (
    <nav className="flex flex-1 flex-col items-center gap-1 overflow-y-auto py-2" aria-label="Primary">
      <button
        type="button"
        onClick={openCommandPalette}
        className={`${railButtonClasses} cursor-pointer`}
        title={`Search — ${modShortcut("K")}`}
        aria-label="Search"
      >
        <Search size={17} aria-hidden />
      </button>

      <RailInbox />

      {DESTINATIONS.filter((d) => navFacts.forPath(d.to)).map((d) => (
        <Link
          key={d.to}
          to={d.to}
          activeOptions={d.exact ? { exact: true } : undefined}
          className={railButtonClasses}
          title={d.label}
          aria-label={d.label}
        >
          <d.icon size={17} aria-hidden />
        </Link>
      ))}

      {/* Client-side, same as the full sidebar — a plain <a> here would full-reload. */}
      {pluginNav.map((n) => (
        <Link
          key={n.key}
          to={n.path as never}
          className={railButtonClasses}
          title={n.label}
          aria-label={n.label}
          data-plugin-nav={n.key}
        >
          <Layers size={17} aria-hidden />
        </Link>
      ))}

      <div className="mt-auto pt-2">
        <Link to={RoutePath.settings} className={railButtonClasses} title="Settings" aria-label="Settings">
          <Settings size={17} aria-hidden />
        </Link>
      </div>
    </nav>
  );
}
