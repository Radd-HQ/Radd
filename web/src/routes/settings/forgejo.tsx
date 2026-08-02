import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, GitBranch, History, Plus, Server, Trash2, XCircle } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import {
  ApiPath,
  apiForgejoBackfillPath,
  apiForgejoConnectionPath,
  apiForgejoConnectionTestPath,
  apiForgejoRepoPath,
} from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { forgejoConnectionsQuery, forgejoReposQuery, projectsQuery } from "../../lib/queries";
import {
  Permission,
  type ForgejoBackfillReport,
  type ForgejoConnection,
  type ForgejoConnectionTest,
  type ForgejoRepo,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { QueryError } from "../../components/QueryError";
import { SelectField } from "../../components/SelectField";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Forgejo/Gitea hosts and repositories (spec 111).
 *
 * Credentials are write-only: the API returns `has_token`/`has_secret`, never the
 * values, and submitting an empty field keeps what is stored — so a form
 * round-trip cannot silently blank a secret.
 */
export function ForgejoSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.globalManage);
  const connections = useQuery(forgejoConnectionsQuery());
  const repos = useQuery(forgejoReposQuery());
  const projects = useQuery(projectsQuery());
  const queryClient = useQueryClient();

  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", base_url: "", webhook_secret: "", api_token: "" });
  const [tests, setTests] = useState<Record<string, ForgejoConnectionTest>>({});
  const [reports, setReports] = useState<Record<string, ForgejoBackfillReport>>({});
  const [newRepo, setNewRepo] = useState<Record<string, string>>({});

  const refresh = () =>
    invalidateEntities(queryClient, Entity.forgejoConnection, Entity.forgejoRepo);

  const createConnection = useMutation({
    mutationFn: () => api.post<ForgejoConnection>(ApiPath.forgejoConnections, form),
    onSuccess: () => {
      setAdding(false);
      setForm({ name: "", base_url: "", webhook_secret: "", api_token: "" });
      refresh();
    },
  });

  const removeConnection = useMutation({
    mutationFn: (id: string) => api.delete<void>(apiForgejoConnectionPath(id)),
    onSettled: refresh,
  });

  const test = useMutation({
    mutationFn: (id: string) => api.post<ForgejoConnectionTest>(apiForgejoConnectionTestPath(id), {}),
    onSuccess: (result, id) => setTests((prev) => ({ ...prev, [id]: result })),
  });

  const addRepo = useMutation({
    mutationFn: (vars: { connectionId: string; fullName: string }) =>
      api.post<ForgejoRepo>(ApiPath.forgejoRepos, {
        connection_id: vars.connectionId,
        full_name: vars.fullName,
      }),
    onSuccess: (_repo, vars) => {
      setNewRepo((prev) => ({ ...prev, [vars.connectionId]: "" }));
      refresh();
    },
  });

  const mapRepo = useMutation({
    mutationFn: (vars: { id: string; projectId: string | null }) =>
      api.patch<ForgejoRepo>(apiForgejoRepoPath(vars.id), { project_id: vars.projectId }),
    onSettled: refresh,
  });

  const removeRepo = useMutation({
    mutationFn: (id: string) => api.delete<void>(apiForgejoRepoPath(id)),
    onSettled: refresh,
  });

  const backfill = useMutation({
    mutationFn: (id: string) => api.post<ForgejoBackfillReport>(apiForgejoBackfillPath(id), {}),
    onSuccess: (report, id) => {
      setReports((prev) => ({ ...prev, [id]: report }));
      refresh();
    },
  });

  const list = connections.data ?? [];
  const reposFor = (connectionId: string) =>
    (repos.data ?? []).filter((repo) => repo.connection_id === connectionId);

  return (
    <SettingsPage
      title="Forgejo"
      description="Hosts whose pushes, branches and pull requests link themselves to issues by key. Map a repository to a project so its published releases create versions there."
    >
      {connections.isPending ? (
        <TableSkeleton rows={2} />
      ) : connections.isError ? (
        <QueryError label="Forgejo connections" error={connections.error} />
      ) : (
        <>
          {list.length === 0 ? (
            <EmptyState
              icon={Server}
              message="No hosts connected. Add one, then register a webhook on it pointing at /api/v1/integrations/forgejo."
            />
          ) : (
            <div className="space-y-4">
              {list.map((connection) => (
                <section key={connection.id} className="rounded-lg border border-subtle">
                  <header className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5">
                    <Server size={14} className="text-fg-muted" aria-hidden />
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-[13px] font-medium text-heading">
                        {connection.name}
                      </div>
                      <div className="truncate text-[11px] text-fg-muted">
                        {connection.base_url || "no base URL set"}
                      </div>
                    </div>
                    {!connection.has_secret && (
                      <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-warning-text">
                        no webhook secret
                      </span>
                    )}
                    {!connection.active && (
                      <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-muted">
                        inactive
                      </span>
                    )}
                    {tests[connection.id] && (
                      <span className="flex items-center gap-1 text-[11px] text-fg-muted">
                        {tests[connection.id].ok ? (
                          <>
                            <CheckCircle2 size={12} className="text-success-text" aria-hidden />
                            {tests[connection.id].version || "reachable"}
                          </>
                        ) : (
                          <>
                            <XCircle size={12} className="text-danger-text" aria-hidden />
                            {tests[connection.id].detail}
                          </>
                        )}
                      </span>
                    )}
                    {canManage && (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => test.mutate(connection.id)}
                          disabled={test.isPending}
                        >
                          Test
                        </Button>
                        <button
                          type="button"
                          aria-label={`Remove ${connection.name}`}
                          onClick={() => removeConnection.mutate(connection.id)}
                          className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-danger-text cursor-pointer"
                        >
                          <Trash2 size={13} aria-hidden />
                        </button>
                      </>
                    )}
                  </header>

                  <ul className="divide-y divide-subtle/60">
                    {reposFor(connection.id).map((repo) => (
                      <li key={repo.id} className="flex items-center gap-3 px-4 py-2">
                        <GitBranch size={13} className="text-fg-muted" aria-hidden />
                        <span className="flex-1 truncate font-mono text-[12px] text-fg">
                          {repo.full_name}
                        </span>
                        <SelectField
                          label=""
                          ariaLabel={`Project for ${repo.full_name}`}
                          value={repo.project_id ?? ""}
                          onChange={(event) =>
                            mapRepo.mutate({
                              id: repo.id,
                              projectId: event.target.value || null,
                            })
                          }
                          disabled={!canManage}
                        >
                          <option value="">No project</option>
                          {(projects.data ?? []).map((project) => (
                            <option key={project.id} value={project.id}>
                              {project.key}
                            </option>
                          ))}
                        </SelectField>
                        {canManage && (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => backfill.mutate(repo.id)}
                              disabled={backfill.isPending || !connection.has_token}
                              title={
                                connection.has_token
                                  ? "Link branches, PRs and commits that predate the webhook"
                                  : "Backfill reads the Forgejo API — this connection has no token"
                              }
                            >
                              <History size={13} aria-hidden /> Backfill
                            </Button>
                            <button
                              type="button"
                              aria-label={`Remove ${repo.full_name}`}
                              onClick={() => removeRepo.mutate(repo.id)}
                              className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-danger-text cursor-pointer"
                            >
                              <Trash2 size={13} aria-hidden />
                            </button>
                          </>
                        )}
                        {reports[repo.id] && (
                          <span className="text-[11px] text-fg-muted">
                            {reports[repo.id].linked} linked ({reports[repo.id].commits} commits,{" "}
                            {reports[repo.id].pull_requests} PRs)
                          </span>
                        )}
                      </li>
                    ))}
                    {canManage && (
                      <li className="flex items-center gap-2 px-4 py-2">
                        <input
                          value={newRepo[connection.id] ?? ""}
                          onChange={(event) =>
                            setNewRepo((prev) => ({
                              ...prev,
                              [connection.id]: event.target.value,
                            }))
                          }
                          placeholder="owner/repo"
                          aria-label={`Add a repository to ${connection.name}`}
                          className="flex-1 rounded-md border border-subtle bg-base px-2 py-1 font-mono text-[12px] outline-focus"
                        />
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={!newRepo[connection.id]?.trim()}
                          onClick={() =>
                            addRepo.mutate({
                              connectionId: connection.id,
                              fullName: (newRepo[connection.id] ?? "").trim(),
                            })
                          }
                        >
                          <Plus size={13} aria-hidden /> Add
                        </Button>
                      </li>
                    )}
                  </ul>
                </section>
              ))}
            </div>
          )}

          {canManage && (
            <div className="mt-4">
              {adding ? (
                <form
                  className="space-y-3 rounded-lg border border-subtle p-4"
                  onSubmit={(event: FormEvent) => {
                    event.preventDefault();
                    createConnection.mutate();
                  }}
                >
                  <TextField
                    label="Name"
                    value={form.name}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                    placeholder="Forgejo"
                  />
                  <TextField
                    label="Base URL"
                    value={form.base_url}
                    onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                    placeholder="https://git.example.com"
                  />
                  <TextField
                    label="Webhook secret"
                    hint="The shared secret the host signs payloads with."
                    value={form.webhook_secret}
                    onChange={(event) => setForm({ ...form, webhook_secret: event.target.value })}
                  />
                  <TextField
                    label="API token (optional)"
                    hint="Read-only. Needed for backfill and the connection test."
                    value={form.api_token}
                    onChange={(event) => setForm({ ...form, api_token: event.target.value })}
                  />
                  <div className="flex gap-2">
                    <Button type="submit" disabled={createConnection.isPending}>
                      Add host
                    </Button>
                    <Button type="button" variant="ghost" onClick={() => setAdding(false)}>
                      Cancel
                    </Button>
                  </div>
                  {createConnection.isError && (
                    <p className="text-[12px] text-danger-text">
                      {errorMessage(createConnection.error)}
                    </p>
                  )}
                </form>
              ) : (
                <Button variant="secondary" onClick={() => setAdding(true)}>
                  <Plus size={14} aria-hidden /> Connect a host
                </Button>
              )}
            </div>
          )}
        </>
      )}
    </SettingsPage>
  );
}
