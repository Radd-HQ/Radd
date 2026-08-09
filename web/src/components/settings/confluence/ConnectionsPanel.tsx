import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Trash2, XCircle } from "lucide-react";
import { Button, ButtonVariant } from "../../Button";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { useConfirm } from "../../ConfirmDialog";
import { api } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import {
  confluenceConnectionsQuery,
  confluenceStatusQuery,
  queryKeys,
} from "../../../lib/queries";
import { ConfluenceAuthMode, type ConfluenceConnection } from "../../../lib/types";

/**
 * Which Confluence to talk to (spec 117) — a database row an admin manages, not
 * an environment variable needing a redeploy. Credentials are never returned, so
 * an empty credential field on save means "keep the stored one".
 */
export function ConnectionsPanel() {
  const client = useQueryClient();
  const [confirmNode, confirm] = useConfirm();
  const [editing, setEditing] = useState<ConfluenceConnection | null>(null);
  const [creating, setCreating] = useState(false);

  const connections = useQuery(confluenceConnectionsQuery());
  const status = useQuery(confluenceStatusQuery());

  const invalidate = () => {
    void client.invalidateQueries({ queryKey: queryKeys.confluenceConnections });
    void client.invalidateQueries({ queryKey: queryKeys.confluenceStatus });
  };

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${ApiPath.confluenceConnections}/${id}`),
    onSuccess: invalidate,
  });

  const test = useMutation({
    mutationFn: (id: string) =>
      api.post(`${ApiPath.confluenceConnections}/${id}/test`, {}),
    onSuccess: invalidate,
  });

  const rows = connections.data ?? [];

  return (
    <section className="rounded-xl border border-subtle bg-surface p-4">
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-heading">Connections</h2>
          <p className="text-[13px] text-fg-muted">
            Confluence Server or Data Center. A personal access token is the usual
            choice; basic auth works where tokens are disabled.
          </p>
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus className="size-4" aria-hidden /> Add
        </Button>
      </header>

      {status.data && !status.data.configured && (
        <p className="mb-3 rounded-lg border border-subtle bg-elevated px-3 py-2 text-[13px] text-fg-secondary">
          No connection yet — add one to begin.
        </p>
      )}
      {status.data?.configured && (
        <p className="mb-3 flex items-center gap-1.5 text-[13px]">
          {status.data.ok ? (
            <>
              <CheckCircle2 className="size-4 text-accent-text" aria-hidden />
              <span className="text-fg-secondary">
                Connected{status.data.user ? ` as ${status.data.user}` : ""}.
              </span>
            </>
          ) : (
            <>
              <XCircle className="size-4 text-fg-muted" aria-hidden />
              <span className="text-fg-secondary">{status.data.detail}</span>
            </>
          )}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="divide-y divide-subtle">
          {rows.map((connection) => (
            <li key={connection.id} className="flex items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-heading">
                  {connection.name}
                  {connection.is_default && (
                    <span className="ml-2 rounded bg-elevated px-1.5 py-0.5 text-[11px] text-fg-muted">
                      default
                    </span>
                  )}
                </p>
                <p className="truncate text-[12px] text-fg-muted">
                  {connection.base_url} · {connection.auth_mode}
                  {connection.has_credential ? "" : " · no credential"}
                </p>
              </div>
              <Button
                variant={ButtonVariant.ghost}
                size="sm"
                onClick={() => test.mutate(connection.id)}
              >
                Test
              </Button>
              <Button
                variant={ButtonVariant.ghost}
                size="sm"
                onClick={() => setEditing(connection)}
              >
                Edit
              </Button>
              <Button
                variant={ButtonVariant.ghost}
                size="sm"
                aria-label={`Delete ${connection.name}`}
                onClick={async () => {
                  if (
                    await confirm({
                      title: `Delete ${connection.name}?`,
                      message: "Snapshots already downloaded from it are kept.",
                      confirmLabel: "Delete",
                      danger: true,
                    })
                  ) {
                    remove.mutate(connection.id);
                  }
                }}
              >
                <Trash2 className="size-4" aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}

      {(creating || editing) && (
        <ConnectionModal
          connection={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={invalidate}
        />
      )}
      {confirmNode}
    </section>
  );
}

function ConnectionModal({
  connection,
  onClose,
  onSaved,
}: {
  connection: ConfluenceConnection | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(connection?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(connection?.base_url ?? "");
  const [authMode, setAuthMode] = useState<string>(
    connection?.auth_mode ?? ConfluenceAuthMode.pat,
  );
  const [username, setUsername] = useState(connection?.username ?? "");
  const [credential, setCredential] = useState("");
  const [verifySsl, setVerifySsl] = useState(connection?.verify_ssl ?? true);
  const [isDefault, setIsDefault] = useState(connection?.is_default ?? false);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        base_url: baseUrl,
        auth_mode: authMode,
        username,
        // Empty means "keep the stored one" — the read shape is redacted, so a
        // form that saves an untouched connection must not blank its token.
        credential: credential || undefined,
        verify_ssl: verifySsl,
        is_default: isDefault,
      };
      return connection
        ? api.patch(`${ApiPath.confluenceConnections}/${connection.id}`, body)
        : api.post(ApiPath.confluenceConnections, body);
    },
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  return (
    <Modal title={connection ? "Edit connection" : "Add a Confluence"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="confluence.example.com"
        />
        <TextField
          label="Base URL"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://confluence.example.com"
          hint="The site root — not the /rest/api path."
        />
        <SelectField
          label="Authentication"
          value={authMode}
          onChange={(e) => setAuthMode(e.target.value)}
        >
          <option value={ConfluenceAuthMode.pat}>Personal access token</option>
          <option value={ConfluenceAuthMode.basic}>Username and password</option>
        </SelectField>
        {authMode === ConfluenceAuthMode.basic && (
          <TextField
            label="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        )}
        <TextField
          label={authMode === ConfluenceAuthMode.pat ? "Token" : "Password"}
          type="password"
          value={credential}
          onChange={(e) => setCredential(e.target.value)}
          hint={connection ? "Leave empty to keep the stored credential." : undefined}
        />
        <label className="flex items-center gap-2 text-[13px] text-fg-secondary">
          <input
            type="checkbox"
            checked={verifySsl}
            onChange={(e) => setVerifySsl(e.target.checked)}
          />
          Verify the TLS certificate
        </label>
        <label className="flex items-center gap-2 text-[13px] text-fg-secondary">
          <input
            type="checkbox"
            checked={isDefault}
            onChange={(e) => setIsDefault(e.target.checked)}
          />
          Use as the default connection
        </label>
        <div className="mt-1 flex justify-end gap-2">
          <Button variant={ButtonVariant.ghost} onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={!name || !baseUrl}>
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}
