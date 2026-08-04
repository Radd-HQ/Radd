import { useState } from "react";
import { PersonName } from "../components/PersonName";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CalendarRange, CheckCircle2, Target } from "lucide-react";
import { RoutePath } from "../lib/constants";
import { formatDate } from "../lib/dates";
import { usePeek, usePermissions } from "../lib/hooks";
import { CATEGORY_META, CATEGORY_ORDER, CYCLE_STATUS_META } from "../lib/meta";
import { cycleItemsQuery, cycleQuery, cycleStatsQuery, cyclesQuery } from "../lib/queries";
import { useSlqPageFilter } from "../lib/slq-filter";
import { CycleStatus, Permission, StateCategory, type Item } from "../lib/types";
import { CompleteCycleModal } from "../components/cycles/CompleteCycleModal";
import { CycleTimeChips } from "../components/cycles/CycleBadges";
import { EmptyState } from "../components/EmptyState";
import { Spinner } from "../components/Spinner";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";
import { QueryError } from "../components/QueryError";
import { Select } from "../components/Select";
import {
  AssigneeAvatar,
  ItemKeyLink,
  KindBadge,
  PriorityIcon,
  ReleaseChip,
} from "../components/items/ItemBadges";

/**
 * A cycle's items page (spec 18, `/cycles/$cycleId`). Cycles span projects
 * and items live per project, so we fetch every project's
 * items and client-filter by `item.cycle?.id` (GET /items has no cycle filter).
 * Items are grouped by state category (universal across projects) with a
 * done/total progress bar.
 */
export function CyclePage() {
  const { cycleId = "" } = useParams({ strict: false });
  const perms = usePermissions();
  const cycle = useQuery(cycleQuery(cycleId));
  const allCycles = useQuery(cyclesQuery());
  const [completing, setCompleting] = useState(false);

  // One server-filtered, paged fetch — complete even for 300+ item cycles.
  const items = useQuery(cycleItemsQuery(cycleId));
  const itemsLoading = items.isPending;
  const cycleItems = items.data ?? [];

  // Filters (person/team) — the list AND the stats reflect them (stats re-fetch
  // server-side with the same params; the list filters client-side).
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [teamFilter, setTeamFilter] = useState("");
  const stats = useQuery(
    cycleStatsQuery(cycleId, assigneeFilter || undefined, teamFilter || undefined),
  );
  // Ad-hoc SLQ bar: the probe is server-scoped to this cycle (`cycle_id` ANDs
  // with `q`), then intersected with the fetched items. The stats endpoint
  // knows nothing about SLQ, so while a query is active the header falls back
  // to counting the visible slice — both progress numbers stay one source.
  const slqFilter = useSlqPageFilter({ cycle_id: cycleId });
  const serverStats = slqFilter.active ? undefined : stats.data;
  const assigneeOptions = [
    ...new Map(
      cycleItems.filter((i) => i.assignee).map((i) => [i.assignee!.id, i.assignee!]),
    ).values(),
  ].sort((a, b) => a.name.localeCompare(b.name));
  const teamOptions = [
    ...new Map(cycleItems.filter((i) => i.team).map((i) => [i.team!.id, i.team!])).values(),
  ].sort((a, b) => a.name.localeCompare(b.name));

  const visibleItems = slqFilter
    .filterItems(cycleItems)
    .filter(
      (item) =>
        (!assigneeFilter || item.assignee?.id === assigneeFilter) &&
        (!teamFilter || item.team?.id === teamFilter),
    );

  const groups = CATEGORY_ORDER.map((category) => ({
    category,
    items: visibleItems.filter((item) => item.state.category === category),
  })).filter((group) => group.items.length > 0);

  // Progress from the server-side stats when loaded (never a paginated subset);
  // both numbers MUST come from the same source or the ratio lies.
  const total = serverStats ? serverStats.total : visibleItems.length;
  const done = serverStats
    ? (serverStats.by_category[StateCategory.done] ?? 0)
    : visibleItems.filter((item) => item.state.category === StateCategory.done).length;
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
              <button
                type="button"
                onClick={() => setCompleting(true)}
                className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-strong px-2.5 py-1 text-xs text-fg hover:border-emphasis hover:text-heading cursor-pointer"
              >
                <CheckCircle2 size={13} aria-hidden />
                Complete cycle
              </button>
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
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${pct}%` }}
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Cycle progress"
            />
          </div>
          <span className="shrink-0 text-xs text-fg-muted">
            {done}/{total} done
          </span>
        </div>

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
          <span className="ml-auto flex items-center gap-2">
            <Select
              value={assigneeFilter}
              onChange={setAssigneeFilter}
              aria-label="Filter by person"
              size="sm"
              options={[
                { value: "", label: "Anyone" },
                ...assigneeOptions.map((user) => ({ value: user.id, label: <PersonName user={user} /> })),
              ]}
            />
            <Select
              value={teamFilter}
              onChange={setTeamFilter}
              aria-label="Filter by team"
              size="sm"
              options={[
                { value: "", label: "Any team" },
                ...teamOptions.map((team) => ({ value: team.id, label: team.name })),
              ]}
            />
          </span>
        </div>
      </header>

      {completing && (
        <CompleteCycleModal
          cycle={cycle.data}
          cycles={allCycles.data ?? []}
          openCount={total - done}
          onClose={() => setCompleting(false)}
        />
      )}

      <div className="flex-1 overflow-y-auto px-6 py-5">
        {itemsLoading ? (
          <Spinner label="Loading items…" />
        ) : cycleItems.length === 0 ? (
          <EmptyState
            icon={CalendarRange}
            message="No items in this cycle yet — assign items to it from their detail page."
          />
        ) : visibleItems.length === 0 ? (
          <p className="p-10 text-center text-sm text-fg-faint">No items match these filters.</p>
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
                  <span className="text-xs text-fg-muted">{group.items.length}</span>
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
          if (event.key === "Enter") open(item.key);
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
