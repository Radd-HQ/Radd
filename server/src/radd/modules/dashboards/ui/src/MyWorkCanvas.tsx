import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Button, ErrorText } from "@radd/plugin-sdk";
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
    <DashboardCanvas dashboard={dashboard} render={render} notice={<WidgetOffers />}
      defaults={() => api.get<DashboardWidget[]>(`${MY_WORK_PATH}/defaults`)}
      save={async (widgets, expected) => {
        const saved = await api.put<DashboardWidget[]>(`${MY_WORK_PATH}/widgets`, { widgets, expected });
        client.setQueryData(dashboardKeys.myWork, saved);
      }} />
  );
}

/** A widget that became available after this person arranged My Work (RADD-1579): the suggested
 *  layout never reaches them, so it is offered here, once. Either answer is remembered. */
function WidgetOffers() {
  const client = useQueryClient();
  const offers = useQuery({
    queryKey: dashboardKeys.myWorkOffers, staleTime: 300_000,
    queryFn: ({ signal }) => api.get<DashboardWidget[]>(`${MY_WORK_PATH}/offers`, { signal }),
  });
  const answer = useMutation({
    mutationFn: ({ widget, accept }: { widget: DashboardWidget; accept: boolean }) =>
      api.post<DashboardWidget[]>(`${MY_WORK_PATH}/offers/${widget.widget_type}`, { accept }),
    onSuccess: (layout, { widget }) => {
      client.setQueryData(dashboardKeys.myWork, layout);
      client.setQueryData(dashboardKeys.myWorkOffers, (old: DashboardWidget[] | undefined) => (old ?? []).filter(w => w.id !== widget.id));
    },
  });
  if (!offers.data?.length) return null;
  return <ul className="space-y-2">
    {offers.data.map(widget => (
      <li key={widget.id} data-widget-offer={widget.widget_type}
        className="flex flex-wrap items-center gap-2 rounded-lg border border-subtle bg-surface px-4 py-2 text-row text-fg">
        <span className="mr-auto"><span className="font-medium text-heading">{widget.title}</span> is now available on My Work.</span>
        {answer.isError && <ErrorText error={answer.error} />}
        <Button size="sm" variant="ghost" disabled={answer.isPending} data-widget-offer-dismiss onClick={() => answer.mutate({ widget, accept: false })}>Not now</Button>
        <Button size="sm" disabled={answer.isPending} data-widget-offer-add onClick={() => answer.mutate({ widget, accept: true })}>Add it</Button>
      </li>
    ))}
  </ul>;
}
