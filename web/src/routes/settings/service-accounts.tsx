import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import {
  ApiPath,
  apiServiceAccountKeyPath,
  apiServiceAccountKeysPath,
} from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import {
  permissionsCatalogQuery,
  projectsQuery,
  serviceAccountKeysQuery,
  serviceAccountsQuery,
} from "../../lib/queries";
import {
  Permission,
  type ServiceAccount,
  type ServiceAccountKeyCreated,
  type TokenScopes,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Modal } from "../../components/Modal";
import { QueryError } from "../../components/QueryError";
import { SelectField } from "../../components/SelectField";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { TokenMultiSelect } from "../../components/TokenMultiSelect";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Service accounts and their scoped keys (spec 113).
 *
 * The scope editor speaks the same vocabulary as the roles matrix — raw
 * permission atoms — because that is what the key actually stores and what the
 * MCP catalog reads back. A key can never exceed its account: the resolver
 * intersects, so an over-broad scope is harmless rather than an escalation.
 */
export function ServiceAccountsSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.globalManage);
  const accounts = useQuery(serviceAccountsQuery());
  const queryClient = useQueryClient();

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [keyingFor, setKeyingFor] = useState<ServiceAccount | null>(null);

  const create = useMutation({
    mutationFn: (accountName: string) =>
      api.post<ServiceAccount>(ApiPath.serviceAccounts, { name: accountName }),
    onSuccess: () => {
      setCreating(false);
      setName("");
      invalidateEntities(queryClient, Entity.serviceAccount);
    },
  });

  const list = accounts.data ?? [];

  return (
    <SettingsPage
      title="Service accounts"
      description="Principals that authenticate with an API key and cannot sign in. Their authority comes from the roles you grant them; each key can be narrowed further to a subset of permissions."
    >
      {accounts.isPending ? (
        <TableSkeleton rows={3} />
      ) : accounts.isError ? (
        <QueryError label="service accounts" error={accounts.error} />
      ) : (
        <>
          {list.length === 0 ? (
            <EmptyState
              icon={Bot}
              message="No service accounts yet. Create one for an agent, a CI job, or an integration that should not act as a person."
            />
          ) : (
            <ul className="rounded-lg border border-subtle">
              {list.map((account) => (
                <li
                  key={account.id}
                  className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0"
                >
                  <Bot size={14} className="text-fg-muted" aria-hidden />
                  <div className="flex-1 min-w-0">
                    <div className="truncate text-[13px] font-medium text-heading">
                      {account.name}
                    </div>
                    <div className="truncate text-[11px] text-fg-muted">{account.email}</div>
                  </div>
                  <span className="text-[11px] text-fg-muted">
                    {account.token_count} {account.token_count === 1 ? "key" : "keys"}
                  </span>
                  {!account.active && (
                    <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-muted">
                      inactive
                    </span>
                  )}
                  {canManage && (
                    <Button size="sm" variant="ghost" onClick={() => setKeyingFor(account)}>
                      <KeyRound size={13} aria-hidden /> Keys
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {canManage && (
            <div className="mt-4">
              {creating ? (
                <form
                  className="flex items-end gap-2"
                  onSubmit={(event: FormEvent) => {
                    event.preventDefault();
                    if (name.trim()) create.mutate(name.trim());
                  }}
                >
                  <TextField
                    label="Name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Radd Agent"
                    autoFocus
                  />
                  <Button type="submit" disabled={create.isPending || !name.trim()}>
                    Create
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                    Cancel
                  </Button>
                </form>
              ) : (
                <Button variant="secondary" onClick={() => setCreating(true)}>
                  <Plus size={14} aria-hidden /> New service account
                </Button>
              )}
              {create.isError && (
                <p className="mt-2 text-[12px] text-danger-text">
                  {errorMessage(create.error)}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {keyingFor && (
        <KeysModal account={keyingFor} onClose={() => setKeyingFor(null)} />
      )}
    </SettingsPage>
  );
}

/** Keys for one account: list, revoke, and mint with a scope. */
function KeysModal({ account, onClose }: { account: ServiceAccount; onClose: () => void }) {
  const queryClient = useQueryClient();
  const keys = useQuery(serviceAccountKeysQuery(account.id));
  const catalog = useQuery(permissionsCatalogQuery);
  const projects = useQuery(projectsQuery());

  const [keyName, setKeyName] = useState("");
  const [projectId, setProjectId] = useState("");
  const [atoms, setAtoms] = useState<string[]>([]);
  const [minted, setMinted] = useState<ServiceAccountKeyCreated | null>(null);

  const atomOptions = useMemo(
    () =>
      (catalog.data ?? [])
        .map((entry) => ({ value: entry.key, label: entry.key, hint: entry.description, group: entry.scope }))
        .sort((a, b) => a.value.localeCompare(b.value)),
    [catalog.data],
  );

  const mint = useMutation({
    mutationFn: () => {
      // An empty atom set means UNSCOPED — the key carries the account's full
      // authority, which is the pre-spec-113 behaviour and still the default.
      const scopes: TokenScopes | null = atoms.length
        ? projectId
          ? { projects: { [projectId]: atoms } }
          : { global: atoms }
        : null;
      return api.post<ServiceAccountKeyCreated>(apiServiceAccountKeysPath(account.id), {
        name: keyName.trim() || "key",
        scopes,
      });
    },
    onSuccess: (created) => {
      setMinted(created);
      setKeyName("");
      setAtoms([]);
      invalidateEntities(queryClient, Entity.serviceAccount);
      queryClient.invalidateQueries({ queryKey: ["serviceAccounts", account.id, "keys"] });
    },
  });

  const revoke = useMutation({
    mutationFn: (keyId: string) =>
      api.delete<void>(apiServiceAccountKeyPath(account.id, keyId)),
    onSettled: () => {
      invalidateEntities(queryClient, Entity.serviceAccount);
      queryClient.invalidateQueries({ queryKey: ["serviceAccounts", account.id, "keys"] });
    },
  });

  return (
    <Modal onClose={onClose} title={`${account.name} — API keys`} wide>
      <div className="space-y-5">
        {minted && (
          <div className="rounded-lg border border-strong bg-elevated p-3">
            <p className="text-[12px] font-medium text-heading">
              Copy this key now — it is never shown again.
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 overflow-x-auto rounded bg-base px-2 py-1 font-mono text-[12px]">
                {minted.token}
              </code>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigator.clipboard?.writeText(minted.token)}
              >
                <Copy size={13} aria-hidden /> Copy
              </Button>
            </div>
          </div>
        )}

        <section>
          <h3 className="text-[12px] font-medium text-heading">Existing keys</h3>
          {keys.isPending ? (
            <TableSkeleton rows={2} />
          ) : keys.isError ? (
            <QueryError label="keys" error={keys.error} />
          ) : (keys.data ?? []).length === 0 ? (
            <p className="mt-2 text-[12px] text-fg-muted">No keys yet.</p>
          ) : (
            <ul className="mt-2 rounded-lg border border-subtle">
              {(keys.data ?? []).map((key) => (
                <li
                  key={key.id}
                  className="flex items-center gap-3 border-b border-subtle/60 px-3 py-2 last:border-b-0"
                >
                  <code className="font-mono text-[12px] text-fg">{key.prefix_display}…</code>
                  <span className="flex-1 truncate text-[12px] text-fg-secondary">{key.name}</span>
                  <span className="text-[11px] text-fg-muted">
                    {key.scopes ? scopeSummary(key.scopes) : "full account authority"}
                  </span>
                  <button
                    type="button"
                    aria-label={`Revoke ${key.name}`}
                    onClick={() => revoke.mutate(key.id)}
                    className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-danger-text cursor-pointer"
                  >
                    <Trash2 size={13} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="border-t border-subtle pt-4">
          <h3 className="text-[12px] font-medium text-heading">Mint a key</h3>
          <p className="mt-1 text-[12px] text-fg-muted">
            Leave the permissions empty for a key with the account's full authority. Anything you
            list here NARROWS the key — it can never grant more than the account itself holds.
          </p>
          <div className="mt-3 space-y-3">
            <TextField
              label="Key name"
              value={keyName}
              onChange={(event) => setKeyName(event.target.value)}
              placeholder="mcp"
            />
            <SelectField
              label="Scope"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
            >
              <option value="">Global (instance-wide atoms)</option>
              {(projects.data ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.key} · {project.name}
                </option>
              ))}
            </SelectField>
            <div>
              <span className="mb-1 block text-[12px] text-fg-secondary">Permissions</span>
              <TokenMultiSelect
                value={atoms}
                onChange={setAtoms}
                options={atomOptions}
                placeholder="item.read, item.create…"
              />
            </div>
            <Button onClick={() => mint.mutate()} disabled={mint.isPending}>
              <KeyRound size={14} aria-hidden /> Mint key
            </Button>
            {mint.isError && (
              <p className="text-[12px] text-danger-text">{errorMessage(mint.error)}</p>
            )}
          </div>
        </section>
      </div>
    </Modal>
  );
}

function scopeSummary(scopes: TokenScopes): string {
  const globalCount = scopes.global?.length ?? 0;
  const projectCount = Object.keys(scopes.projects ?? {}).length;
  const parts: string[] = [];
  if (globalCount) parts.push(`${globalCount} global`);
  if (projectCount) parts.push(`${projectCount} project${projectCount === 1 ? "" : "s"}`);
  return parts.length ? `scoped: ${parts.join(", ")}` : "scoped: nothing";
}
