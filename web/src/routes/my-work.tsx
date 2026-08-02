import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, History, Inbox, ShieldCheck, Star, UserRound } from "lucide-react";
import { listRecentItems } from "../lib/recent";
import type { LucideIcon } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { shortDate } from "../lib/dates";
import { usePeek } from "../lib/hooks";
import { notificationsQuery, pendingApprovalsQuery, slqItemsQuery } from "../lib/queries";
import { PRIORITY_META } from "../lib/meta";
import { combineQueryWithFilters } from "../lib/slq";
import { useSlqQueryState } from "../lib/slq-filter";
import type { Item } from "../lib/types";
import { Avatar } from "../components/Avatar";
import { ItemKeyLink } from "../components/items/ItemBadges";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";

/** Days ahead the "Due soon" section looks. */
const DUE_SOON_DAYS = 7;

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

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
  const dueCutoff = new Date();
  dueCutoff.setDate(dueCutoff.getDate() + DUE_SOON_DAYS);
  const dueQ = `assignee = me AND target <= ${isoDate(dueCutoff)} AND ${OPEN}`;

  // Page-wide SLQ filter (top-bar query): ANDs into every section's own
  // query server-side — "project = TD" narrows Due soon, Assigned and
  // Starred at once. Recently viewed and the inbox aren't item queries.
  const slqFilter = useSlqQueryState();
  const withFilter = (q: string) =>
    slqFilter.committed ? combineQueryWithFilters(q, [slqFilter.committed]) : q;

  const assigned = useQuery(slqItemsQuery({}, withFilter(ASSIGNED_Q)));
  const due = useQuery(slqItemsQuery({}, withFilter(dueQ)));
  const starred = useQuery(slqItemsQuery({}, withFilter(STARRED_Q)));
  const notifications = useQuery(notificationsQuery(true));

  const dueSorted = [...(due.data ?? [])].sort((a, b) =>
    (a.target_date ?? "").localeCompare(b.target_date ?? ""),
  );
  const dueIds = new Set(dueSorted.map((item) => item.id));
  const assignedRest = (assigned.data ?? []).filter((item) => !dueIds.has(item.id));

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
        <AwaitingApprovalSection />

        <Section
          icon={CalendarClock}
          title="Due soon"
          count={dueSorted.length}
          empty="Nothing due in the next week."
        >
          {dueSorted.map((item) => (
            <ItemRow key={item.id} item={item} showDue />
          ))}
        </Section>

        <Section
          icon={UserRound}
          title="Assigned to me"
          count={assignedRest.length}
          empty="Nothing else on your plate."
        >
          {assignedRest.map((item) => (
            <ItemRow key={item.id} item={item} />
          ))}
        </Section>

        <Section
          icon={Star}
          title="Starred"
          count={(starred.data ?? []).length}
          empty="Star issues to pin them here."
        >
          {(starred.data ?? []).slice(0, 8).map((item) => (
            <ItemRow key={item.id} item={item} />
          ))}
        </Section>

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

function Section({
  icon: Icon,
  title,
  count,
  empty,
  children,
}: {
  icon: LucideIcon;
  title: string;
  count: number;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-2 flex items-center gap-2">
        <Icon size={14} className="text-fg-muted" aria-hidden />
        <h2 className="text-sm font-semibold text-fg">{title}</h2>
        <span className="text-xs text-fg-faint">{count}</span>
      </header>
      {count === 0 ? (
        <p className="rounded-lg border border-dashed border-subtle px-4 py-3 text-xs text-fg-faint">
          {empty}
        </p>
      ) : (
        <ul className="overflow-hidden rounded-lg border border-subtle">{children}</ul>
      )}
    </section>
  );
}

function ItemRow({ item, showDue = false }: { item: Item; showDue?: boolean }) {
  const peek = usePeek();
  const overdue = Boolean(
    showDue && item.target_date && item.target_date < isoDate(new Date()),
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
