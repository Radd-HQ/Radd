import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Plug, Star, Trash2 } from "lucide-react";
import { api, Button, EmptyState, QueryError, Table, TableSkeleton, TBody, Td, Th, THead, useConfirm } from "@radd/plugin-sdk";
import { connectionsQuery, JiraPath, jiraKeys } from "./api";
import { Panel, StatusText } from "./chrome";
import { ConnectionModal } from "./ConnectionModal";
import {
  JIRA_AUTH_MODE_LABELS,
  JIRA_AUTH_MODE_SHORT,
  JiraConnectionSource,
  type JiraConnection,
  type JiraConnectionStatus,
} from "./types";

/** Jira connections — admin-managed rows. An env-seeded row is ordinary and editable; its origin is only shown. */
export function ConnectionsPanel() {
  const queryClient = useQueryClient();
  const connections = useQuery(connectionsQuery());
  const [editing, setEditing] = useState<JiraConnection | null>(null);
  const [adding, setAdding] = useState(false);
  const [tested, setTested] = useState<Record<string, JiraConnectionStatus>>({});
  const [confirmNode, confirm] = useConfirm();

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: jiraKeys.connections });
    void queryClient.invalidateQueries({ queryKey: jiraKeys.status });
    void queryClient.invalidateQueries({ queryKey: jiraKeys.projectsAll });
  };

  const test = useMutation({
    mutationFn: (id: string) =>
      api.post<JiraConnectionStatus>(`${JiraPath.connections}/${id}/test`, {}),
    onSuccess: (status, id) => setTested((prev) => ({ ...prev, [id]: status })),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${JiraPath.connections}/${id}`),
    onSuccess: invalidate,
  });

  const makeDefault = useMutation({
    mutationFn: (id: string) =>
      api.patch<JiraConnection>(`${JiraPath.connections}/${id}`, { is_default: true }),
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
    <Panel
      section="connections"
      title="Connections"
      description="The Jira instances Radd can import from. Changes take effect immediately — no restart."
      action={
        <Button size="sm" onClick={() => setAdding(true)}>
          New connection
        </Button>
      }
    >
      {confirmNode}

      {connections.isPending ? (
        <TableSkeleton rows={2} />
      ) : connections.isError ? (
        <QueryError label="Jira connections" error={connections.error} />
      ) : connections.data.length === 0 ? (
        <EmptyState icon={Plug} message="No Jira connections yet — add one to start an import." />
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
                          className="shrink-0 whitespace-nowrap rounded bg-status-warning/10 px-1.5 py-0.5 text-[10px] text-status-warning-ink"
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
                          aria-label={`Make ${connection.name} the default`}
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
    </Panel>
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
  if (pending) return <StatusText tone="running" wrap>Testing…</StatusText>;
  if (!hasCredential) return <StatusText tone="warning" icon={CircleAlert} wrap>No credential</StatusText>;
  if (!status) return <span className="whitespace-nowrap text-xs text-fg-faint">Not tested</span>;
  if (status.ok) return <StatusText tone="success" wrap>{status.account || "connected"}</StatusText>;
  return (
    <span className="flex items-start gap-1.5 text-xs text-status-danger-ink" title={status.error}>
      <CircleAlert size={13} className="mt-0.5 shrink-0" />
      <span className="line-clamp-2">{status.error || "failed"}</span>
    </span>
  );
}
