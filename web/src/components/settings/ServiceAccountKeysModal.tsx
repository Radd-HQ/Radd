import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiServiceAccountKeyPath, apiServiceAccountKeysPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { permissionsCatalogQuery } from "../../lib/queries";
import { serviceAccountQuery, serviceKeyDirectoryQuery, SERVICE_ACCOUNT_PAGE_SIZE } from "../../lib/queries/integrations";
import { useDirectory } from "../../lib/useDirectory";
import type { ServiceAccount, ServiceAccountKeyCreated, TokenScopes } from "../../lib/types";
import { Button } from "../Button";
import { DirectoryPager } from "../DirectoryPager";
import { Modal } from "../Modal";
import { QueryError } from "../QueryError";
import { ProjectSelect } from "../projects/ProjectSelect";
import { SelectField } from "../SelectField";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";
import { TokenMultiSelect } from "../TokenMultiSelect";

/** Direct detail keeps an off-page account and its unfinished key form reachable. */
export function ServiceAccountKeysModal({ id, onClose }: { id: string; onClose: () => void }) {
  const account = useQuery(serviceAccountQuery(id));
  if (account.isPending || !account.data) return <Modal title="Service account keys" onClose={onClose}>
    {account.isPending ? <TableSkeleton rows={2} /> : <div><QueryError label="service account" error={account.error} /><Button variant="secondary" onClick={() => void account.refetch()}>Retry account</Button></div>}
  </Modal>;
  return <KeyEditor key={id} account={account.data} onClose={onClose} accountError={account.isError ? <div><QueryError label="service account" error={account.error} /><Button variant="secondary" onClick={() => void account.refetch()}>Retry account</Button></div> : undefined} />;
}

/** Keys for one account: list, revoke, and mint with a scope. */
function KeyEditor({ account, onClose, accountError }: { account: ServiceAccount; onClose: () => void; accountError?: ReactNode }) {
  const queryClient = useQueryClient();
  const keys = useDirectory(account.id, SERVICE_ACCOUNT_PAGE_SIZE, (q, page) => serviceKeyDirectoryQuery(account.id, q, page));
  useEffect(() => {
    if (keys.isSuccess && !keys.busy && keys.page > 0 && keys.page * keys.pageSize >= keys.total) keys.setPage(Math.max(0, Math.ceil(keys.total / keys.pageSize) - 1));
  }, [keys.isSuccess, keys.busy, keys.page, keys.pageSize, keys.total, keys.setPage]);
  const catalog = useQuery(permissionsCatalogQuery);

  const [scopeMode, setScopeMode] = useState("restricted");
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
      // Full authority is an explicit choice; an unfinished restricted form cannot mint an unrestricted key.
      if (scopeMode === "restricted" && atoms.length === 0) throw new Error("Choose at least one permission for a restricted key.");
      const scopes: TokenScopes | null = scopeMode === "restricted"
        ? projectId
          ? { projects: { [projectId]: atoms } }
          : { global: atoms }
        : null;
      return api.post<ServiceAccountKeyCreated>(apiServiceAccountKeysPath(account.id), {
        name: keyName.trim() || "key",
        scopes,
      });
    },
    onSuccess: async (created) => {
      setMinted(created);
      setKeyName("");
      setAtoms([]);
      await invalidateEntities(queryClient, Entity.serviceAccount);
    },
  });

  const revoke = useMutation({
    mutationFn: (keyId: string) =>
      api.delete<void>(apiServiceAccountKeyPath(account.id, keyId)),
    onSettled: () => invalidateEntities(queryClient, Entity.serviceAccount),
  });

  return (
    <Modal onClose={onClose} title={`${account.name} — API keys`} wide>
      <div className="space-y-5">
        {accountError}
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
          <TextField type="search" label="Find keys" value={keys.filter} onChange={event => keys.setFilter(event.target.value)} />
          <div aria-busy={keys.busy}>
          {keys.isPending ? (
            <TableSkeleton rows={2} />
          ) : keys.isError ? (
            <div><QueryError label="keys" error={keys.error} /><Button variant="secondary" onClick={() => void keys.refetch()}>Retry keys</Button></div>
          ) : keys.rows.length === 0 ? (
            <p className="mt-2 text-[12px] text-fg-muted">No matching keys.</p>
          ) : (
            <ul aria-label="Service account keys" className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-subtle">
              {keys.rows.map((key) => (
                <li
                  key={key.id}
                  className="flex flex-wrap items-center gap-2 border-b border-subtle/60 px-3 py-2 last:border-b-0"
                >
                  <code className="font-mono text-[12px] text-fg">{key.prefix_display}…</code>
                  <span className="flex-1 truncate text-[12px] text-fg-secondary">{key.name}</span>
                  <span className="max-w-full break-words text-[11px] text-fg-muted">
                    {key.restricted ? `scoped: ${key.global_count} global, ${key.project_count} projects` : "full account authority"}
                  </span>
                  {key.expires_at && <span className="text-[11px] text-fg-muted">{new Date(key.expires_at).getTime() < Date.now() ? "Expired" : `Expires ${new Date(key.expires_at).toLocaleDateString()}`}</span>}
                  <button
                    type="button"
                    aria-label={`Revoke ${key.name}`}
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(key.id)}
                    className="flex size-8 shrink-0 items-center justify-center rounded text-fg-muted hover:bg-elevated hover:text-danger-text cursor-pointer"
                  >
                    <Trash2 size={13} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
          </div>
          <DirectoryPager {...keys} onPage={keys.setPage} label="service account keys" />
        </section>

        <section className="border-t border-subtle pt-4">
          <h3 className="text-[12px] font-medium text-heading">Mint a key</h3>
          <p className="mt-1 text-[12px] text-fg-muted">
            Choose the permissions this key may use. Its effective access is also limited by the account's roles.
          </p>
          <div className="mt-3 space-y-3">
            <TextField
              label="Key name"
              value={keyName}
              onChange={(event) => setKeyName(event.target.value)}
              placeholder="mcp"
            />
            <SelectField label="Key authority" value={scopeMode} onChange={event => setScopeMode(event.target.value)}>
              <option value="restricted">Selected permissions</option>
              <option value="full">Full account authority</option>
            </SelectField>
            {scopeMode === "restricted" && <ProjectSelect label="Scope" value={projectId} onChange={setProjectId} emptyLabel="All accessible scopes" hint="Apply the selected permissions across this account’s accessible scopes, or only to one project." />}
            {scopeMode === "full" && <p className="text-xs text-fg-muted">This key can use all current and future permissions of this account.</p>}
            {scopeMode === "restricted" && <div>
              <span className="mb-1 block text-[12px] text-fg-secondary">Permissions</span>
              <TokenMultiSelect
                ariaLabel="Key permissions"
                value={atoms}
                onChange={setAtoms}
                options={atomOptions}
                placeholder="item.read, item.create…"
              />
            </div>}
            <Button onClick={() => mint.mutate()} disabled={mint.isPending || (scopeMode === "restricted" && !atoms.length)}>
              <KeyRound size={14} aria-hidden /> Mint key
            </Button>
            {mint.isError && (
              <p role="alert" className="text-[12px] text-status-danger-ink">{errorMessage(mint.error)}</p>
            )}
          </div>
        </section>
        {revoke.isError && <p role="alert" className="text-xs text-status-danger-ink">{errorMessage(revoke.error)}</p>}
      </div>
    </Modal>
  );
}

