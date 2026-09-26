import { useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutDashboard, Pencil, Share2, Trash2 } from "lucide-react";
import { api, Button, ErrorText, invalidateEntities, PageQueryFilter, Spinner, useConfirm } from "@radd/plugin-sdk";
import { DashboardCanvas } from "./DashboardCanvas";
import { DashboardModal } from "./DashboardModal";
import { DashboardSharingModal } from "./DashboardSharingModal";
import { dashboardPath, dashboardQuery } from "./queries";
import { WidgetBody } from "./WidgetBody";

/**
 * A shared dashboard (spec 75) at `/dashboards/$dashboardId` — the host's route, this plugin's page.
 * The top bar's SLQ filter ANDs into every widget: SLQ widgets into their own query, report and
 * view-count widgets as the endpoints' extra filter.
 */
export function DashboardPage() {
  const { dashboardId = "" } = useParams({ strict: false });
  const query = useQuery(dashboardQuery(dashboardId));
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [editOpen, setEditOpen] = useState(false);
  const [sharingOpen, setSharingOpen] = useState(false);
  const [confirmDialog, confirm] = useConfirm();

  const removeDashboard = useMutation({
    mutationFn: () => api.delete<void>(dashboardPath(dashboardId)),
    onSuccess: async () => {
      await invalidateEntities(queryClient, "dashboard");
      void navigate({ to: "/" });
    },
  });

  if (query.isPending) return <Spinner label="Loading dashboard…" />;
  const dashboard = query.data;
  if (query.isError || !dashboard) {
    return <div className="p-10 text-sm text-fg-muted">Dashboard not found — it may have been deleted or unshared.</div>;
  }
  const remove = () => void confirm({
    title: "Delete dashboard",
    message: `Delete dashboard “${dashboard.name}”? This can't be undone.`,
    confirmLabel: "Delete",
    danger: true,
  }).then((ok) => { if (ok) removeDashboard.mutate(); });

  return (
    <PageQueryFilter placeholder="Filter every widget with SLQ: team = Pipeline AND priority = high">{(filterQuery) => (
      <div className="flex h-full flex-col" data-dashboard-page={dashboard.id}>
        <header className="flex items-center gap-2.5 border-b border-subtle px-6 py-3.5">
          <LayoutDashboard size={16} className="text-fg-secondary" aria-hidden />
          <h1 className="text-sm font-semibold text-heading">{dashboard.name}</h1>
          {dashboard.owner && <span className="text-xs text-fg-muted">by {dashboard.owner.name}</span>}
          {dashboard.description && <span className="truncate text-xs text-fg-faint">· {dashboard.description}</span>}
          <div className="ml-auto flex items-center gap-2">
            {dashboard.can_edit && (
              <Button variant="ghost" onClick={() => setEditOpen(true)} title="Rename dashboard">
                <Pencil size={13} aria-hidden /> Rename
              </Button>
            )}
            {dashboard.can_manage && <>
              <Button variant="ghost" onClick={() => setSharingOpen(true)}>
                <Share2 size={13} aria-hidden /> Share
              </Button>
              <Button variant="ghost" onClick={remove} title="Delete dashboard">
                <Trash2 size={13} aria-hidden /> Delete
              </Button>
            </>}
          </div>
        </header>
        {removeDashboard.isError && <ErrorText className="px-6 py-2" error={removeDashboard.error} />}
        <div className="flex-1 overflow-y-auto p-4">
          <DashboardCanvas key={dashboard.id} dashboard={dashboard}
            save={async (widgets, expected) => {
              await api.put(`${dashboardPath(dashboardId)}/widgets`, { widgets, expected });
              await invalidateEntities(queryClient, "dashboard");
            }} render={(widget) => <WidgetBody widget={widget} filterQuery={filterQuery} />} />
        </div>
        {editOpen && <DashboardModal dashboard={dashboard} onClose={() => setEditOpen(false)} />}
        {sharingOpen && <DashboardSharingModal dashboard={dashboard} onClose={() => setSharingOpen(false)} />}
        {confirmDialog}
      </div>
    )}</PageQueryFilter>
  );
}
