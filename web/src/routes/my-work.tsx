import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import { Entity, entityMeta } from "../lib/cache";
import { Link } from "@tanstack/react-router";
import { MyForms } from "../components/forms/MyForms";
import { ListSection } from "../components/requests/ListSection";
import { MyRequests } from "../components/requests/RequestSection";
import { useQuery, useInfiniteQuery } from "@tanstack/react-query";
import { CalendarClock, History, Inbox, ShieldCheck, Star, UserRound } from "lucide-react";
import { listRecentItems } from "../lib/recent";
import { RoutePath } from "../lib/constants";
import { shiftIsoDay, shortDate, todayIso } from "../lib/dates";
import { usePeek } from "../lib/hooks";
import { notificationsQuery, pendingApprovalsQuery, itemsCountQuery } from "../lib/queries";
import { PRIORITY_META } from "../lib/meta";
import { combineQueryWithFilters, splitQueryOrder } from "../lib/slq";
import { useSlqQueryState } from "../lib/slq-filter";
import type { Item } from "../lib/types";
import { Avatar } from "../components/Avatar";
import { ItemKeyLink } from "../components/items/ItemBadges";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";

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
  const dueQ = `assignee = me AND target <= ${shiftIsoDay(todayIso(), DUE_SOON_DAYS)} AND ${OPEN}`;

  // Page-wide SLQ filter (top-bar query): ANDs into every section's own
  // query server-side — "project = TD" narrows Due soon, Assigned and
  // Starred at once. Recently viewed and the inbox aren't item queries.
  const slqFilter = useSlqQueryState();
  const withFilter = (q: string) =>
    slqFilter.committed ? combineQueryWithFilters(q, [slqFilter.committed]) : q;

  const notifications = useQuery(notificationsQuery(true));
  const queryFor = (q: string, order: string) => { const parts = splitQueryOrder(withFilter(q)); return `${parts.where} ${parts.order || `ORDER BY ${order}`}`; };
  const laterQ = `${ASSIGNED_Q} AND (target IS EMPTY OR target > ${shiftIsoDay(todayIso(), DUE_SOON_DAYS)})`;

  return (
    <div className="w-full px-6 py-6">
      <TopBarQuery>
        <QueryBar
          filter={slqFilter}
          placeholder="Filter My Work with SLQ: project = TD AND priority = high"
        />
      </TopBarQuery>
      <h1 className="mb-5 text-lg font-semibold text-heading">My Work</h1>

      <div className="flex flex-col gap-6">
        {/* Requester surfaces first (RADD-785/786): for someone whose only
            relationship with Radd is filing requests, these are the whole page,
            and both render nothing when they are empty. */}
        <MyForms />
        <MyRequests compact />

        <AwaitingApprovalSection />

        <WorkPreview icon={CalendarClock} title="Due soon" q={queryFor(dueQ, "target ASC, priority DESC, number DESC")} limit={25} showDue empty="Nothing due in the next week." />
        <WorkPreview icon={UserRound} title="Assigned to me" q={queryFor(laterQ, "rank")} limit={25} empty="Nothing else on your plate." />
        <WorkPreview icon={Star} title="Starred" q={queryFor(STARRED_Q, "rank")} limit={8} empty="Star issues to pin them here." />

        <RecentlyViewedSection />

        <section>
          <header className="mb-2 flex items-center gap-2">
            <Inbox size={14} className="text-fg-muted" aria-hidden />
            <h2 className="text-sm font-semibold text-fg">Inbox</h2>
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
              {(notifications.data?.notifications ?? []).slice(0, 5).map((notification) => (
                <li
                  key={notification.id}
                  className="flex items-baseline gap-2 border-b border-subtle/60 px-4 py-2 text-xs last:border-b-0"
                >
                  {notification.item_key && <ItemKeyLink itemKey={notification.item_key} />}
                  <span className="truncate text-fg">
                    {notification.actor?.name ?? "System"} · {notification.type.replace("_", " ")}
                  </span>
                  <span className="ml-auto shrink-0 truncate text-fg-faint">
                    {notification.item_title}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

/**
 * Approval requests awaiting MY verdict (spec 71) — rendered only when the
 * queue is non-empty; rows open the peek panel like the other sections.
 */
function AwaitingApprovalSection() {
  const peek = usePeek();
  const pending = useQuery(pendingApprovalsQuery);
  const rows = pending.data ?? [];
  if (rows.length === 0) return null;
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
    queryKey: ["my-work-preview", q, limit], meta: entityMeta(Entity.item), initialPageParam: 0,
    queryFn: ({signal, pageParam}) => api.get<Item[]>("/items", {signal, query: {q, limit: String(limit), offset: String(pageParam)}}),
    getNextPageParam: (last: Item[], _pages: Item[][], offset: number) => last.length === limit ? offset + limit : undefined,
  });
  const count = useQuery(itemsCountQuery({}, q));
  const rows = query.data?.pages.flat() ?? [];
  return <Section icon={icon} title={title} count={count.data?.total ?? rows.length}
    empty={query.isPending ? "Loading…" : query.isError ? "Could not load issues." : empty}
    action={<span className="flex items-center gap-2 text-xs text-fg-muted">
      {query.isPending ? "Loading…" : `${rows.length} shown`}
      {count.isError ? " · Total unavailable" : !count.data ? " · Counting…" : ""}
      {query.isError && <button className="underline" onClick={() => void query.refetch()}>Retry</button>}
      {query.hasNextPage && (!count.data || rows.length < count.data.total) && <button className="text-accent-text underline" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>{query.isFetchingNextPage ? "Loading…" : "Show more"}</button>}
    </span>}>
    {query.isError && !rows.length && <li role="alert" className="p-3 text-xs text-fg-muted">Could not load issues. Use Retry.</li>}
    {rows.map(item => <ItemRow key={item.id} item={item} showDue={showDue} />)}
    {query.isFetchNextPageError && <li role="alert" className="p-3 text-xs text-fg-muted">Could not load more. Try again.</li>}
  </Section>;
}
