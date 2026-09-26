import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Plus } from "lucide-react";
import { api, errorMessage, useConfirm, usePermissions, Button, EmptyState, QueryError, SettingsPage, Slot,
  TableSkeleton, TextField } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT } from "@radd-plugin-ui/projects/picker-contract";
import { ReceiverRow } from "./ReceiverRow";
import { RECEIVERS_PATH, receiverPath, receiversKey, type AlertReceiver, type ReceiverPatch } from "./types";

function newToken(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Settings → Alertmanager (RADD-1317; the plugin's own page since RADD-1370).
 * Each receiver is a row naming the project its alerts become issues in, and
 * the three things it may do to them. The token is write-only on the server, so
 * a new receiver's token is generated here and shown ONCE, inside the URL
 * Alertmanager must be configured with.
 */
export function AlertmanagerSettingsPage() {
  const canManage = usePermissions().global("global.manage");
  const queryClient = useQueryClient();
  const receivers = useQuery({
    queryKey: receiversKey,
    enabled: canManage,
    queryFn: ({ signal }) => api.get<AlertReceiver[]>(RECEIVERS_PATH, { signal }),
  });
  const [confirmDialog, confirm] = useConfirm();
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", project_id: "" });
  // The token of a receiver just created or re-keyed — the one moment it is visible.
  const [revealed, setRevealed] = useState<{ id: string; token: string } | null>(null);

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: receiversKey });
  const create = useMutation({
    mutationFn: (token: string) =>
      api.post<AlertReceiver>(RECEIVERS_PATH, { name: form.name.trim(), project_id: form.project_id || null, token })
        .then((receiver) => ({ receiver, token })),
    onSuccess: ({ receiver, token }) => {
      setRevealed({ id: receiver.id, token });
      setAdding(false);
      setForm({ name: "", project_id: "" });
      invalidate();
    },
  });
  const update = useMutation({
    mutationFn: (vars: { id: string; body: ReceiverPatch }) => api.patch<AlertReceiver>(receiverPath(vars.id), vars.body),
    onSuccess: (_receiver, vars) => {
      if (vars.body.token) setRevealed({ id: vars.id, token: vars.body.token });
    },
    onSettled: invalidate,
  });
  const remove = useMutation({ mutationFn: (id: string) => api.delete<void>(receiverPath(id)), onSettled: invalidate });

  const askNewToken = async (receiver: AlertReceiver) => {
    const ok = await confirm({
      title: "Generate a new token?",
      message: "The current URL stops working; Alertmanager must be configured with the new one.",
      confirmLabel: "Generate",
    });
    if (ok) update.mutate({ id: receiver.id, body: { token: newToken() } });
  };
  const askDelete = async (receiver: AlertReceiver) => {
    const ok = await confirm({
      title: `Delete ${receiver.name}?`,
      message: "Alerts sent to its URL are refused. Issues it created stay.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(receiver.id);
  };

  return (
    <SettingsPage title="Alertmanager" history={{ entities: ["alertmanager_receiver"] }}
      description="Receivers turn firing Prometheus Alertmanager alerts into issues in a project, one issue per receiver and alert fingerprint.">
      {confirmDialog}
      {!canManage ? (
        <EmptyState icon={BellRing} message="You need instance-admin access to configure Alertmanager." />
      ) : (
        <>
          <p className="mb-4 text-[13px] text-fg-muted" data-alertmanager-note>
            A receiver creates the issue, then does only what its settings below say. Firing, repeats and resolutions are
            also automation triggers, for anything the settings don't cover.
          </p>
          {[update, remove].map((mutation, index) =>
            mutation.isError ? <p key={index} role="alert" className="mb-2 text-xs text-danger-text">{errorMessage(mutation.error)}</p> : null)}
          {receivers.isPending ? (
            <TableSkeleton rows={2} />
          ) : receivers.isError ? (
            <QueryError label="Alertmanager receivers" error={receivers.error} />
          ) : receivers.data.length === 0 ? (
            <EmptyState icon={BellRing} message="No receivers. Add one, then point an Alertmanager webhook_config at its URL." />
          ) : (
            <ul className="space-y-2">
              {receivers.data.map((receiver) => (
                <ReceiverRow key={receiver.id} receiver={receiver}
                  revealedToken={revealed?.id === receiver.id ? revealed.token : null}
                  onPatch={(body) => update.mutate({ id: receiver.id, body })}
                  onNewToken={() => void askNewToken(receiver)} onDelete={() => void askDelete(receiver)} />
              ))}
            </ul>
          )}
          <div className="mt-4">
            {adding ? (
              <form className="space-y-3 rounded-lg border border-subtle p-4" onSubmit={(event: FormEvent) => {
                event.preventDefault();
                create.mutate(newToken());
              }}>
                <TextField label="Name" value={form.name} placeholder="prod-cluster"
                  onChange={(event) => setForm({ ...form, name: event.target.value })} />
                <Slot id={PROJECT_SELECT_SLOT} value={form.project_id} label="Project" emptyLabel="Choose a project…"
                  onChange={(id: string) => setForm({ ...form, project_id: id })}
                  fallback={<span className="text-xs text-fg-muted">Projects are unavailable.</span>} />
                <div className="flex gap-2">
                  <Button type="submit" disabled={create.isPending || !form.name.trim() || !form.project_id}>Create receiver</Button>
                  <Button type="button" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
                </div>
                {create.isError && <p role="alert" className="text-[12px] text-danger-text">{errorMessage(create.error)}</p>}
              </form>
            ) : (
              <Button variant="secondary" onClick={() => setAdding(true)}>
                <Plus size={14} aria-hidden /> Add a receiver
              </Button>
            )}
          </div>
        </>
      )}
    </SettingsPage>
  );
}
