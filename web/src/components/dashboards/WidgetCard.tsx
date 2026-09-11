import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { SlotId, useSlotMatch, useDisabledMatches } from "@radd/plugin-sdk";
import { MissingPluginType } from "../shell/MissingPluginType";
import { REPORT_DEFAULT_RANGE_DAYS, RoutePath } from "../../lib/constants";
import { isoDaysAgo } from "../../lib/dates";
import { usePeek, usePointsEnabled } from "../../lib/hooks";
import {
  itemsCountQuery,
  projectByIdQuery,
  slqListItemsQuery,
  viewCountsQuery,
  viewQuery,
} from "../../lib/queries";
import {
  ReportInterval,
  ReportMeasure,
  WidgetType,
  type DashboardWidget,
  type Item,
} from "../../lib/types";
import { combineQueryWithFilters } from "../../lib/slq";
import { Spinner } from "../Spinner";
import { ItemKeyLink } from "../items/ItemBadges";
import { BurnupCard } from "../reports/BurnupCard";
import { CumulativeFlowCard } from "../reports/CumulativeFlowCard";
import { SlaCard } from "../reports/SlaCard";
import { ThroughputCard } from "../reports/ThroughputCard";
import { TimeInStateCard } from "../reports/TimeInStateCard";
import { VelocityCard } from "../reports/VelocityCard";

/**
 * One dashboard widget's body (spec 75): every type renders through an
 * EXISTING data surface — the shared report cards from components/reports/*,
 * GET /items/count, GET /items?q=, POST /views/counts. A widget whose fetch
 * 403/404s renders an Unavailable card (the report cards contain their own
 * error state) — the dashboard as a whole never dies.
 */
export function WidgetBody({
  widget,
  filterQuery,
}: {
  widget: DashboardWidget;
  /** Dashboard-wide SLQ filter (the top-bar query). Every builtin honors it:
   * SLQ widgets AND it into their own q client-side; report + view-count
   * widgets pass it as the endpoints' `q`/`extra_q`, where the server
   * intersects the report's item universe with the CURRENT matches. Plugin
   * widgets receive it in their render args and decide for themselves. */
  filterQuery?: string;
}) {
  // Plugin-contributed widget types (spec 94): a plugin registers a `dashboard.widget` slot keyed
  // (match) to its widget-type string; an unknown builtin type falls through to it here. (Making the
  // TYPE selectable end-to-end also needs the backend widget-type enum to become a registry — a
  // logged follow-up; see docs/plugin-ui.md.)
  const pluginWidget = useSlotMatch(SlotId.dashboardWidget, widget.widget_type);
  const disabledWidgetTypes = useDisabledMatches(SlotId.dashboardWidget);
  switch (widget.widget_type) {
    case WidgetType.reportThroughput:
    case WidgetType.reportCfd:
      return <ReportRangeWidget widget={widget} filterQuery={filterQuery} />;
    case WidgetType.reportTimeInState:
      return widget.config.project_id ? (
        <TimeInStateCard
          projectId={widget.config.project_id}
          initialKind={widget.config.kind ?? undefined}
          q={filterQuery}
        />
      ) : (
        <UnavailableCard title={widget.title} />
      );
    case WidgetType.reportVelocity:
      return <VelocityWidget widget={widget} filterQuery={filterQuery} />;
    case WidgetType.reportBurnup:
      return <BurnupWidget widget={widget} filterQuery={filterQuery} />;
    case WidgetType.reportSla:
      return (
        <SlaCard
          projectId={widget.config.project_id ?? undefined}
          initialWeeks={widget.config.weeks}
          q={filterQuery}
        />
      );
    case WidgetType.slqCount:
      return <SlqCountCard widget={widget} filterQuery={filterQuery} />;
    case WidgetType.slqList:
      return <SlqListCard widget={widget} filterQuery={filterQuery} />;
    case WidgetType.viewCount:
      return <ViewCountCard widget={widget} filterQuery={filterQuery} />;
    default:
      // A non-builtin type: a live plugin widget renders it; otherwise it's turned off (still in the
      // manifest) or its plugin is gone entirely — the notice distinguishes the two.
      return pluginWidget ? (
        <>{pluginWidget.contribution.render({ config: widget.config, widget, filterQuery })}</>
      ) : (
        <MissingPluginType
          typeKey={widget.widget_type}
          kind="widget"
          disabled={disabledWidgetTypes.has(widget.widget_type)}
        />
      );
  }
}

/** The stand-in for a widget whose scope the viewer can't read (spec 75). */
function UnavailableCard({ title }: { title?: string | null }) {
  return (
    <div className="rounded-xl border border-dashed border-subtle px-4 py-6 text-center text-xs text-fg-faint">
      {title ? `${title} — unavailable` : "Unavailable"}
      <span className="mt-0.5 block text-[11px] text-fg-faint">
        You may not have access to this widget’s data.
      </span>
    </div>
  );
}

/** Throughput/CFD over the default reporting window at the configured interval. */
function ReportRangeWidget({
  widget,
  filterQuery,
}: {
  widget: DashboardWidget;
  filterQuery?: string;
}) {
  const projectId = widget.config.project_id;
  if (!projectId) return <UnavailableCard title={widget.title} />;
  const start = isoDaysAgo(REPORT_DEFAULT_RANGE_DAYS);
  const end = isoDaysAgo(0);
  const interval = widget.config.interval ?? ReportInterval.week;
  return widget.widget_type === WidgetType.reportThroughput ? (
    <ThroughputCard projectId={projectId} start={start} end={end} interval={interval} q={filterQuery} />
  ) : (
    <CumulativeFlowCard projectId={projectId} start={start} end={end} interval={interval} q={filterQuery} />
  );
}

function VelocityWidget({
  widget,
  filterQuery,
}: {
  widget: DashboardWidget;
  filterQuery?: string;
}) {
  const pointsEnabled = usePointsEnabled();
  return (
    <VelocityCard
      showPoints={pointsEnabled || widget.config.measure === ReportMeasure.points}
      initialLast={widget.config.last}
      initialMeasure={widget.config.measure}
      q={filterQuery}
    />
  );
}

function BurnupWidget({
  widget,
  filterQuery,
}: {
  widget: DashboardWidget;
  filterQuery?: string;
}) {
  const pointsEnabled = usePointsEnabled();
  if (!widget.config.cycle_id) return <UnavailableCard title={widget.title} />;
  return (
    <BurnupCard
      showPoints={pointsEnabled || widget.config.measure === ReportMeasure.points}
      fixedCycleId={widget.config.cycle_id}
      initialMeasure={widget.config.measure}
      q={filterQuery}
    />
  );
}

/** The `project_id` slice of an SLQ widget's scope, ready for GET /items[..]. */
function slqScope(widget: DashboardWidget): Record<string, string> {
  return widget.config.project_id ? { project_id: widget.config.project_id } : {};
}

/** A widget's effective query: its own `q` AND the dashboard-wide filter. */
function widgetQuery(widget: DashboardWidget, filterQuery: string | undefined): string {
  const base = widget.config.q ?? "";
  return filterQuery ? combineQueryWithFilters(base, [filterQuery]) : base;
}

/** Big-number card over GET /items/count (spec 75). */
function SlqCountCard({
  widget,
  filterQuery,
}: {
  widget: DashboardWidget;
  filterQuery?: string;
}) {
  const q = widgetQuery(widget, filterQuery);
  const query = useQuery(itemsCountQuery(slqScope(widget), q));
  if (query.isError) return <UnavailableCard title={widget.title} />;
  const label = widget.config.label || widget.title || "Matching items";
  return (
    <div className="rounded-xl border border-subtle bg-surface px-4 py-4 shadow-lift">
      <p className="truncate text-[11px] uppercase tracking-wide text-fg-muted">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums text-heading">
        {query.data ? query.data.total : "…"}
      </p>
      {q && (
        <p className="mt-1 truncate font-mono text-[10px] text-fg-faint" title={q}>
          {q}
        </p>
      )}
    </div>
  );
}

/** Compact item rows over GET /items?q=&limit= — key, title, state pill → peek. */
function SlqListCard({
  widget,
  filterQuery,
}: {
  widget: DashboardWidget;
  filterQuery?: string;
}) {
  const q = widgetQuery(widget, filterQuery);
  const query = useQuery(slqListItemsQuery(slqScope(widget), q, widget.config.limit ?? 10));
  if (query.isError) return <UnavailableCard title={widget.title} />;
  const items = query.data ?? [];
  return (
    <div className="overflow-hidden rounded-xl border border-subtle bg-surface shadow-lift">
      <p className="border-b border-subtle/60 px-4 py-2 text-[11px] uppercase tracking-wide text-fg-muted">
        {widget.title || "Issues"}
      </p>
      {query.isPending ? (
        <Spinner label="Loading…" />
      ) : items.length === 0 ? (
        <p className="px-4 py-4 text-xs text-fg-faint">No matching issues.</p>
      ) : (
        <ul>
          {items.map((item) => (
            <SlqListRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}

function SlqListRow({ item }: { item: Item }) {
  const peek = usePeek();
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
        className="flex w-full cursor-pointer items-center gap-2 border-b border-subtle/60 px-4 py-1.5 text-left last:border-b-0 hover:bg-elevated/50"
      >
        <ItemKeyLink
          itemKey={item.key}
          className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary hover:text-accent-text hover:underline"
        />
        <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{item.title}</span>
        <span className="shrink-0 rounded bg-elevated/80 px-1.5 py-px text-[10px] text-fg-secondary">
          {item.state.name}
        </span>
      </div>
    </li>
  );
}

/**
 * A saved view's membership count via POST /views/counts (spec 64 machinery).
 * The server OMITS invisible/unknown ids — that omission is the per-viewer
 * "Unavailable" signal here.
 */
function ViewCountCard({
  widget,
  filterQuery,
}: {
  widget: DashboardWidget;
  filterQuery?: string;
}) {
  const viewId = widget.config.view_id ?? "";
  const counts = useQuery(viewCountsQuery(viewId ? [viewId] : [], filterQuery));
  const views = useQuery(viewQuery(viewId));
  const view = views.data;
  const project = useQuery(projectByIdQuery(view?.project_id ?? ""));
  if (
    !viewId ||
    counts.isError ||
    (counts.data && counts.data[viewId] === undefined) ||
    views.isError
  ) {
    return <UnavailableCard title={widget.title} />;
  }
  const count = counts.data?.[viewId];
  const label = widget.title || view?.name || "View";
  const projectKey = project.data?.key;
  const body = (
    <>
      <p className="truncate text-[11px] uppercase tracking-wide text-fg-muted">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums text-heading">
        {count !== undefined ? count : "…"}
      </p>
      {view && <p className="mt-1 truncate text-[10px] text-fg-faint">View · {view.name}</p>}
    </>
  );
  const cardClasses =
    "block rounded-lg border border-subtle bg-surface/40 px-4 py-4 hover:border-strong";
  if (view && projectKey) {
    return (
      <Link
        to={RoutePath.projectView}
        params={{ projectKey, viewId: view.id }}
        className={cardClasses}
      >
        {body}
      </Link>
    );
  }
  if (view) {
    return (
      <Link to={RoutePath.allProjectsView} params={{ viewId: view.id }} className={cardClasses}>
        {body}
      </Link>
    );
  }
  return <div className={cardClasses}>{body}</div>;
}
