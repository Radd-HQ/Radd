import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CalendarRange, CheckCircle2, Target } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { formatDate } from "../lib/dates";
import { usePeek, usePermissions } from "../lib/hooks";
import { CATEGORY_META, CATEGORY_ORDER, CYCLE_STATUS_META } from "../lib/meta";
import { CYCLE_ITEMS_PAGE_SIZE, cycleItemsQuery, cycleQuery, cycleStatsQuery } from "../lib/queries";
import { useSlqQueryState } from "../lib/slq-filter";
import { CycleStatus, Permission, StateCategory, type Item } from "../lib/types";
import { Button } from "../components/Button";
import { CompleteCycleModal } from "../components/cycles/CompleteCycleModal";
import { CycleTimeChips } from "../components/cycles/CycleBadges";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";
import { QueryError } from "../components/QueryError";
import { PeopleDirectorySelect } from "../components/PeopleDirectorySelect";
import { DirectoryPager } from "../components/DirectoryPager";
import type { PeopleChoice } from "../lib/queries/users";
import {
  AssigneeAvatar,
  ItemKeyLink,
  KindBadge,
  PriorityIcon,
  ReleaseChip,
} from "../components/items/ItemBadges";

/** Cycle items use bounded server windows. Person, team and committed SLQ
 * scope both the rows and full-result progress/time statistics. */
export function CyclePage() {
  const { cycleId = "" } = useParams({ strict: false });
  const perms = usePermissions();
  const cycle = useQuery(cycleQuery(cycleId));
  const [completing, setCompleting] = useState(false);

  const [assigneeFilter, setAssigneeFilter] = useState<PeopleChoice | null>(null);
  const [teamFilter, setTeamFilter] = useState<PeopleChoice | null>(null);
  const slqFilter = useSlqQueryState();
  const scope = JSON.stringify([cycleId, assigneeFilter?.id, teamFilter?.id, slqFilter.committed]);
  const [position, setPosition] = useState({ scope, page: 0 });
  if (position.scope !== scope) setPosition({ scope, page: 0 });
  const page = position.scope === scope ? position.page : 0;
  const items = useQuery(cycleItemsQuery(cycleId, page, slqFilter.committed, assigneeFilter?.id, teamFilter?.id));
  const stats = useQuery(cycleStatsQuery(cycleId, assigneeFilter?.id, teamFilter?.id, undefined, slqFilter.committed));
  // Never substitute the current window for whole-result totals, including
  // while filters change or the statistics request fails.
  const serverStats = stats.isPlaceholderData ? undefined : stats.data;
  const visibleItems = items.data ?? [];
  const groups = CATEGORY_ORDER.map((category) => ({
    category,
    items: visibleItems.filter((item) => item.state.category === category),
  })).filter((group) => group.items.length > 0);
  const total = serverStats?.total ?? 0;
  const done = serverStats?.by_category[StateCategory.done] ?? 0;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  if (cycle.isPending) return <Spinner label="Loading cycle…" />;
  if (cycle.isError) {
    return (
      <div className="p-10">
        <QueryError label="cycle" error={cycle.error} />
      </div>
    );
  }

  const status = CYCLE_STATUS_META[cycle.data.status];

  return (
    <div className="flex h-full w-full flex-col">
      {/* The cycle's SLQ filter rides in the global top bar, same as views. */}
      <TopBarQuery>
        <QueryBar
          filter={slqFilter}
          placeholder="Filter this cycle with SLQ: priority = blocker AND project = TD"
        />
      </TopBarQuery>
      <header className="border-b border-subtle px-6 py-4">
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <Link to={RoutePath.home} className="hover:text-fg">
            Projects
          </Link>
          <span>/</span>
          <span>Cycles</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold text-heading">{cycle.data.name}</h1>
          <span
            className="inline-flex items-center gap-1.5 rounded border border-strong px-1.5 py-px text-[11px] uppercase tracking-wide text-fg-secondary"
            title={`Status: ${status.label}`}
          >
            <span className={`size-2 rounded-full ${status.dotClassName}`} aria-hidden />
            {status.label}
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-fg-muted">
            <CalendarRange size={13} aria-hidden />
            {cycle.data.start_date && cycle.data.end_date
              ? `${formatDate(cycle.data.start_date)} – ${formatDate(cycle.data.end_date)}`
              : "Not scheduled"}
          </span>
          {cycle.data.status === CycleStatus.active &&
            perms.global(Permission.cycleUpdate) && (
              <Button
                variant="secondary"
                size="sm"
                className="ml-auto"
                onClick={() => setCompleting(true)}
              >
                <CheckCircle2 size={13} aria-hidden />
                Complete cycle
              </Button>
            )}
        </div>
        {cycle.data.goal && (
          <p className="mt-2 flex items-start gap-1.5 text-[13px] text-fg-secondary">
            <Target size={14} className="mt-0.5 shrink-0 text-fg-faint" aria-hidden />
            {cycle.data.goal}
          </p>
        )}
        <div className="mt-3 flex items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-elevated">
            <div
              className="h-full rounded-full bg-status-success transition-all"
              style={{ width: `${pct}%` }}
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Cycle progress"
            />
          </div>
          <span className="shrink-0 text-xs text-fg-muted">
            {serverStats ? `${done}/${total} done` : "Loading totals…"}
          </span>
        </div>

        {stats.isError && <QueryError label="cycle totals" error={stats.error} />}

        {/* Stats + filters: state counts and time totals for the filtered slice. */}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          {serverStats && (
            <>
              {CATEGORY_ORDER.filter((category) => serverStats.by_category[category]).map(
                (category) => (
                  <span
                    key={category}
                    className="inline-flex items-center gap-1.5 text-xs text-fg"
                  >
                    <span
                      className={`size-2 rounded-full ${CATEGORY_META[category].dotClassName}`}
                      aria-hidden
                    />
                    {CATEGORY_META[category].label}
                    <span className="font-medium text-heading">
                      {serverStats.by_category[category]}
                    </span>
                  </span>
                ),
              )}
              <CycleTimeChips stats={serverStats} />
            </>
          )}
          <span className="ml-auto flex max-w-full flex-wrap items-center gap-2">
            <PeopleDirectorySelect kind="person" value={assigneeFilter} onChange={setAssigneeFilter}
              label="Filter by person" emptyLabel="Anyone" />
            <PeopleDirectorySelect kind="team" value={teamFilter} onChange={setTeamFilter}
              label="Filter by team" emptyLabel="Any team" />
          </span>
        </div>
      </header>

      {completing && (
        <CompleteCycleModal
          cycle={cycle.data}
          onClose={() => setCompleting(false)}
        />
      )}

      <div className="flex-1 overflow-y-auto px-6 py-5">
        {items.isPending ? (
          <Spinner label="Loading items…" />
        ) : items.isError ? (
          <QueryError label="cycle items" error={items.error} />
        ) : visibleItems.length === 0 ? (
          <EmptyState icon={CalendarRange} message={slqFilter.committed || assigneeFilter || teamFilter
            ? "No items match these filters." : "No items on this page. Assign items to this cycle from their detail page."} />
        ) : (
          <div className="flex flex-col gap-6">
            {groups.map((group) => (
              <section key={group.category}>
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className={`size-2 rounded-full ${CATEGORY_META[group.category].dotClassName}`}
                    aria-hidden
                  />
                  <h2 className="text-[13px] font-semibold text-fg">
                    {CATEGORY_META[group.category].label}
                  </h2>
                  <span className="text-xs text-fg-muted">{group.items.length} on this page</span>
                </div>
                <ul className="rounded-lg border border-subtle">
                  {group.items.map((item) => (
                    <CycleItemRow key={item.id} item={item} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
        <DirectoryPager page={page} pageSize={CYCLE_ITEMS_PAGE_SIZE} total={total}
          busy={items.isFetching || stats.isFetching || !serverStats}
          onPage={next => setPosition({ scope, page: next })} label="cycle items" />
      </div>
    </div>
  );
}

function CycleItemRow({ item }: { item: Item }) {
  const { open } = usePeek();
  return (
    <li className="border-b border-subtle/60 last:border-b-0">
      {/* div, not button: the key inside is a real link (anchors can't nest in buttons) */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => open(item.key)}
        onKeyDown={(event) => {
          if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            open(item.key);
          }
        }}
        className="flex w-full cursor-pointer items-center gap-2.5 px-4 py-2.5 text-left hover:bg-surface/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
      >
        <KindBadge kind={item.kind} size={13} />
        <PriorityIcon priority={item.priority} size={13} />
        <ItemKeyLink itemKey={item.key} />
        <span className="min-w-0 flex-1 truncate text-[13px] text-heading">{item.title}</span>
        {item.target_date && (
          <span className="shrink-0 text-[11px] text-fg-muted">
            {formatDate(item.target_date)}
          </span>
        )}
        {item.release && <ReleaseChip release={item.release} />}
        {item.assignee && <AssigneeAvatar assignee={item.assignee} />}
      </div>
    </li>
  );
}
