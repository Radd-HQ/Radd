import { useQueryClient } from "@tanstack/react-query";
import { api, invalidateEntities, SharingDialog, usePermissions } from "@radd/plugin-sdk";
import { dashboardPath } from "./queries";
import type { Dashboard } from "./types";

/** Server-wide access broadcasts to everyone, so it takes the create atom (spec 75). */
const DASHBOARD_CREATE = "dashboard.create";

/**
 * Share a dashboard: the shell's sharing editor (the spec-57 model views share), committed in one
 * owner-authorized transaction through this plugin's own `/save`.
 */
export function DashboardSharingModal({ dashboard, onClose }: { dashboard: Dashboard; onClose: () => void }) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  return (
    <SharingDialog
      title="Share dashboard"
      resourceType="dashboard"
      resourceId={dashboard.id}
      ownerId={dashboard.owner_id}
      globalAccess={dashboard.global_access}
      canBroadcast={perms.global(DASHBOARD_CREATE)}
      onSave={async (body) => {
        await api.post<Dashboard>(`${dashboardPath(dashboard.id)}/save`, body);
        await invalidateEntities(queryClient, "dashboard", "accessGrant");
      }}
      onClose={onClose}
    />
  );
}
