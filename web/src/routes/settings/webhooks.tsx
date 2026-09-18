import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Plus, RotateCcw, Webhook } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import type { WebhookDelivery, WebhookEndpoint } from "../../lib/types";
import { Button } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { CopyValue } from "../../components/settings/CopyValue";
import { ErrorText } from "../../components/ErrorText";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { pushToast } from "../../lib/toast";
import { ChangeHistoryPanel } from "../../components/history/ChangeHistoryPanel";

/** Settings → Webhooks (RADD-1096). The management API existed since spec 25
 * with the SPA never calling it — endpoints were created by curl and a failing
 * delivery was invisible. This is the door: endpoint CRUD with the signing
 * secret revealed (the receiver must be configured with it), the per-endpoint
 * delivery log, and replay for dead deliveries. */

const endpointsKey = ["webhooks", "endpoints"] as const;

const STATUS_STYLES: Record<string, string> = {
  success: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  pending: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  dead: "bg-red-500/15 text-red-300 ring-red-500/30",
};

export function WebhooksSettingsPage() {
  const queryClient = useQueryClient();
  const endpoints = useQuery({
    queryKey: endpointsKey,
    queryFn: ({ signal }) => api.get<WebhookEndpoint[]>(ApiPath.webhooks, { signal }),
  });
  const [creating, setCreating] = useState(false);

  return (
    <SettingsPage history={{ entities: ["webhook_endpoint"] }}
      title="Webhooks"
      description="Signed HTTP deliveries for every event, with retries. Each endpoint has its own signing secret (Standard Webhooks: whsec_…) — configure the receiver with it, and read the delivery log here when something doesn't arrive."
    >
      <div className="mb-3 flex justify-end">
        <Button onClick={() => setCreating(true)}>
          <Plus size={13} aria-hidden />
          Add endpoint
        </Button>
      </div>
      {creating && (
        <CreateEndpointForm
          onDone={() => {
            setCreating(false);
            void queryClient.invalidateQueries({ queryKey: endpointsKey });
          }}
          onCancel={() => setCreating(false)}
        />
      )}
      {endpoints.isPending ? (
        <TableSkeleton rows={2} />
      ) : endpoints.isError ? (
        <ErrorText error={endpoints.error} />
      ) : endpoints.data.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-fg-muted">
          <Webhook size={14} aria-hidden />
          No endpoints yet — deliveries start as soon as one exists.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {endpoints.data.map((endpoint) => (
            <EndpointRow key={endpoint.id} endpoint={endpoint} />
          ))}
        </ul>
      )}
    </SettingsPage>
  );
}

function CreateEndpointForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [eventTypes, setEventTypes] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api.post<WebhookEndpoint>(ApiPath.webhooks, {
        url: url.trim(),
        description: description.trim(),
        event_types: eventTypes.trim()
          ? eventTypes.split(",").map((entry) => entry.trim()).filter(Boolean)
          : null,
      }),
    onSuccess: (endpoint) => {
      pushToast(`Endpoint added — secret ${endpoint.secret.slice(0, 12)}…`);
      onDone();
    },
  });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (url.trim()) create.mutate();
      }}
      className="mb-4 flex flex-col gap-3 rounded-lg border border-subtle bg-surface/40 p-4"
    >
      <TextField
        label="URL"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="https://receiver.example.com/hooks/radd"
        required
        autoFocus
      />
      <TextField
        label="Description"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        placeholder="What listens here"
      />
      <TextField
        label="Event types"
        value={eventTypes}
        onChange={(event) => setEventTypes(event.target.value)}
        placeholder="item.created, item.updated — empty for every event"
        hint="Comma-separated event types; leave empty to receive everything."
      />
      <div className="flex items-center justify-end gap-2">
        {create.isError && (
          <span className="mr-auto text-xs text-red-400">{errorMessage(create.error)}</span>
        )}
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending || !url.trim()}>
          {create.isPending ? "Adding…" : "Add endpoint"}
        </Button>
      </div>
    </form>
  );
}

function EndpointRow({ endpoint }: { endpoint: WebhookEndpoint }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [confirmDialog, confirm] = useConfirm();
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: endpointsKey });

  const toggleActive = useMutation({
    mutationFn: () =>
      api.patch<WebhookEndpoint>(`${ApiPath.webhooks}/${endpoint.id}`, {
        active: !endpoint.active,
      }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(`${ApiPath.webhooks}/${endpoint.id}`),
    onSuccess: invalidate,
  });

  return (
    <li className="rounded-lg border border-subtle bg-surface/40">
      <div className="flex items-center gap-2 px-3 py-2.5">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} deliveries for ${endpoint.url}`}
          className="shrink-0 rounded p-0.5 text-fg-muted outline-focus hover:bg-elevated hover:text-fg"
        >
          {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-[12px] text-heading">{endpoint.url}</p>
          {endpoint.description && (
            <p className="truncate text-[11px] text-fg-muted">{endpoint.description}</p>
          )}
        </div>
        <span className="hidden text-[11px] text-fg-faint sm:block">
          {endpoint.event_types?.length
            ? `${endpoint.event_types.length} event type${endpoint.event_types.length === 1 ? "" : "s"}`
            : "all events"}
        </span>
        <Button
          size="sm"
          variant="secondary"
          disabled={toggleActive.isPending}
          onClick={() => toggleActive.mutate()}
        >
          {endpoint.active ? "Disable" : "Enable"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="border border-strong hover:border-red-500/50 hover:text-red-300"
          disabled={remove.isPending}
          onClick={() => {
            void confirm({
              title: "Delete endpoint?",
              message: "Its delivery log goes with it. The receiver stops getting events.",
              confirmLabel: "Delete",
              danger: true,
            }).then((ok) => {
              if (ok) remove.mutate();
            });
          }}
        >
          Delete…
        </Button>
      </div>
      {open && (
        <div className="flex flex-col gap-3 border-t border-subtle/60 px-3 py-3">
          <CopyValue label="Signing secret" value={endpoint.secret} secret mono />
          <DeliveryLog endpointId={endpoint.id} />
          <ChangeHistoryPanel entityType="webhook_endpoint" entityId={endpoint.id} />
        </div>
      )}
      {confirmDialog}
      {(toggleActive.isError || remove.isError) && (
        <p className="px-3 pb-2 text-xs text-red-400">
          {errorMessage(toggleActive.isError ? toggleActive.error : remove.error)}
        </p>
      )}
    </li>
  );
}

function DeliveryLog({ endpointId }: { endpointId: string }) {
  const queryClient = useQueryClient();
  const deliveries = useQuery({
    queryKey: ["webhooks", "deliveries", endpointId],
    queryFn: ({ signal }) =>
      api.get<WebhookDelivery[]>(`${ApiPath.webhooks}/${endpointId}/deliveries`, { signal }),
  });
  const replay = useMutation({
    mutationFn: (deliveryId: string) =>
      api.post<WebhookDelivery>(
        `${ApiPath.webhooks}/${endpointId}/deliveries/${deliveryId}/replay`,
      ),
    onSuccess: () => {
      pushToast("Delivery queued for replay with a fresh retry schedule");
      void queryClient.invalidateQueries({ queryKey: ["webhooks", "deliveries", endpointId] });
    },
    onError: (error) => pushToast(errorMessage(error)),
  });

  if (deliveries.isPending) return <TableSkeleton rows={2} />;
  if (deliveries.isError) return <ErrorText error={deliveries.error} />;
  if (deliveries.data.length === 0) {
    return <p className="text-xs text-fg-muted">No deliveries yet.</p>;
  }
  return (
    <ul className="flex flex-col gap-1">
      {deliveries.data.map((delivery) => (
        <li key={delivery.id} className="flex items-center gap-2 text-[12px]">
          <span
            className={`rounded-full px-1.5 py-px text-[10px] font-medium ring-1 ${
              STATUS_STYLES[delivery.status] ?? "bg-elevated text-fg-secondary ring-strong"
            }`}
          >
            {delivery.status}
          </span>
          <span className="font-mono text-[11px] text-fg-muted">event {delivery.event_id}</span>
          <span className="text-fg-faint">
            {delivery.attempts} attempt{delivery.attempts === 1 ? "" : "s"}
          </span>
          {delivery.last_status_code !== null && (
            <span className="text-fg-faint">HTTP {delivery.last_status_code}</span>
          )}
          {delivery.last_error && (
            <span className="min-w-0 flex-1 truncate text-red-300/80" title={delivery.last_error}>
              {delivery.last_error}
            </span>
          )}
          {delivery.status === "dead" && (
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto shrink-0"
              disabled={replay.isPending}
              onClick={() => replay.mutate(delivery.id)}
            >
              <RotateCcw size={12} aria-hidden />
              Replay
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
