import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Loader2, Plug, Star, Trash2 } from "lucide-react";
import { api } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import { jiraConnectionsQuery, queryKeys } from "../../../lib/queries";
import {
  JIRA_AUTH_MODE_LABELS,
  JIRA_AUTH_MODE_SHORT,
  JiraAuthMode,
  JiraConnectionSource,
  type JiraConnection,
  type JiraConnectionInput,
  type JiraConnectionStatus,
  type JiraAuthModeValue,
} from "../../../lib/types";
import { Button } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { EmptyState } from "../../EmptyState";
import { Modal } from "../../Modal";
import { QueryError } from "../../QueryError";
import { SelectField } from "../../SelectField";
import { Table, TBody, Td, THead, Th } from "../../Table";
import { TableSkeleton } from "../../TableSkeleton";
import { TextField } from "../../TextField";
import { ErrorText } from "../../ErrorText";

const EMPTY: JiraConnectionInput = {
  name: "",
  base_url: "",
  auth_mode: JiraAuthMode.pat,
  username: "",
  credential: "",
  verify_ssl: true,
  is_default: false,
};

/**
 * Jira connections (spec 100) — which instances Radd can import from.
 *
 * Replaces spec 90's environment-only configuration, which named exactly one
 * instance and needed a redeploy to change, including to fix a typo in the URL.
 * An env-seeded row is an ordinary editable connection; its origin is shown only
 * so an admin can tell where it came from.
 */
export function ConnectionsPanel() {
  const queryClient = useQueryClient();
  const connections = useQuery(jiraConnectionsQuery());
  const [editing, setEditing] = useState<JiraConnection | null>(null);
  const [adding, setAdding] = useState(false);
  const [tested, setTested] = useState<Record<string, JiraConnectionStatus>>({});
  const [confirmNode, confirm] = useConfirm();

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.jiraConnections });
    void queryClient.invalidateQueries({ queryKey: queryKeys.jiraStatus });
    void queryClient.invalidateQueries({ queryKey: ["jiraProjects"] });
  };

  const test = useMutation({
    mutationFn: (id: string) =>
      api.post<JiraConnectionStatus>(`${ApiPath.jiraConnections}/${id}/test`, {}),
    onSuccess: (status, id) => setTested((prev) => ({ ...prev, [id]: status })),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${ApiPath.jiraConnections}/${id}`),
    onSuccess: invalidate,
  });

  const makeDefault = useMutation({
    mutationFn: (id: string) =>
      api.patch<JiraConnection>(`${ApiPath.jiraConnections}/${id}`, { is_default: true }),
    onSuccess: invalidate,
  });

  const onDelete = async (connection: JiraConnection) => {
    const ok = await confirm({
      title: `Delete ${connection.name}?`,
      message:
        "Snapshots already downloaded from it are kept — they are cached locally and do not need the connection. New downloads will not be possible.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(connection.id);
  };

  return (
    <section className="rounded-lg border border-subtle bg-surface p-4">
      {confirmNode}
      <header className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-medium text-heading">Connections</h2>
          <p className="mt-0.5 text-xs text-fg-secondary">
            The Jira instances Radd can import from. Changes take effect immediately — no restart.
          </p>
        </div>
        <Button size="sm" onClick={() => setAdding(true)}>
          Add connection
        </Button>
      </header>

      {connections.isPending ? (
        <TableSkeleton rows={2} />
      ) : connections.isError ? (
        <QueryError label="Jira connections" error={connections.error} />
      ) : connections.data.length === 0 ? (
        <EmptyState
          icon={Plug}
          message="No Jira connections yet — add one to start an import."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                <Th>URL</Th>
                <Th>Auth</Th>
                <Th>Status</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </THead>
            <TBody>
              {connections.data.map((connection) => (
                <tr key={connection.id}>
                  <Td>
                    <span className="flex items-center gap-1.5 text-heading">
                      {connection.name}
                      {connection.is_default && (
                        <span
                          title="Used when an import does not name a connection"
                          className="rounded bg-overlay px-1.5 py-0.5 text-[10px] text-fg-secondary"
                        >
                          default
                        </span>
                      )}
                      {connection.source === JiraConnectionSource.env && (
                        <span
                          title="Seeded from RADD_JIRA_* on first startup. Editing it here is safe — it is never re-seeded."
                          className="rounded bg-overlay px-1.5 py-0.5 text-[10px] text-fg-faint"
                        >
                          from env
                        </span>
                      )}
                    </span>
                  </Td>
                  <Td className="max-w-[22rem] font-mono text-xs text-fg-secondary">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate">{connection.base_url}</span>
                      {!connection.verify_ssl && (
                        <span
                          title="TLS certificate verification is off for this connection"
                          className="shrink-0 whitespace-nowrap rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400"
                        >
                          no TLS check
                        </span>
                      )}
                    </span>
                  </Td>
                  <Td
                    className="whitespace-nowrap text-xs text-fg-secondary"
                    title={JIRA_AUTH_MODE_LABELS[connection.auth_mode] ?? connection.auth_mode}
                  >
                    {JIRA_AUTH_MODE_SHORT[connection.auth_mode] ?? connection.auth_mode}
                    {connection.username && (
                      <span className="text-fg-faint"> · {connection.username}</span>
                    )}
                  </Td>
                  <Td>
                    <ConnectionStatusCell
                      status={tested[connection.id]}
                      pending={test.isPending && test.variables === connection.id}
                      hasCredential={connection.has_credential}
                    />
                  </Td>
                  <Td>
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => test.mutate(connection.id)}
                        disabled={test.isPending}
                      >
                        Test
                      </Button>
                      {!connection.is_default && (
                        <Button
                          size="sm"
                          variant="ghost"
                          title="Use this connection when an import does not name one"
                          onClick={() => makeDefault.mutate(connection.id)}
                        >
                          <Star size={13} />
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => setEditing(connection)}>
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="danger-ghost"
                        aria-label={`Delete ${connection.name}`}
                        onClick={() => void onDelete(connection)}
                      >
                        <Trash2 size={13} />
                      </Button>
                    </div>
                  </Td>
                </tr>
              ))}
            </TBody>
          </Table>
        </div>
      )}

      {(adding || editing) && (
        <ConnectionModal
          connection={editing}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
          onSaved={invalidate}
        />
      )}
    </section>
  );
}

function ConnectionStatusCell({
  status,
  pending,
  hasCredential,
}: {
  status: JiraConnectionStatus | undefined;
  pending: boolean;
  hasCredential: boolean;
}) {
  if (pending) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-fg-secondary">
        <Loader2 size={13} className="animate-spin" /> Testing…
      </span>
    );
  }
  if (!hasCredential) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-amber-400">
        <CircleAlert size={13} /> No credential
      </span>
    );
  }
  if (!status) return <span className="whitespace-nowrap text-xs text-fg-faint">Not tested</span>;
  if (status.ok) {
    return (
      <span className="flex items-center gap-1.5 text-xs text-emerald-400">
        <CheckCircle2 size={13} /> {status.account || "connected"}
      </span>
    );
  }
  return (
    <span className="flex items-start gap-1.5 text-xs text-red-400" title={status.error}>
      <CircleAlert size={13} className="mt-0.5 shrink-0" />
      <span className="line-clamp-2">{status.error || "failed"}</span>
    </span>
  );
}

function ConnectionModal({
  connection,
  onClose,
  onSaved,
}: {
  connection: JiraConnection | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = connection !== null;
  const [form, setForm] = useState<JiraConnectionInput>(
    connection
      ? {
          name: connection.name,
          base_url: connection.base_url,
          auth_mode: connection.auth_mode,
          username: connection.username,
          credential: "", // never round-tripped; empty keeps the stored one
          verify_ssl: connection.verify_ssl,
          is_default: connection.is_default,
        }
      : EMPTY,
  );
  const set = <K extends keyof JiraConnectionInput>(key: K, value: JiraConnectionInput[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        base_url: form.base_url.trim(),
        auth_mode: form.auth_mode,
        username: form.auth_mode === JiraAuthMode.basic ? form.username.trim() : "",
        verify_ssl: form.verify_ssl,
        is_default: form.is_default,
      };
      // On edit, an untouched credential field must NOT blank the stored token.
      if (form.credential) body.credential = form.credential;
      return isEdit
        ? api.patch<JiraConnection>(`${ApiPath.jiraConnections}/${connection.id}`, body)
        : api.post<JiraConnection>(ApiPath.jiraConnections, {
            ...body,
            credential: form.credential,
          });
    },
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  const isBasic = form.auth_mode === JiraAuthMode.basic;
  const missingCredential = !isEdit && !form.credential;
  const canSave =
    form.name.trim() !== "" &&
    form.base_url.trim() !== "" &&
    !missingCredential &&
    (!isBasic || form.username.trim() !== "");

  return (
    <Modal title={isEdit ? `Edit ${connection.name}` : "Add a Jira connection"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField
          label="Name"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="Production Jira"
          hint="How this instance is labelled in Radd."
        />
        <TextField
          label="Base URL"
          value={form.base_url}
          onChange={(e) => set("base_url", e.target.value)}
          placeholder="https://jira.example.com"
          hint="The site root — not the /rest path."
        />
        <SelectField
          label="Authentication"
          value={form.auth_mode}
          onChange={(e) => set("auth_mode", e.target.value as JiraAuthModeValue)}
        >
          <option value={JiraAuthMode.pat}>{JIRA_AUTH_MODE_LABELS[JiraAuthMode.pat]}</option>
          <option value={JiraAuthMode.basic}>{JIRA_AUTH_MODE_LABELS[JiraAuthMode.basic]}</option>
        </SelectField>
        {isBasic && (
          <TextField
            label="Username"
            value={form.username}
            onChange={(e) => set("username", e.target.value)}
            autoComplete="off"
          />
        )}
        <TextField
          label={isBasic ? "Password" : "Personal access token"}
          type="password"
          value={form.credential}
          onChange={(e) => set("credential", e.target.value)}
          autoComplete="new-password"
          placeholder={isEdit ? "Leave blank to keep the stored credential" : ""}
          hint={
            isEdit
              ? "Stored credentials are never shown. Type a new one only to replace it."
              : "Read access is enough — the importer only reads from Jira."
          }
        />
        <label className="flex items-center gap-2 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={form.verify_ssl}
            onChange={(e) => set("verify_ssl", e.target.checked)}
          />
          Verify the TLS certificate
          <span className="text-fg-faint">(turn off only for an internal CA)</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={form.is_default}
            onChange={(e) => set("is_default", e.target.checked)}
          />
          Use as the default connection
        </label>

        {save.isError && <ErrorText error={save.error} />}

        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={!canSave || save.isPending}>
            {save.isPending ? "Saving…" : isEdit ? "Save" : "Add connection"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
