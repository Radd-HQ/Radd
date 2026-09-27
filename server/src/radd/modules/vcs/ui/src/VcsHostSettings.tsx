import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Server, Trash2, XCircle } from "lucide-react";
import { api, errorMessage, invalidateEntities, useConfirm, useContributedQuery, useListFilter,
  Button, EmptyState, IconButton, ListSearchInput, QueryError, TableSkeleton, TextField } from "@radd/plugin-sdk";
import type { WorkCategoryChoice } from "@radd-plugin-ui/timelogging/lookup-contract";
import type { HostConnection, HostConnectionTest, HostRepo, VcsConnector } from "./types";
import { hostEntities, hostPaths, useHostQuery } from "./queries";
import { RepoRow, type Categories } from "./RepoRow";
import { VcsIdentityMap } from "./VcsIdentityMap";

/** One connector's tab on Settings → Version control: its hosts, their
 * repositories and identity maps (spec 111, RADD-1258/1366), in the wording the
 * connector declares (RADD-1435). The page is instance-admin only; the tab
 * renders nothing a reader could not change. */
export function VcsHostSettings({ config }: { config: VcsConnector }) {
  const connections = useHostQuery<HostConnection[]>(config.provider, "connections");
  const repos = useHostQuery<HostRepo[]>(config.provider, "repos");
  const categoryQuery = useContributedQuery<WorkCategoryChoice[]>("timelogging.categories");
  const categories: Categories = {
    rows: categoryQuery.isSuccess ? categoryQuery.data : undefined,
    unavailable: !categoryQuery.available || categoryQuery.isError,
  };
  const [editing, setEditing] = useState<HostConnection | "new" | null>(null);
  const list = connections.data ?? [];

  return (
    <div>
      <p className="mb-2 text-[13px] text-fg-muted">{config.description}</p>
      <p className="mb-3 text-xs text-fg-muted">
        Only registered, enabled repositories accept webhooks. Pausing a host pauses all its repositories; removing a
        repository stops ingestion and keeps historical links. Use a different webhook secret for each host. The default
        project is where versions are published; turn off “Link across projects” to also restrict issue links and
        mirrored time to it. Beyond linking, a repository changes issues only through its own switches — every
        merge, push, CI run and release is also an automation trigger, for anything they don't cover.
      </p>
      {categoryQuery.isError && <QueryError label="work categories" error={categoryQuery.error} />}
      {repos.isError && <QueryError label="repositories" error={repos.error} />}
      {connections.isPending ? (
        <TableSkeleton rows={2} />
      ) : connections.isError ? (
        <QueryError label={`${config.title} connections`} error={connections.error} />
      ) : (
        <>
          {list.length === 0 ? (
            <EmptyState icon={Server}
              message={`No hosts connected. Add one, then register a webhook on it pointing at ${config.webhook_path}.`} />
          ) : (
            <div className="space-y-4">
              {list.map((connection) => (
                <ConnectionCard key={connection.id} config={config} connection={connection} categories={categories}
                  repos={(repos.data ?? []).filter((repo) => repo.connection_id === connection.id)}
                  onEdit={() => setEditing(connection)} />
              ))}
            </div>
          )}
          <div className="mt-4">
            {editing ? (
              <HostForm config={config} connection={editing === "new" ? null : editing} onDone={() => setEditing(null)} />
            ) : (
              <Button variant="secondary" onClick={() => setEditing("new")}>
                <Plus size={14} aria-hidden /> Connect a host
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ConnectionCard({ config, connection, repos, categories, onEdit }: {
  config: VcsConnector;
  connection: HostConnection;
  repos: HostRepo[];
  categories: Categories;
  onEdit: () => void;
}) {
  const queryClient = useQueryClient();
  const paths = hostPaths(config.provider);
  const refresh = () => invalidateEntities(queryClient, ...hostEntities(config.provider));
  const [confirmDialog, confirm] = useConfirm();
  const [newRepo, setNewRepo] = useState("");
  const toggle = useMutation({
    mutationFn: () => api.patch(paths.connection(connection.id), { active: !connection.active }),
    onSettled: refresh,
  });
  const remove = useMutation({ mutationFn: () => api.delete<void>(paths.connection(connection.id)), onSettled: refresh });
  const test = useMutation({ mutationFn: () => api.post<HostConnectionTest>(paths.connectionTest(connection.id), {}) });
  const addRepo = useMutation({
    mutationFn: (fullName: string) => api.post<HostRepo>(paths.repos, { connection_id: connection.id, full_name: fullName }),
    onSuccess: () => {
      setNewRepo("");
      void refresh();
    },
  });
  const search = useListFilter(repos, (repo) => [repo.full_name]);
  const askRemove = async () => {
    const ok = await confirm({
      title: `Remove ${connection.name}?`,
      message: `Its ${connection.repo_count} registered repositories stop accepting webhooks. Links already made to issues stay.`,
      confirmLabel: "Remove host",
      danger: true,
    });
    if (ok) remove.mutate();
  };
  const error = [toggle, remove, test, addRepo].find((mutation) => mutation.isError)?.error;
  const result = test.data;

  return (
    <section className="rounded-lg border border-subtle" data-connection={connection.name}>
      {confirmDialog}
      <header className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5">
        <Server size={14} className="text-fg-muted" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-heading">{connection.name}</div>
          <div className="truncate text-[11px] text-fg-muted">{connection.base_url || "no base URL set"}</div>
        </div>
        {!connection.has_secret && <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-status-warning-ink">no webhook secret</span>}
        {!connection.active && <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-muted">inactive</span>}
        {result && (
          <span className="flex items-center gap-1 text-[11px] text-fg-muted">
            {result.ok ? <CheckCircle2 size={12} className="text-status-success-ink" aria-hidden /> : <XCircle size={12} className="text-status-danger-ink" aria-hidden />}
            {result.ok ? result.version || "reachable" : result.detail}
          </span>
        )}
        <Button size="sm" variant="ghost" onClick={onEdit}>Edit</Button>
        <Button size="sm" variant="ghost" disabled={toggle.isPending} onClick={() => toggle.mutate()}>
          {connection.active ? "Pause" : "Resume"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => test.mutate()} disabled={test.isPending}>Test</Button>
        <IconButton danger aria-label={`Remove ${connection.name}`} onClick={() => void askRemove()} disabled={remove.isPending}>
          <Trash2 size={13} aria-hidden />
        </IconButton>
      </header>
      {error && <p role="alert" className="px-4 pt-2 text-xs text-status-danger-ink">{errorMessage(error)}</p>}
      {repos.length > 8 && (
        <div className="border-b border-subtle/60 px-4 py-2">
          <ListSearchInput value={search.filter} onChange={search.setFilter} placeholder="Filter repositories…"
            ariaLabel={`Filter repositories on ${connection.name}`} total={repos.length} matched={search.filtered.length} noun="repositories" />
        </div>
      )}
      <ul className="divide-y divide-subtle/60">
        {search.filtering && search.filtered.length === 0 && (
          <li className="px-4 py-3 text-xs text-fg-muted">No repositories match “{search.filter.trim()}”.</li>
        )}
        {search.filtered.map((repo) => (
          <RepoRow key={repo.id} provider={config.provider} changeNoun={config.change_noun} connection={connection} repo={repo}
            categories={categories} />
        ))}
        <li>
          <form className="flex items-center gap-2 px-4 py-2" onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (newRepo.trim()) addRepo.mutate(newRepo.trim());
          }}>
            <div className="flex-1">
              <TextField aria-label={`Add a repository to ${connection.name}`} placeholder="owner/repo" value={newRepo}
                onChange={(event) => setNewRepo(event.target.value)} />
            </div>
            <Button type="submit" size="sm" variant="secondary" disabled={!newRepo.trim() || addRepo.isPending}>
              <Plus size={13} aria-hidden /> Add
            </Button>
          </form>
        </li>
      </ul>
      <div className="border-t border-subtle/60 p-3">
        <VcsIdentityMap provider={config.provider} connectionId={connection.id} />
      </div>
    </section>
  );
}

/** Add a host, or edit one — a blank secret or token keeps the stored value. */
function HostForm({ config, connection, onDone }: {
  config: VcsConnector;
  connection: HostConnection | null;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const paths = hostPaths(config.provider);
  const [form, setForm] = useState({
    name: connection?.name ?? "",
    base_url: connection?.base_url ?? config.default_base_url,
    webhook_secret: "",
    api_token: "",
  });
  const save = useMutation({
    mutationFn: () => connection
      ? api.patch<HostConnection>(paths.connection(connection.id), {
          name: form.name, base_url: form.base_url,
          ...(form.api_token ? { api_token: form.api_token } : {}),
          ...(form.webhook_secret ? { webhook_secret: form.webhook_secret } : {}),
        })
      : api.post<HostConnection>(paths.connections, form),
    onSuccess: () => {
      void invalidateEntities(queryClient, ...hostEntities(config.provider));
      onDone();
    },
  });
  return (
    <form className="space-y-3 rounded-lg border border-subtle p-4" onSubmit={(event: FormEvent) => {
      event.preventDefault();
      save.mutate();
    }}>
      <TextField label="Name" value={form.name} placeholder={config.name_placeholder}
        onChange={(event) => setForm({ ...form, name: event.target.value })} />
      <TextField label={config.default_base_url ? "Base URL (leave for the public host)" : "Base URL"} value={form.base_url}
        placeholder={config.base_url_placeholder} onChange={(event) => setForm({ ...form, base_url: event.target.value })} />
      <TextField label="Webhook secret" type="password" value={form.webhook_secret}
        hint={connection ? "Leave blank to keep the stored secret; enter a value to rotate it." : config.secret_hint}
        onChange={(event) => setForm({ ...form, webhook_secret: event.target.value })} />
      <TextField label="API token (optional)" type="password" value={form.api_token}
        hint={connection ? "Leave blank to keep the stored token; enter a value to rotate it." : config.token_hint}
        onChange={(event) => setForm({ ...form, api_token: event.target.value })} />
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>{connection ? "Save host" : "New host"}</Button>
        <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
      {save.isError && <p role="alert" className="text-[12px] text-status-danger-ink">{errorMessage(save.error)}</p>}
    </form>
  );
}
