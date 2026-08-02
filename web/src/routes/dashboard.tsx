import { useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  LayoutDashboard,
  Pencil,
  Plus,
  Share2,
  StretchHorizontal,
  Trash2,
  X,
} from "lucide-react";
import { api, errorMessage } from "../lib/api";
import { Entity, invalidateEntities } from "../lib/cache";
import { RoutePath, apiDashboardPath, apiDashboardWidgetPath } from "../lib/constants";
import { dashboardQuery } from "../lib/queries";
import type { Dashboard, DashboardWidget, DashboardWidgetUpdate } from "../lib/types";
import { Button } from "../components/Button";
import { useConfirm } from "../components/ConfirmDialog";
import { Spinner } from "../components/Spinner";
import { DashboardModal } from "../components/dashboards/DashboardModal";
import { DashboardSharingModal } from "../components/dashboards/DashboardSharingModal";
import { WidgetModal } from "../components/dashboards/WidgetModal";
import { WidgetBody } from "../components/dashboards/WidgetCard";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";
import { useSlqQueryState } from "../lib/slq-filter";

/** Literal col-span classes so Tailwind sees them (width = grid thirds 1..3). */
const WIDTH_CLASSES: Record<number, string> = {
  1: "lg:col-span-1",
  2: "lg:col-span-2",
  3: "lg:col-span-3",
};

/** Report widgets carry their own card chrome — the caption renders only for them. */
const SELF_TITLED_PREFIX = "report_";

/**
 * A composable dashboard (spec 75): a 3-column CSS grid of widgets, each
 * spanning its configured width. Widgets fetch through the EXISTING read
 * surfaces, so a widget the viewer can't read shows an Unavailable card and
 * the page never dies. Edit affordances (add/edit/resize/reorder/remove
 * widgets, rename) show for owner/editor; Sharing/Delete for owner/co-owner.
 */
export function DashboardPage() {
  const { dashboardId = "" } = useParams({ strict: false });
  const query = useQuery({ ...dashboardQuery(dashboardId), enabled: dashboardId !== "" });
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [editOpen, setEditOpen] = useState(false);
  const [sharingOpen, setSharingOpen] = useState(false);
  /** null = closed; {} = add; {widget} = edit that widget. */
  const [widgetModal, setWidgetModal] = useState<{ widget?: DashboardWidget } | null>(null);
  const [confirmDialog, confirm] = useConfirm();
  // Dashboard-wide SLQ filter (top-bar query): ANDs into every SLQ-driven
  // widget's own query — report widgets (server-side time-series aggregates)
  // don't take an SLQ and ignore it.
  const slqFilter = useSlqQueryState();

  const patchWidget = useMutation({
    mutationFn: ({ widgetId, patch }: { widgetId: string; patch: DashboardWidgetUpdate }) =>
      api.patch<Dashboard>(apiDashboardWidgetPath(dashboardId, widgetId), patch),
    onSettled: () => invalidateEntities(queryClient, Entity.dashboard),
  });

  const removeWidget = useMutation({
    mutationFn: (widgetId: string) =>
      api.delete<void>(apiDashboardWidgetPath(dashboardId, widgetId)),
    onSettled: () => invalidateEntities(queryClient, Entity.dashboard),
  });

  const swapWidgets = useMutation({
    /** Reorder = swap position values with the neighbour (two PATCHes). */
    mutationFn: async ({ a, b }: { a: DashboardWidget; b: DashboardWidget }) => {
      await api.patch<Dashboard>(apiDashboardWidgetPath(dashboardId, a.id), {
        position: b.position,
      });
      await api.patch<Dashboard>(apiDashboardWidgetPath(dashboardId, b.id), {
        position: a.position,
      });
    },
    onSettled: () => invalidateEntities(queryClient, Entity.dashboard),
  });

  const removeDashboard = useMutation({
    mutationFn: () => api.delete<void>(apiDashboardPath(dashboardId)),
    onSuccess: async () => {
      await invalidateEntities(queryClient, Entity.dashboard);
      void navigate({ to: RoutePath.home });
    },
  });

  if (query.isPending) return <Spinner label="Loading dashboard…" />;
  const dashboard = query.data;
  if (query.isError || !dashboard) {
    return (
      <div className="p-10 text-sm text-fg-muted">
        Dashboard not found — it may have been deleted or unshared.
      </div>
    );
  }

  // Server orders by position; normalize indices so swaps always differ even
  // when two widgets share a stored position value.
  const widgets = dashboard.widgets.map((widget, index) => ({ ...widget, position: index }));

  const move = (index: number, delta: number) => {
    const target = widgets[index + delta];
    if (target && !swapWidgets.isPending) {
      swapWidgets.mutate({ a: widgets[index], b: target });
    }
  };

  return (
    <div className="flex h-full flex-col">
      <TopBarQuery>
        <QueryBar
          filter={slqFilter}
          placeholder="Filter every widget with SLQ: team = Pipeline AND priority = high"
        />
      </TopBarQuery>
      <header className="flex items-center gap-2.5 border-b border-subtle px-6 py-3.5">
        <LayoutDashboard size={16} className="text-fg-secondary" aria-hidden />
        <h1 className="text-sm font-semibold text-heading">{dashboard.name}</h1>
        {dashboard.owner && (
          <span className="text-xs text-fg-muted">by {dashboard.owner.name}</span>
        )}
        {dashboard.description && (
          <span className="truncate text-xs text-fg-faint">· {dashboard.description}</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {dashboard.can_edit && (
            <>
              <Button onClick={() => setWidgetModal({})}>
                <Plus size={13} aria-hidden /> Add widget
              </Button>
              <Button variant="ghost" onClick={() => setEditOpen(true)} title="Rename dashboard">
                <Pencil size={13} aria-hidden /> Edit
              </Button>
            </>
          )}
          {dashboard.can_manage && (
            <>
              <Button variant="ghost" onClick={() => setSharingOpen(true)}>
                <Share2 size={13} aria-hidden /> Share
              </Button>
              <Button
                variant="ghost"
                onClick={() =>
                  void confirm({
                    title: "Delete dashboard",
                    message: `Delete dashboard “${dashboard.name}”? This can't be undone.`,
                    confirmLabel: "Delete",
                    danger: true,
                  }).then((ok) => {
                    if (ok) removeDashboard.mutate();
                  })
                }
                title="Delete dashboard"
              >
                <Trash2 size={13} aria-hidden /> Delete
              </Button>
            </>
          )}
        </div>
      </header>

      {removeDashboard.isError && (
        <p className="px-6 py-2 text-xs text-red-400">{errorMessage(removeDashboard.error)}</p>
      )}

      <div className="flex-1 overflow-y-auto">
        {widgets.length === 0 ? (
          <div className="mx-6 my-8 rounded-lg border border-dashed border-subtle px-6 py-10 text-center">
            <p className="text-sm text-fg-muted">No widgets yet.</p>
            {dashboard.can_edit && (
              <div className="mt-3">
                <Button onClick={() => setWidgetModal({})}>
                  <Plus size={13} aria-hidden /> Add the first widget
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 items-start gap-3 bg-base px-4 py-4 lg:grid-cols-3">
            {widgets.map((widget, index) => (
              <div
                key={widget.id}
                className={`group/widget relative min-w-0 ${WIDTH_CLASSES[widget.width] ?? WIDTH_CLASSES[1]}`}
              >
                {dashboard.can_edit && (
                  <WidgetToolbar
                    widget={widget}
                    first={index === 0}
                    last={index === widgets.length - 1}
                    onEdit={() => setWidgetModal({ widget })}
                    onWidth={() =>
                      patchWidget.mutate({
                        widgetId: widget.id,
                        patch: { width: (widget.width % 3) + 1 },
                      })
                    }
                    onMoveUp={() => move(index, -1)}
                    onMoveDown={() => move(index, 1)}
                    onRemove={() => removeWidget.mutate(widget.id)}
                  />
                )}
                {widget.title && widget.widget_type.startsWith(SELF_TITLED_PREFIX) && (
                  <p className="mb-1 text-[11px] uppercase tracking-wide text-fg-muted">
                    {widget.title}
                  </p>
                )}
                <WidgetBody widget={widget} filterQuery={slqFilter.committed || undefined} />
              </div>
            ))}
          </div>
        )}
      </div>

      {editOpen && (
        <DashboardModal dashboard={dashboard} onClose={() => setEditOpen(false)} />
      )}
      {sharingOpen && (
        <DashboardSharingModal dashboard={dashboard} onClose={() => setSharingOpen(false)} />
      )}
      {widgetModal && (
        <WidgetModal
          dashboard={dashboard}
          widget={widgetModal.widget}
          onClose={() => setWidgetModal(null)}
        />
      )}
      {confirmDialog}
    </div>
  );
}

/** Hover toolbar over a widget (edit / width 1-2-3 / move / remove). */
function WidgetToolbar({
  widget,
  first,
  last,
  onEdit,
  onWidth,
  onMoveUp,
  onMoveDown,
  onRemove,
}: {
  widget: DashboardWidget;
  first: boolean;
  last: boolean;
  onEdit: () => void;
  onWidth: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
}) {
  const buttonClasses =
    "rounded p-1 text-fg-muted hover:bg-strong hover:text-fg cursor-pointer " +
    "focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-focus";
  return (
    <div
      className="absolute right-2 top-2 z-10 flex items-center gap-0.5 rounded-md border border-strong bg-surface/95 px-1 py-0.5 opacity-0 shadow transition-opacity focus-within:opacity-100 group-hover/widget:opacity-100"
      role="toolbar"
      aria-label="Widget actions"
    >
      <button type="button" onClick={onEdit} title="Edit widget" className={buttonClasses}>
        <Pencil size={12} aria-hidden />
      </button>
      <button
        type="button"
        onClick={onWidth}
        title={`Width: ${widget.width}/3 — click to cycle`}
        className={buttonClasses}
      >
        <StretchHorizontal size={12} aria-hidden />
      </button>
      <button
        type="button"
        onClick={onMoveUp}
        disabled={first}
        title="Move up"
        className={`${buttonClasses} disabled:opacity-30`}
      >
        <ChevronUp size={12} aria-hidden />
      </button>
      <button
        type="button"
        onClick={onMoveDown}
        disabled={last}
        title="Move down"
        className={`${buttonClasses} disabled:opacity-30`}
      >
        <ChevronDown size={12} aria-hidden />
      </button>
      <button
        type="button"
        onClick={onRemove}
        title="Remove widget"
        className={`${buttonClasses} hover:text-red-400`}
      >
        <X size={12} aria-hidden />
      </button>
    </div>
  );
}
