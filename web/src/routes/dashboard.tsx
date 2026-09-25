import { useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import { api } from "../lib/api";
import { Entity, invalidateEntities } from "../lib/cache";
import { RoutePath, apiDashboardPath } from "../lib/constants";
import { dashboardQuery } from "../lib/queries";
import { Button } from "../components/Button";
import { useConfirm } from "../components/ConfirmDialog";
import { Spinner } from "../components/Spinner";
import { DashboardModal } from "../components/dashboards/DashboardModal";
import { DashboardSharingModal } from "../components/dashboards/DashboardSharingModal";
import { DashboardCanvas } from "../components/dashboards/DashboardCanvas";
import { WidgetBody } from "../components/dashboards/WidgetCard";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";
import { useSlqQueryState } from "../lib/slq-filter";
import { ErrorText } from "../components/ErrorText";

export function DashboardPage() {
  const { dashboardId = "" } = useParams({ strict: false });
  const query = useQuery({ ...dashboardQuery(dashboardId), enabled: dashboardId !== "" });
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [editOpen, setEditOpen] = useState(false);
  const [sharingOpen, setSharingOpen] = useState(false);
  const [confirmDialog, confirm] = useConfirm();
  // Dashboard-wide SLQ filter (top-bar query): ANDs into every SLQ-driven
  // widget's own query — report widgets (server-side time-series aggregates)
  // don't take an SLQ and ignore it.
  const slqFilter = useSlqQueryState();

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
              <Button variant="ghost" onClick={() => setEditOpen(true)} title="Rename dashboard">
                <Pencil size={13} aria-hidden /> Rename
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
        <ErrorText className="px-6 py-2" error={removeDashboard.error} />
      )}

      <div className="flex-1 overflow-y-auto p-4">
        <DashboardCanvas key={dashboard.id} dashboard={dashboard}
          save={async (widgets, expected) => {
            await api.put(`${apiDashboardPath(dashboardId)}/widgets`, { widgets, expected });
            await invalidateEntities(queryClient, Entity.dashboard);
          }} render={widget => <WidgetBody widget={widget} filterQuery={slqFilter.committed} />} />
      </div>

      {editOpen && (
        <DashboardModal dashboard={dashboard} onClose={() => setEditOpen(false)} />
      )}
      {sharingOpen && (
        <DashboardSharingModal dashboard={dashboard} onClose={() => setSharingOpen(false)} />
      )}
      {confirmDialog}
    </div>
  );
}
