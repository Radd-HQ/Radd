/** Presentational sidebar rows/sections — props in, JSX out (extracted from Sidebar.tsx verbatim). */

import { useIsAuthenticated } from "../../lib/hooks";
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarClock,
  CalendarRange,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  GanttChartSquare,
  Inbox,
  List,
  ListOrdered,
  SquareKanban,
  UserRound,
} from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { projectByIdQuery, formsQuery, notificationsBadgeQuery, viewCountsQuery } from "../../lib/queries";
import { CycleStatus, ViewType, type Cycle, type Project, type View } from "../../lib/types";

export const navLinkClasses =
  "relative flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-fg-secondary hover:bg-overlay " +
  "hover:text-heading focus-visible:outline-2 focus-visible:outline-focus " +
  "[&.active]:bg-elevated [&.active]:text-heading " +
  "[&.active]:before:absolute [&.active]:before:left-0 [&.active]:before:top-1/2 " +
  "[&.active]:before:h-4 [&.active]:before:w-0.5 [&.active]:before:-translate-y-1/2 " +
  "[&.active]:before:rounded-full [&.active]:before:bg-accent [&.active]:before:content-['']";

export const subLinkClasses =
  "flex items-center gap-1.5 rounded-md py-1 pl-7 pr-2 text-xs text-fg-muted hover:bg-overlay " +
  "hover:text-heading focus-visible:outline-2 focus-visible:outline-focus " +
  "[&.active]:bg-elevated [&.active]:text-heading";
/** Section heading with a fold chevron; `actions` stay clickable when collapsed. */
export function SectionHeader({
  label,
  labelTo,
  collapsed,
  onToggle,
  actions,
}: {
  label: string;
  /** When set, the label itself navigates (Pages) — the chevron still folds. */
  labelTo?: string;
  collapsed: boolean;
  onToggle: () => void;
  actions?: ReactNode;
}) {
  const Chevron = collapsed ? ChevronRight : ChevronDown;
  const labelClasses =
    "text-[11px] font-medium uppercase tracking-wide text-fg-faint hover:text-fg";
  return (
    <div className="group/section flex items-center px-2 pb-1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        aria-label={`${collapsed ? "Expand" : "Collapse"} ${label}`}
        className="mr-1 rounded p-0.5 text-fg-faint hover:bg-overlay hover:text-fg cursor-pointer"
      >
        <Chevron size={11} aria-hidden />
      </button>
      {labelTo ? (
        <Link to={labelTo} className={labelClasses}>
          {label}
        </Link>
      ) : (
        <button type="button" onClick={onToggle} className={`${labelClasses} cursor-pointer`}>
          {label}
        </button>
      )}
      {actions}
    </div>
  );
}
/** Inbox nav row with the live unread badge (spec 26; polled — realtime with spec 27). */
export function InboxLink() {
  const { data } = useQuery({ ...notificationsBadgeQuery, enabled: useIsAuthenticated() });
  const unread = data?.unread_count ?? 0;
  return (
    <Link to={RoutePath.inbox} className={navLinkClasses} data-pin-label="Inbox">
      <Inbox size={14} aria-hidden />
      Inbox
      {unread > 0 && (
        <span className="ml-auto rounded-full bg-accent px-1.5 py-px text-[10px] font-semibold text-white">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}
/**
 * "New from form" links under a project (spec 20): each enabled intake form
 * links to its submit page. Only rendered for form managers (listing forms
 * needs form.manage), so the query is always permitted.
 */
export function ProjectFormLinks({ project }: { project: Project }) {
  const { data: forms } = useQuery(formsQuery(project.id, false));
  const enabled = (forms ?? []).filter((form) => form.enabled);
  if (enabled.length === 0) return null;
  return (
    <>
      {enabled.map((form) => (
        <li key={form.id}>
          <Link
            to={RoutePath.formSubmit}
            params={{ projectKey: project.key, formId: form.id }}
            className={subLinkClasses}
          >
            <ClipboardList size={12} aria-hidden />
            <span className="truncate">{form.name}</span>
          </Link>
        </li>
      ))}
    </>
  );
}
/**
 * Queue rows with live count badges (spec 64): ONE batched POST /views/counts
 * for the whole section (viewCountsQuery, 60s re-poll) — never per-view calls.
 * Project-scoped queues link with their project context when it's resolved.
 */
export function QueueLinks({ views }: { views: View[] }) {
  const { data: counts } = useQuery(viewCountsQuery(views.map((view) => view.id)));
  return (
    <ul>
      {views.map(view => <QueueLink key={view.id} view={view} count={counts?.[view.id]} />)}
    </ul>
  );
}

function QueueLink({ view, count }: { view: View; count?: number }) {
  const project = useQuery(projectByIdQuery(view.project_id ?? ""));
  const projectKey = project.data?.key;
  const body = <>
    <ListOrdered size={14} aria-hidden />
    <span className="truncate">{view.name}</span>
    {count !== undefined && <span className="ml-auto shrink-0 rounded-full bg-elevated px-1.5 py-px text-[10px] font-medium text-fg-secondary">
      {count > 999 ? "999+" : count}
    </span>}
  </>;
  return <li>{projectKey ? <Link to={RoutePath.projectView} params={{ projectKey, viewId: view.id }} className={navLinkClasses}>
    {body}
  </Link> : <Link to={RoutePath.allProjectsView} params={{ viewId: view.id }} className={navLinkClasses}>{body}</Link>}</li>;
}
/** View row body: type icon, name, and a "personal" marker on unshared views. */
export function ViewRowContent({ view, small = false }: { view: View; small?: boolean }) {
  const Icon =
    view.view_type === ViewType.board
      ? SquareKanban
      : view.view_type === ViewType.planning
        ? CalendarClock
        : view.view_type === ViewType.roadmap
          ? GanttChartSquare
          : List;
  return (
    <>
      <Icon size={small ? 12 : 14} aria-hidden />
      <span className="truncate">{view.name}</span>
      {!view.shared && (
        <UserRound
          size={11}
          className="ml-auto shrink-0 text-fg-faint"
          aria-label="Personal view"
        />
      )}
    </>
  );
}
/** One cycle row in the sidebar. Only non-completed cycles reach here — finished
 * ones are viewable on Settings → Cycles — so there is no muted variant. The
 * live active cycle keeps its badge. */
export function CycleRow({ cycle }: { cycle: Cycle }) {
  return (
    <li>
      <Link
        to={RoutePath.cycle}
        params={{ cycleId: cycle.id }}
        className={navLinkClasses}
        data-pin-label={cycle.name}
      >
        <CalendarRange size={14} aria-hidden />
        <span className="truncate">{cycle.name}</span>
        {cycle.status === CycleStatus.active && (
          <span className="ml-auto shrink-0 rounded bg-chart-progress/15 px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-chart-progress-ink">
            Active
          </span>
        )}
      </Link>
    </li>
  );
}
