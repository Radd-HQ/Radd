import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, KeyRound, Plus } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { serviceAccountDirectoryQuery, SERVICE_ACCOUNT_PAGE_SIZE } from "../../lib/queries/integrations";
import { useDirectory } from "../../lib/useDirectory";
import { Permission, type ServiceAccount } from "../../lib/types";
import { Button } from "../../components/Button";
import { DirectoryPager } from "../../components/DirectoryPager";
import { QueryError } from "../../components/QueryError";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ServiceAccountKeysModal } from "../../components/settings/ServiceAccountKeysModal";

export function ServiceAccountsSettingsPage() {
  const perms = usePermissions();
  const canCreate = perms.global(Permission.globalManage) && perms.global(Permission.serviceAccountCreate);
  const accounts = useDirectory("service-accounts", SERVICE_ACCOUNT_PAGE_SIZE, serviceAccountDirectoryQuery);
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [keyingFor, setKeyingFor] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (accountName: string) => api.post<ServiceAccount>(ApiPath.serviceAccounts, { name: accountName }),
    onSuccess: async account => {
      setCreating(false); setName(""); setKeyingFor(account.id);
      await invalidateEntities(queryClient, Entity.serviceAccount);
    },
  });
  return <SettingsPage title="Service accounts" description="Principals that authenticate with an API key and cannot sign in. Their authority comes from the roles you grant them; each key can be narrowed further to a subset of permissions.">
    <TextField type="search" label="Find service accounts" value={accounts.filter} onChange={event => accounts.setFilter(event.target.value)} placeholder="Search names or email addresses…" />
    <div aria-busy={accounts.busy} className="mt-3">
      {accounts.isPending ? <TableSkeleton rows={3} /> : accounts.isError ? <div><QueryError label="service accounts" error={accounts.error} /><Button variant="secondary" onClick={() => void accounts.refetch()}>Retry accounts</Button></div>
        : accounts.rows.length === 0 ? <p className="text-sm text-fg-muted">{accounts.q ? "No matching service accounts." : "No service accounts yet. Create one for an agent, a CI job, or an integration."}</p>
        : <ul aria-label="Service accounts" className="rounded-lg border border-subtle">{accounts.rows.map(account => <li key={account.id} className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
          <Bot size={14} className="shrink-0 text-fg-muted" aria-hidden />
          <div className="min-w-0 flex-1"><div className="truncate text-[13px] font-medium text-heading">{account.name}</div><div className="truncate text-[11px] text-fg-muted">{account.email}</div>
            {!account.active && <span className="text-[11px] text-fg-muted">Inactive · </span>}<span className="text-[11px] text-fg-muted">{account.token_count} {account.token_count === 1 ? "key" : "keys"}</span></div>
          <Button size="sm" variant="ghost" onClick={() => setKeyingFor(account.id)}><KeyRound size={13} aria-hidden /> Keys</Button>
        </li>)}</ul>}
    </div>
    <DirectoryPager {...accounts} onPage={accounts.setPage} label="service accounts" />
    {canCreate && <div className="mt-4">
      {creating ? <form className="flex flex-wrap items-end gap-2" onSubmit={(event: FormEvent) => { event.preventDefault(); if (name.trim()) create.mutate(name.trim()); }}>
        <TextField label="Name" value={name} onChange={event => setName(event.target.value)} placeholder="Radd Agent" autoFocus />
        <Button type="submit" disabled={create.isPending || !name.trim()}>Create</Button><Button type="button" variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
      </form> : <Button variant="secondary" onClick={() => setCreating(true)}><Plus size={14} aria-hidden />New service account</Button>}
      {create.isError && <p role="alert" className="mt-2 text-xs text-status-danger-ink">{errorMessage(create.error)}</p>}
    </div>}
    {keyingFor && <ServiceAccountKeysModal id={keyingFor} onClose={() => setKeyingFor(null)} />}
  </SettingsPage>;
}
