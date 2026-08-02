import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SidePanel } from "../SidePanel";
import { Inbox, Search, X } from "lucide-react";
import { ROADMAP_TRAY_PAGE_LIMIT, roadmapTrayFilterStorageKey } from "../../lib/constants";
import { usePeek } from "../../lib/hooks";
import { CATEGORY_META } from "../../lib/meta";
import { itemsCountQuery, roadmapTrayItemsQuery } from "../../lib/queries";
import { combineQueryWithFilters } from "../../lib/slq";
import type { Item } from "../../lib/types";
import { ItemKeyLink, KindBadge, PriorityIcon } from "../items/ItemBadges";
import { Pager } from "../Pager";

/** Tray filter chips (spec 79): everything, or unscheduled epics only (the
 * "populate the roadmap top-down" flow). Persisted per view in localStorage. */
export const TrayFilter = {
  all: "all",
  epics: "epics",
} as const;
export type TrayFilterValue = (typeof TrayFilter)[keyof typeof TrayFilter];

function loadTrayFilter(viewId: string): TrayFilterValue {
  return window.localStorage.getItem(roadmapTrayFilterStorageKey(viewId)) === TrayFilter.epics
    ? TrayFilter.epics
    : TrayFilter.all;
}

/** SLQ string literals are backslash-escaped quoted values (lexer rules). */
const slqString = (text: string) => `"${text.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;

/**
 * Items without a full start+target window (spec 19) — parked here where they
 * can be picked up and scheduled. Chips open the issue in the side panel;
 * with item.update (spec 77) they also DRAG onto the timeline, which schedules
 * them at the drop day with a default-length bar.
 *
 * Perf wave: the tray fetches its OWN bounded pages (the main
 * roadmap fetch carries only epics + dated bars, never the unscheduled pool —
 * which is ~93k items on a 100k-item project). Chips and the search box narrow
 * server-side through SLQ; "Load more" extends the pool a page at a time.
 * Epics already drawing a derived (children-union) bar are deduped out.
 */
export function UnscheduledTray({
  viewId,
  query,
  projectId,
  excludeIds,
  canEdit,
  onDragStart,
  onDragEnd,
}: {
  /** Keys the persisted tray filter (spec 79 — roadmaps are saved views). */
  viewId: string;
  /** The tray's base SLQ (view query + tray clause), before chips/search. */
  query: string;
  projectId: string | null;
  /** Ids already drawn as rows (derived-bar epics) — hidden here. */
  excludeIds: ReadonlySet<string>;
  /** Enables drag-to-schedule (spec 77); false keeps the read-only tray. */
  canEdit: boolean;
  onDragStart: (item: Item) => void;
  onDragEnd: () => void;
}) {
  const { open: openPeek } = usePeek();
  // Initialized from storage — the surface remounts per view (key={view.id}).
  const [filter, setFilter] = useState<TrayFilterValue>(() => loadTrayFilter(viewId));
  const pickFilter = (next: TrayFilterValue) => {
    setFilter(next);
    window.localStorage.setItem(roadmapTrayFilterStorageKey(viewId), next);
  };
  // Committed on Enter (spec 55 convention: no per-keystroke fetches).
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const trayQ = useMemo(
    () =>
      combineQueryWithFilters(query, [
        ...(filter === TrayFilter.epics ? ["kind = epic"] : []),
        ...(search ? [`title ~ ${slqString(search)}`] : []),
      ]),
    [query, filter, search],
  );
  // Classic pages (pagination wave): compact ‹ page/of › pager + a true total.
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [trayQ]);
  const pageQuery = useQuery(roadmapTrayItemsQuery(viewId, trayQ, projectId, page));
  const total =
    useQuery(itemsCountQuery(projectId ? { project_id: projectId } : {}, trayQ)).data?.total ??
    null;
  const pageCount =
    total === null ? null : Math.max(1, Math.ceil(total / ROADMAP_TRAY_PAGE_LIMIT));
  const visible = useMemo(
    () => (pageQuery.data ?? []).filter((item) => !excludeIds.has(item.id)),
    [pageQuery.data, excludeIds],
  );

  const chipClasses = (active: boolean) =>
    "rounded-full border px-2 py-px text-[11px] transition-colors cursor-pointer " +
    (active
      ? "border-accent-hover bg-accent/15 text-accent-text-strong"
      : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg");

  return (
    <SidePanel
      panelKey="roadmap-tray"
      label="Unscheduled"
      icon={Inbox}
      badge={total ?? visible.length}
      expandedClassName="w-72 shrink-0 overflow-y-auto rounded-xl border border-subtle bg-surface shadow-lift"
    >
      <header className="sticky top-0 z-10 border-b border-subtle bg-surface">
        <div className="flex items-center gap-1.5 px-4 pb-2 pt-1" role="group" aria-label="Tray filter">
          <button
            type="button"
            aria-pressed={filter === TrayFilter.all}
            onClick={() => pickFilter(TrayFilter.all)}
            className={chipClasses(filter === TrayFilter.all)}
          >
            All
          </button>
          <button
            type="button"
            aria-pressed={filter === TrayFilter.epics}
            onClick={() => pickFilter(TrayFilter.epics)}
            className={chipClasses(filter === TrayFilter.epics)}
          >
            Epics
          </button>
        </div>
        <div className="relative px-4 pb-2">
          <Search
            size={12}
            className="pointer-events-none absolute left-6 top-1/2 -translate-y-[13px] text-fg-faint"
            aria-hidden
          />
          <input
            type="text"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") setSearch(searchInput.trim());
              if (event.key === "Escape") {
                setSearchInput("");
                setSearch("");
              }
            }}
            placeholder="Search titles… (Enter)"
            aria-label="Search unscheduled items"
            className="h-6 w-full rounded-md border border-subtle bg-base pl-6 pr-6 text-[11px] text-fg placeholder:text-fg-faint focus:outline-2 focus:outline-focus"
          />
          {(searchInput || search) && (
            <button
              type="button"
              onClick={() => {
                setSearchInput("");
                setSearch("");
              }}
              title="Clear search"
              className="absolute right-6 top-1/2 -translate-y-[13px] text-fg-faint hover:text-fg cursor-pointer"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </header>
      {canEdit && visible.length > 0 && (
        <p className="border-b border-subtle/60 px-4 py-2 text-[11px] leading-snug text-fg-faint">
          Drag onto the timeline to schedule — issues get a one-week bar, epics about three.
        </p>
      )}
      {pageQuery.isPending ? (
        <p className="px-4 py-3 text-xs text-fg-faint">Loading…</p>
      ) : visible.length === 0 ? (
        <p className="px-4 py-3 text-xs text-fg-faint">
          {search
            ? "No unscheduled items match."
            : filter === TrayFilter.epics
              ? "No unscheduled epics."
              : "Everything has dates."}
        </p>
      ) : (
        <>
          <ul className="p-2">
            {visible.map((item) => (
              <li key={item.id}>
                {/* div, not button: the key inside is a real link */}
                <div
                  role="button"
                  tabIndex={0}
                  draggable={canEdit}
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = "move";
                    onDragStart(item);
                  }}
                  onDragEnd={onDragEnd}
                  onClick={() => openPeek(item.key)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") openPeek(item.key);
                  }}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-elevated/60 focus-visible:outline-2 focus-visible:outline-focus ${
                    canEdit ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"
                  }`}
                  title={item.title}
                >
                  <KindBadge kind={item.kind} size={13} />
                  <PriorityIcon priority={item.priority} size={12} />
                  <ItemKeyLink itemKey={item.key} />
                  <span className="min-w-0 flex-1 truncate text-[12px] text-fg">
                    {item.title}
                  </span>
                  <span
                    className={`size-1.5 shrink-0 rounded-full ${CATEGORY_META[item.state.category].dotClassName}`}
                    title={item.state.name}
                    aria-hidden
                  />
                </div>
              </li>
            ))}
          </ul>
          {(pageCount === null || pageCount > 1) && (
            <div className="flex justify-center px-4 pb-3">
              <Pager page={page} pageCount={pageCount} onPage={setPage} compact />
            </div>
          )}
        </>
      )}
    </SidePanel>
  );
}
