/** The builtin query widgets: a count, a short list, and a saved view's count (spec 75). */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ItemKeyLink, ItemPeek, Spinner, type Item } from "@radd/plugin-sdk";
import type { DashboardWidget } from "./types";
import { andFilter } from "./widget-meta";
import { itemsCountQuery, itemsListQuery, projectKeyQuery, viewCountQuery, viewQuery } from "./widget-queries";

interface WidgetProps {
  widget: DashboardWidget;
  filterQuery?: string;
}

/** The stand-in for a widget whose scope the viewer can't read (spec 75). */
export function UnavailableCard({ title }: { title?: string | null }) {
  return (
    <div className="rounded-xl border border-dashed border-subtle px-4 py-6 text-center text-xs text-fg-faint">
      {title ? `${title} — unavailable` : "Unavailable"}
      <span className="mt-0.5 block text-[11px] text-fg-faint">You may not have access to this widget’s data.</span>
    </div>
  );
}

/** The `project_id` slice of an SLQ widget's scope, ready for GET /items[..]. */
function slqScope(widget: DashboardWidget): Record<string, string> {
  return widget.config.project_id ? { project_id: widget.config.project_id } : {};
}

/** Big-number card over GET /items/count. */
export function SlqCountCard({ widget, filterQuery }: WidgetProps) {
  const q = andFilter(widget.config.q ?? "", filterQuery);
  const query = useQuery(itemsCountQuery(slqScope(widget), q));
  if (query.isError) return <UnavailableCard title={widget.title} />;
  const label = widget.config.label;
  return (
    <div className="px-1 py-1">
      {label && <p className="truncate text-xs text-fg-muted">{label}</p>}
      <p className="mt-1 text-3xl font-semibold tabular-nums text-heading">{query.data ? query.data.total : "…"}</p>
      {q && <p className="mt-1 truncate font-mono text-[10px] text-fg-faint" title={q}>{q}</p>}
    </div>
  );
}

/** Compact item rows over GET /items?q=&limit= — key, title, state pill → peek. */
export function SlqListCard({ widget, filterQuery }: WidgetProps) {
  const q = andFilter(widget.config.q ?? "", filterQuery);
  const query = useQuery(itemsListQuery(slqScope(widget), q, widget.config.limit ?? 10));
  if (query.isError) return <UnavailableCard title={widget.title} />;
  const items = query.data ?? [];
  return (
    <div className="overflow-hidden">
      {query.isPending ? <Spinner label="Loading…" />
        : items.length === 0 ? <p className="px-4 py-4 text-xs text-fg-faint">No matching issues.</p>
        : <ul>{items.map((item) => <SlqListRow key={item.id} item={item} />)}</ul>}
    </div>
  );
}

function SlqListRow({ item }: { item: Item }) {
  return (
    <li>
      {/* div, not button: the key inside is a real link (anchors can't nest in buttons) */}
      <ItemPeek itemKey={item.key}>{(open) => (
        <div role="button" tabIndex={0} onClick={open} onKeyDown={(event) => { if (event.key === "Enter") open(); }}
          className="flex w-full cursor-pointer items-center gap-2 border-b border-subtle/60 px-4 py-1.5 text-left last:border-b-0 hover:bg-elevated/50">
          <ItemKeyLink itemKey={item.key}
            className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary hover:text-accent-text hover:underline" />
          <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{item.title}</span>
          <span className="shrink-0 rounded bg-elevated/80 px-1.5 py-px text-[10px] text-fg-secondary">{item.state.name}</span>
        </div>
      )}</ItemPeek>
    </li>
  );
}

/**
 * A saved view's membership count via POST /views/counts. The server OMITS invisible/unknown
 * ids — that omission is the per-viewer "Unavailable" signal here.
 */
export function ViewCountCard({ widget, filterQuery }: WidgetProps) {
  const viewId = widget.config.view_id ?? "";
  const counts = useQuery(viewCountQuery(viewId, filterQuery));
  const views = useQuery(viewQuery(viewId));
  const view = views.data;
  const project = useQuery(projectKeyQuery(view?.project_id ?? ""));
  if (!viewId || counts.isError || (counts.data && counts.data[viewId] === undefined) || views.isError) {
    return <UnavailableCard title={widget.title} />;
  }
  const count = counts.data?.[viewId];
  const body = (
    <>
      <p className="truncate text-[11px] uppercase tracking-wide text-fg-muted">{widget.title || view?.name || "View"}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums text-heading">{count !== undefined ? count : "…"}</p>
      {view && <p className="mt-1 truncate text-[10px] text-fg-faint">View · {view.name}</p>}
    </>
  );
  const cardClasses = "block rounded-lg border border-subtle bg-surface/40 px-4 py-4 hover:border-strong";
  const projectKey = project.data?.key;
  if (view && projectKey) {
    return <Link to="/p/$projectKey/v/$viewId" params={{ projectKey, viewId: view.id }} className={cardClasses}>{body}</Link>;
  }
  if (view && !view.project_id) {
    return <Link to="/v/$viewId" params={{ viewId: view.id }} className={cardClasses}>{body}</Link>;
  }
  return <div className={cardClasses}>{body}</div>;
}
