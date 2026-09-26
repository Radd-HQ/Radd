import type { ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ErrorText } from "@radd/plugin-sdk";
import { DashboardCanvas } from "./DashboardCanvas";
import { MY_WORK_PATH, dashboardKeys, myWorkQuery } from "./queries";
import type { Dashboard, DashboardWidget } from "./types";

/** My Work's canvas: the person's private layout. The host draws its own kinds through `render`
 *  and hands the rest to `WidgetBody`. */
export function MyWorkCanvas({ render }: { render: (widget: DashboardWidget) => ReactNode }) {
  const client = useQueryClient();
  const query = useQuery(myWorkQuery());
  if (query.isPending) return <p className="text-sm text-fg-muted">Loading My Work…</p>;
  if (query.isError) return <ErrorText error={query.error} />;
  const dashboard: Dashboard = {
    id: "my-work", name: "My Work", description: "", owner_id: null, owner: null, global_access: null,
    shared: false, can_edit: true, can_manage: false, position: 0, widgets: query.data, created_at: "", updated_at: "",
  };
  return (
    <DashboardCanvas dashboard={dashboard} render={render}
      defaults={() => api.get<DashboardWidget[]>(`${MY_WORK_PATH}/defaults`)}
      save={async (widgets, expected) => {
        const saved = await api.put<DashboardWidget[]>(`${MY_WORK_PATH}/widgets`, { widgets, expected });
        client.setQueryData(dashboardKeys.myWork, saved);
      }} />
  );
}
