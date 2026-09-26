import { DashboardCanvas } from "../components/dashboards/DashboardCanvas";
import { WidgetBody } from "../components/dashboards/WidgetCard";
import { ActivityWidget } from "../components/dashboards/ActivityWidget";
import { ErrorText, shiftIsoDay, shortDate, todayIso } from "@radd/plugin-sdk";
import { QuickStar } from "../components/items/QuickStar";
import type { LucideIcon } from "lucide-react";
import { api, ApiError, type CursorPage } from "../lib/api";
import { Entity, entityMeta } from "../lib/cache";
import { Link } from "@tanstack/react-router";
import { MyForms } from "../components/forms/MyForms";
import { ListSection } from "../components/requests/ListSection";
import { MyRequests } from "../components/requests/RequestSection";
import { useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, History, Inbox, ShieldCheck, Star, UserRound } from "lucide-react";
import { listRecentItems } from "../lib/recent";
import { RoutePath } from "../lib/constants";
import { usePeek } from "../lib/hooks";
import { notificationsQuery, pendingApprovalsQuery, itemsCountQuery } from "../lib/queries";
import { PRIORITY_META } from "../lib/meta";
import { combineQueryWithFilters, splitQueryOrder } from "../lib/slq";
import { useSlqQueryState } from "../lib/slq-filter";
import type { Item, Dashboard, DashboardWidget } from "../lib/types";
import { Avatar } from "../components/Avatar";
import { ItemKeyLink } from "../components/items/ItemBadges";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";
import { groupNotificationBursts } from "../lib/notification-bursts";
import { notificationSummary } from "../components/notifications/NotificationRow";

/** Days ahead the "Due soon" section looks. */
const DUE_SOON_DAYS = 7;

/** SLQ scopes for the dashboard sections (spec 32) — plain `GET /items?q=`. */
const OPEN = "category NOT IN (done, canceled)";
const ASSIGNED_Q = `assignee = me AND ${OPEN}`;
const STARRED_Q = `starred = true AND ${OPEN}`;

/**
 * "My Work" — the personal landing page (spec 32): what's on your plate, what's
 * due, what you starred, and your unread inbox. Rows open the peek panel so you
 * never leave the dashboard.
 */
export function MyWorkPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["my-work-widgets"], retry: false, queryFn: () => api.get<DashboardWidget[]>("/dashboards/my-work/widgets") });
  const slqFilter = useSlqQueryState();
  if (query.isPending) return <p className="p-6">Loading My Work…</p>;
  if (query.isError && query.error instanceof ApiError && query.error.status === 404) return <div className="space-y-6 p-6">
    <h1 className="text-lg font-semibold text-heading">My Work</h1>
    <MyForms /><MyRequests compact /><AwaitingApprovalSection />
    <WorkPreview icon={UserRound} title="Assigned to me" q={`${ASSIGNED_Q} ORDER BY category DESC, priority DESC`} limit={10} empty="Nothing on your plate." />
    <WorkPreview icon={Star} title="Starred" q={STARRED_Q} limit={5} empty="Star issues to pin them here." />
    <InboxWidget />
  </div>;
  if (query.isError) return <ErrorText error={query.error} />;
  const dashboard: Dashboard = { id: "my-work", name: "My Work", description: "", owner_id: null, owner: null, global_access: null,
    shared: false, shares: [], can_edit: true, can_manage: false, position: 0, widgets: query.data, created_at: "", updated_at: "" };
  return <div className="w-full p-6">
    <TopBarQuery><QueryBar filter={slqFilter} placeholder="Filter issue widgets with SLQ: project = TD" /></TopBarQuery>
    <h1 className="mb-3 text-lg font-semibold text-heading">My Work</h1>
    <DashboardCanvas dashboard={dashboard} defaults={() => api.get<DashboardWidget[]>("/dashboards/my-work/defaults")}
      save={async (widgets, expected) => {
        const saved = await api.put<DashboardWidget[]>("/dashboards/my-work/widgets", { widgets, expected });
        client.setQueryData(["my-work-widgets"], saved);
      }} render={widget => <PersonalWidget widget={widget} filter={slqFilter.committed} />} />
  </div>;
}

function PersonalWidget({ widget, filter }: { widget: DashboardWidget; filter: string }) {
  const q = (scope: string, order: string) => {
    const parts = splitQueryOrder(filter ? combineQueryWithFilters(scope, [filter]) : scope);
    return `${parts.where} ${parts.order || `ORDER BY ${order}`}`;
  };
  switch (widget.widget_type) {
    case "assigned": return <WorkPreview icon={UserRound} title="Assigned to me" q={q(ASSIGNED_Q, "category DESC, priority DESC, rank")} limit={10} empty="Nothing on your plate." />;
    case "due": return <WorkPreview icon={CalendarClock} title="Due soon" q={q(`assignee = me AND target <= ${shiftIsoDay(todayIso(), DUE_SOON_DAYS)} AND ${OPEN}`, "target ASC, priority DESC")} limit={10} showDue empty="Nothing due in the next week." />;
    case "starred": return <WorkPreview icon={Star} title="Starred" q={q(STARRED_Q, "rank")} limit={5} empty="Star issues to pin them here." />;
    case "activity": return <ActivityWidget key={JSON.stringify(widget.config)} config={widget.config} />;
    case "inbox": return <InboxWidget />;
    case "approvals": return <AwaitingApprovalSection />;
    case "requests": return <MyRequests compact />;
    case "forms": return <MyForms />;
    case "recent": return <RecentlyViewedSection />;
    default: return <WidgetBody widget={widget} filterQuery={filter} />;
  }
}

function InboxWidget() {
  const notifications = useQuery(notificationsQuery(true));
  if (notifications.isError) return <ErrorText error={notifications.error} />;
  return (        <section>
          <header className="mb-2 flex items-center gap-2">
            <Inbox size={12} className="text-fg-muted" aria-hidden />
            {/* RADD-1294: the same heading as every other My Work section. */}
            <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-muted">Inbox</h2>
            {(notifications.data?.unread_count ?? 0) > 0 && (
              <span className="rounded-full bg-accent/20 px-1.5 py-px text-[10px] font-medium text-accent-text">
                {notifications.data?.unread_count}
              </span>
            )}
            <Link
              to={RoutePath.inbox}
              className="ml-auto text-xs text-accent-text hover:text-accent-text-strong"
            >
              Open inbox →
            </Link>
          </header>
          {(notifications.data?.notifications ?? []).length === 0 ? (
            <p className="rounded-lg border border-dashed border-subtle px-4 py-3 text-xs text-fg-faint">
              No unread notifications.
            </p>
          ) : (
            <ul className="overflow-hidden rounded-lg border border-subtle">
              {groupNotificationBursts(notifications.data?.notifications ?? []).slice(0, 5).map(({ lead: notification, members }) => (
                <li
                  key={notification.id}
                  className="flex items-baseline gap-2 border-b border-subtle/60 px-4 py-2 text-xs last:border-b-0"
                >
                  {notification.item_key && <ItemKeyLink itemKey={notification.item_key} />}
                  {/* RADD-1294: the inbox's own sentence, not the raw type name. */}
                  <span className="truncate text-fg">
                    {notificationSummary(notification)}
                    {members.length > 1 && <span className="text-fg-muted"> · {members.length} times</span>}
                  </span>
                  <span className="ml-auto shrink-0 truncate text-fg-faint">
                    {notification.item_title}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>);
}

/**
 * Approval requests awaiting MY verdict (spec 71) — rendered only when the
 * queue is non-empty; rows open the peek panel like the other sections.
 */
function AwaitingApprovalSection() {
  const peek = usePeek();
  const pending = useQuery(pendingApprovalsQuery);
  const rows = pending.data ?? [];
  if (pending.isError) return <ErrorText error={pending.error} />;
  if (pending.isPending) return <p className="text-sm text-fg-muted">Loading approvals…</p>;
  if (rows.length === 0) return <p className="text-sm text-fg-muted">No approvals waiting for you.</p>;
  return (
    <section>
      <header className="mb-2 flex items-center gap-2">
        <ShieldCheck size={14} className="text-fg-muted" aria-hidden />
        <h2 className="text-sm font-semibold text-fg">Awaiting my approval</h2>
        <span className="text-xs text-fg-faint">{rows.length}</span>
      </header>
      <ul className="overflow-hidden rounded-lg border border-subtle">
        {rows.map((row) => (
          <li key={row.id}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => peek.open(row.item_key)}
              onKeyDown={(event) => {
                if (event.key === "Enter") peek.open(row.item_key);
              }}
              title={row.note || undefined}
              className="flex w-full items-center gap-2.5 border-b border-subtle/60 px-4 py-2 text-left last:border-b-0 hover:bg-elevated/50 cursor-pointer"
            >
              <ItemKeyLink
                itemKey={row.item_key}
                className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary hover:text-accent-text hover:underline"
              />
              <span className="min-w-0 flex-1 truncate text-[13px] text-fg">
                {row.item_title}
              </span>
              <span className="shrink-0 rounded bg-elevated/80 px-1.5 py-px text-[10px] text-fg-secondary">
                → {row.to_state_name}
              </span>
              <span className="shrink-0 text-[11px] text-fg-muted">
                {row.requested_by?.name ?? "Unknown"} · {shortDate(row.created_at)}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Per-browser recently-viewed trail (spec 37 — recorded by the item detail). */
function RecentlyViewedSection() {
  const peek = usePeek();
  const recent = listRecentItems();
  if (recent.length === 0) return null;
  return (
    <section>
      <header className="mb-2 flex items-center gap-2">
        <History size={14} className="text-fg-muted" aria-hidden />
        <h2 className="text-sm font-semibold text-fg">Recently viewed</h2>
      </header>
      <div className="flex flex-wrap gap-1.5">
        {recent.slice(0, 8).map((entry) => (
          <div
            key={entry.key}
            role="button"
            tabIndex={0}
            onClick={() => peek.open(entry.key)}
            onKeyDown={(event) => {
              if (event.key === "Enter") peek.open(entry.key);
            }}
            title={entry.title}
            className="flex max-w-64 items-baseline gap-1.5 rounded-md border border-subtle px-2 py-1 text-xs hover:border-emphasis cursor-pointer"
          >
            <ItemKeyLink itemKey={entry.key} />
            <span className="truncate text-fg">{entry.title}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * My Work's sections are the SAME object as Portal's now (RADD-799).
 *
 * This used to be a local component with a 14px semibold heading while Portal
 * used an 11px uppercase muted one — same kind of list, two looks, on two pages
 * a requester moves between. That difference was most of what "messy" meant.
 */
const Section = ListSection;

function ItemRow({ item, showDue = false }: { item: Item; showDue?: boolean }) {
  const peek = usePeek();
  const overdue = Boolean(
    showDue && item.target_date && item.target_date < todayIso(),
  );
  const priority = PRIORITY_META[item.priority];
  return (
    <li>
      {/* div, not button: the key inside is a real link (anchors can't nest in buttons) */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => peek.open(item.key)}
        onKeyDown={(event) => {
          if (event.key === "Enter") peek.open(item.key);
        }}
        className={
          "flex w-full items-center gap-2.5 border-b border-subtle/60 px-4 py-2 text-left last:border-b-0 hover:bg-elevated/50 cursor-pointer " +
          (overdue ? "bg-red-500/5" : "")
        }
      >
        <QuickStar item={item} />
        <ItemKeyLink
          itemKey={item.key}
          className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary hover:text-accent-text hover:underline"
        />
        <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{item.title}</span>
        {priority && (
          <span className="shrink-0 text-[11px] text-fg-muted">{priority.label}</span>
        )}
        <span className="shrink-0 rounded bg-elevated/80 px-1.5 py-px text-[10px] text-fg-secondary">
          {item.state.name}
        </span>
        {item.assignee && !showDue && <Avatar user={item.assignee} size="xs" />}
        {showDue && item.target_date && (
          <span
            className={
              "shrink-0 text-[11px] " + (overdue ? "font-medium text-red-300" : "text-fg-muted")
            }
          >
            {overdue ? "Overdue · " : "Due "}
            {shortDate(item.target_date)}
          </span>
        )}
      </div>
    </li>
  );
}

/** Small initial windows; every matching row remains reachable without leaving My Work. */
function WorkPreview({icon, title, q, limit, showDue = false, empty}: {
  icon: LucideIcon; title: string; q: string; limit: number; showDue?: boolean; empty: string;
}) {
  const query = useInfiniteQuery({
    queryKey: ["my-work-cursor-preview", q, limit], meta: entityMeta(Entity.item), initialPageParam: null as string | null,
    queryFn: ({signal, pageParam}) => api.getCursor<Item>("/items", {signal, query: {q, limit: String(limit), after: pageParam ?? undefined}}),
    getNextPageParam: (last: CursorPage<Item>) => last.next ?? undefined,
  });
  const count = useQuery(itemsCountQuery({}, q));
  const rows = [...new Map((query.data?.pages.flatMap(page=>page.rows) ?? []).map(item=>[item.id,item])).values()];
  return <Section icon={icon} title={title} count={count.data?.total ?? rows.length}
    empty={query.isPending ? "Loading…" : query.isError ? "Could not load issues." : empty}
    action={<span className="flex items-center gap-2 text-xs text-fg-muted">
      {/* RADD-1293: only when the list is a slice of the total — "0 shown" above an
          empty state, or "5 shown" beside a 5, said nothing. */}
      {query.isPending ? "Loading…" : count.data && rows.length > 0 && rows.length < count.data.total ? `${rows.length} of ${count.data.total} shown` : ""}
      {count.isError ? " · Total unavailable" : !count.data ? " · Counting…" : ""}
      {query.isError && <button className="underline" onClick={() => void query.refetch()}>Retry</button>}
      {query.hasNextPage && <button className="text-accent-text underline" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>{query.isFetchingNextPage ? "Loading…" : "Show more"}</button>}
    </span>}>
    {query.isError && !rows.length && <li role="alert" className="p-3 text-xs text-fg-muted">Could not load issues. Use Retry.</li>}
    {rows.map(item => <ItemRow key={item.id} item={item} showDue={showDue} />)}
    {query.isFetchNextPageError && <li role="alert" className="p-3 text-xs text-fg-muted">Could not load more. Try again.</li>}
  </Section>;
}
