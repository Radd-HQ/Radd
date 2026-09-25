import { useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Plus } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, RoutePath } from "../../lib/constants";
import { projectsQuery } from "../../lib/queries";
import { Button } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { CopyValue } from "../../components/settings/CopyValue";
import { EmptyState } from "../../components/EmptyState";
import { QueryError } from "../../components/QueryError";
import { SelectField } from "../../components/SelectField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { IntegrationAutomations } from "../../components/settings/IntegrationAutomations";

/**
 * Settings → Alertmanager (RADD-1317). Receivers used to be one env token and
 * an env project key; now each is a row naming the project its alerts become
 * issues in. The token is write-only on the server (`has_token`), so a new
 * receiver's token is generated here and shown ONCE, inside the webhook URL
 * Alertmanager must be configured with.
 */

type AlertReceiver = {
  id: string;
  name: string;
  project_id: string | null;
  active: boolean;
  has_token: boolean;
  created_at: string;
};

const receiversKey = ["alertmanager", "receivers"] as const;

function newToken(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function webhookUrl(token: string): string {
  return `${window.location.origin}/api/v1/integrations/alertmanager?token=${token}`;
}

export function AlertmanagerSettingsPage() {
  const queryClient = useQueryClient();
  const receivers = useQuery({
    queryKey: receiversKey,
    queryFn: () => api.get<AlertReceiver[]>(ApiPath.alertmanagerReceivers),
  });
  const projects = useQuery(projectsQuery());
  const [confirmDialog, confirm] = useConfirm();
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", project_id: "" });
  // The token of a receiver just created or re-keyed — the one moment it is visible.
  const [revealed, setRevealed] = useState<{ id: string; token: string } | null>(null);

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: receiversKey });
  const create = useMutation({
    mutationFn: (token: string) =>
      api
        .post<AlertReceiver>(ApiPath.alertmanagerReceivers, {
          name: form.name.trim(),
          project_id: form.project_id || null,
          token,
        })
        .then((receiver) => ({ receiver, token })),
    onSuccess: ({ receiver, token }) => {
      setRevealed({ id: receiver.id, token });
      setAdding(false);
      setForm({ name: "", project_id: "" });
      invalidate();
    },
  });
  const update = useMutation({
    mutationFn: (vars: { id: string; body: Partial<AlertReceiver> & { token?: string } }) =>
      api.patch<AlertReceiver>(`${ApiPath.alertmanagerReceivers}/${vars.id}`, vars.body),
    onSuccess: (_receiver, vars) => {
      if (vars.body.token) setRevealed({ id: vars.id, token: vars.body.token });
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`${ApiPath.alertmanagerReceivers}/${id}`),
    onSuccess: invalidate,
  });

  const projectKey = (id: string | null) => projects.data?.find((project) => project.id === id)?.key;

  return (
    <SettingsPage
      title="Alertmanager"
      description="Receivers turn firing Prometheus Alertmanager alerts into issues in a project, one issue per receiver and alert fingerprint."
      history={{ entities: ["alertmanager_receiver"] }}
    >
      {confirmDialog}
      <IntegrationAutomations group="Alertmanager" />
      <p className="mb-4 text-[13px] text-fg-muted" data-alertmanager-note>
        A receiver creates the issue and changes nothing else. What a repeat or a resolution should do (comment, move
        the issue, label it) is an automation: start from an Alertmanager template in{" "}
        <Link to={RoutePath.settingsAutomations} className="text-accent-text hover:underline">
          Automations
        </Link>
        .
      </p>
      {receivers.isPending ? (
        <TableSkeleton rows={2} />
      ) : receivers.isError ? (
        <QueryError label="Alertmanager receivers" error={receivers.error} />
      ) : receivers.data.length === 0 ? (
        <EmptyState icon={BellRing} message="No receivers. Add one, then point an Alertmanager webhook_config at its URL." />
      ) : (
        <ul className="space-y-2">
          {receivers.data.map((receiver) => (
            <li key={receiver.id} className="rounded-lg border border-subtle bg-surface/40" data-receiver={receiver.name}>
              <div className="flex items-center gap-3 px-3 py-2.5">
                <BellRing size={14} className="text-fg-muted" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-heading">{receiver.name}</span>
                {!receiver.project_id && (
                  <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-warning-text">no project</span>
                )}
                {!receiver.active && (
                  <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-muted">inactive</span>
                )}
                <SelectField
                  label=""
                  ariaLabel={`Project for ${receiver.name}`}
                  value={receiver.project_id ?? ""}
                  onChange={(event) =>
                    update.mutate({ id: receiver.id, body: { project_id: event.target.value || null } })
                  }
                >
                  <option value="">No project</option>
                  {(projects.data ?? []).map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.key}
                    </option>
                  ))}
                </SelectField>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={update.isPending}
                  onClick={() => update.mutate({ id: receiver.id, body: { active: !receiver.active } })}
                >
                  {receiver.active ? "Disable" : "Enable"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    void confirm({
                      title: "Generate a new token?",
                      message: "The current URL stops working; Alertmanager must be configured with the new one.",
                      confirmLabel: "Generate",
                    }).then((ok) => {
                      if (ok) update.mutate({ id: receiver.id, body: { token: newToken() } });
                    });
                  }}
                >
                  New token…
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    void confirm({
                      title: `Delete ${receiver.name}?`,
                      message: "Alerts sent to its URL are refused. Issues it created stay.",
                      confirmLabel: "Delete",
                      danger: true,
                    }).then((ok) => {
                      if (ok) remove.mutate(receiver.id);
                    });
                  }}
                >
                  Delete…
                </Button>
              </div>
              {revealed?.id === receiver.id && (
                <div className="flex flex-col gap-2 border-t border-subtle/60 px-3 py-3" data-receiver-url>
                  <CopyValue label="Webhook URL" value={webhookUrl(revealed.token)} mono />
                  <p className="text-[11px] text-fg-muted">
                    Shown once — the token is not stored anywhere you can read it back. Delivering into{" "}
                    {projectKey(receiver.project_id) ?? "no project yet"}.
                  </p>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4">
        {adding ? (
          <form
            className="space-y-3 rounded-lg border border-subtle p-4"
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              create.mutate(newToken());
            }}
          >
            <TextField
              label="Name"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="prod-cluster"
            />
            <SelectField
              label="Project"
              value={form.project_id}
              onChange={(event) => setForm({ ...form, project_id: event.target.value })}
            >
              <option value="">Choose a project…</option>
              {(projects.data ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.key} · {project.name}
                </option>
              ))}
            </SelectField>
            <div className="flex gap-2">
              <Button type="submit" disabled={create.isPending || !form.name.trim() || !form.project_id}>
                Create receiver
              </Button>
              <Button type="button" variant="ghost" onClick={() => setAdding(false)}>
                Cancel
              </Button>
            </div>
            {create.isError && <p className="text-[12px] text-danger-text">{errorMessage(create.error)}</p>}
          </form>
        ) : (
          <Button variant="secondary" onClick={() => setAdding(true)}>
            <Plus size={14} aria-hidden /> Add a receiver
          </Button>
        )}
      </div>
    </SettingsPage>
  );
}
