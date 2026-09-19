import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { CheckCircle2, GitBranch, History, Plus, Server, Trash2, XCircle } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { invalidateEntities, type Entity } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import { projectsQuery, workCategoriesQuery } from "../../lib/queries";
import {
  Permission,
  type ForgejoBackfillReport,
  type ForgejoConnection,
  type ForgejoConnectionTest,
  type ForgejoRepo,
  type VcsProviderValue,
} from "../../lib/types";
import { Button } from "../Button";
import { EmptyState } from "../EmptyState";
import { ListSearchInput } from "../ListSearchInput";
import { QueryError } from "../QueryError";
import { SelectField } from "../SelectField";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";
import { VcsIdentityMap } from "./VcsIdentityMap";

/**
 * One body for every version-control host connector (Forgejo since spec 111,
 * GitHub since RADD-1129, GitLab since RADD-1253), rendered as a tab of
 * Settings → Version control (RADD-1262). The APIs share a wire shape — hosts
 * and repositories as rows, credentials write-only (`has_token`/`has_secret`),
 * an empty field on update keeping the stored value — so the body is
 * parameterised by paths and wording, not duplicated.
 */
type EntityName = (typeof Entity)[keyof typeof Entity];

export type VcsHostConfig = {
  /** The VcsProvider this host kind writes links as — keys the identity map (RADD-1258). */
  provider: VcsProviderValue;
  /** Entity types the page edits — its "Change history" footer link (spec 123). */
  historyEntities: string[];
  title: string;
  description: string;
  /** Where to register the webhook on the host, shown in the empty state. */
  webhookPath: string;
  namePlaceholder: string;
  baseUrlPlaceholder: string;
  /** When set, the base URL field is optional and defaults to this host. */
  defaultBaseUrl?: string;
  tokenHint: string;
  secretHint: string;
  /** Hooks, not option factories: the two connectors' query keys are distinct
   * literal types and TanStack's option objects are invariant in them. */
  useConnections: () => UseQueryResult<ForgejoConnection[], Error>;
  useRepos: () => UseQueryResult<ForgejoRepo[], Error>;
  entities: [connection: EntityName, repo: EntityName];
  paths: {
    connections: string;
    repos: string;
    connection: (id: string) => string;
    connectionTest: (id: string) => string;
    repo: (id: string) => string;
    backfill: (id: string) => string;
  };
};

export function VcsHostSettings({ config }: { config: VcsHostConfig }) {
  const perms = usePermissions();
  const canManage = perms.global(Permission.globalManage);
  const connections = config.useConnections();
  const repos = config.useRepos();
  const projects = useQuery(projectsQuery());
  const categories = useQuery(workCategoriesQuery());
  const queryClient = useQueryClient();

  const [adding, setAdding] = useState(false);
  const blank = { name: "", base_url: config.defaultBaseUrl ?? "", webhook_secret: "", api_token: "" };
  const [form, setForm] = useState(blank);
  const [tests, setTests] = useState<Record<string, ForgejoConnectionTest>>({});
  const [reports, setReports] = useState<Record<string, ForgejoBackfillReport>>({});
  const [newRepo, setNewRepo] = useState<Record<string, string>>({});

  const refresh = () => invalidateEntities(queryClient, config.entities[0], config.entities[1]);

  const createConnection = useMutation({
    mutationFn: () => api.post<ForgejoConnection>(config.paths.connections, form),
    onSuccess: () => {
      setAdding(false);
      setForm(blank);
      refresh();
    },
  });
  const removeConnection = useMutation({
    mutationFn: (id: string) => api.delete<void>(config.paths.connection(id)),
    onSettled: refresh,
  });
  const test = useMutation({
    mutationFn: (id: string) => api.post<ForgejoConnectionTest>(config.paths.connectionTest(id), {}),
    onSuccess: (result, id) => setTests((prev) => ({ ...prev, [id]: result })),
  });
  const addRepo = useMutation({
    mutationFn: (vars: { connectionId: string; fullName: string }) =>
      api.post<ForgejoRepo>(config.paths.repos, { connection_id: vars.connectionId, full_name: vars.fullName }),
    onSuccess: (_repo, vars) => {
      setNewRepo((prev) => ({ ...prev, [vars.connectionId]: "" }));
      refresh();
    },
  });
  const mapRepo = useMutation({
    mutationFn: (vars: { id: string; projectId: string | null }) =>
      api.patch<ForgejoRepo>(config.paths.repo(vars.id), { project_id: vars.projectId }),
    onSettled: refresh,
  });
  // RADD-1258: the work category a worklog mirrored from this repo's MRs/PRs carries.
  const setCategory = useMutation({
    mutationFn: (vars: { id: string; categoryId: string | null }) =>
      api.patch<ForgejoRepo>(config.paths.repo(vars.id), { time_category_id: vars.categoryId }),
    onSettled: refresh,
  });
  const removeRepo = useMutation({
    mutationFn: (id: string) => api.delete<void>(config.paths.repo(id)),
    onSettled: refresh,
  });
  const backfill = useMutation({
    mutationFn: (id: string) => api.post<ForgejoBackfillReport>(config.paths.backfill(id), {}),
    onSuccess: (report, id) => {
      setReports((prev) => ({ ...prev, [id]: report }));
      refresh();
    },
  });

  const list = connections.data ?? [];
  const reposFor = (connectionId: string) =>
    (repos.data ?? []).filter((repo) => repo.connection_id === connectionId);

  return (
    <div>
      <p className="mb-4 text-[13px] text-fg-muted">{config.description}</p>
      {connections.isPending ? (
        <TableSkeleton rows={2} />
      ) : connections.isError ? (
        <QueryError label={`${config.title} connections`} error={connections.error} />
      ) : (
        <>
          {list.length === 0 ? (
            <EmptyState
              icon={Server}
              message={`No hosts connected. Add one, then register a webhook on it pointing at ${config.webhookPath}.`}
            />
          ) : (
            <div className="space-y-4">
              {list.map((connection) => (
                <section key={connection.id} className="rounded-lg border border-subtle">
                  <header className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5">
                    <Server size={14} className="text-fg-muted" aria-hidden />
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-[13px] font-medium text-heading">{connection.name}</div>
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
                      <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-muted">inactive</span>
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
                        <Button size="sm" variant="ghost" onClick={() => test.mutate(connection.id)} disabled={test.isPending}>
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

                  <RepoSearch repos={reposFor(connection.id)}>
                    {(search) => (
                      <>
                        {reposFor(connection.id).length > 8 && (
                          <div className="border-b border-subtle/60 px-4 py-2">
                            <ListSearchInput
                              value={search.filter}
                              onChange={search.setFilter}
                              placeholder="Filter repositories…"
                              ariaLabel={`Filter repositories on ${connection.name}`}
                              total={reposFor(connection.id).length}
                              matched={search.filtered.length}
                              noun="repositories"
                            />
                          </div>
                        )}
                        <ul className="divide-y divide-subtle/60">
                          {search.filtering && search.filtered.length === 0 && (
                            <li className="px-4 py-3 text-xs text-fg-muted">
                              No repositories match “{search.filter.trim()}”.
                            </li>
                          )}
                          {search.filtered.map((repo) => (
                            <li key={repo.id} className="flex items-center gap-3 px-4 py-2">
                              <GitBranch size={13} className="text-fg-muted" aria-hidden />
                              <span className="flex-1 truncate font-mono text-[12px] text-fg">{repo.full_name}</span>
                              <SelectField
                                label=""
                                ariaLabel={`Project for ${repo.full_name}`}
                                value={repo.project_id ?? ""}
                                onChange={(event) =>
                                  mapRepo.mutate({ id: repo.id, projectId: event.target.value || null })
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
                              <SelectField
                                label=""
                                ariaLabel={`Work category for time mirrored from ${repo.full_name}`}
                                value={repo.time_category_id ?? ""}
                                onChange={(event) =>
                                  setCategory.mutate({ id: repo.id, categoryId: event.target.value || null })
                                }
                                disabled={!canManage}
                              >
                                <option value="">Development (default)</option>
                                {(categories.data ?? [])
                                  .filter((category) => !category.archived)
                                  .map((category) => (
                                    <option key={category.id} value={category.id}>
                                      {category.name}
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
                                        : "Backfill reads the host's API — this connection has no token"
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
                                  setNewRepo((prev) => ({ ...prev, [connection.id]: event.target.value }))
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
                      </>
                    )}
                  </RepoSearch>
                  <div className="border-t border-subtle/60 p-3">
                    <VcsIdentityMap provider={config.provider} connectionId={connection.id} canManage={canManage} />
                  </div>
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
                    placeholder={config.namePlaceholder}
                  />
                  <TextField
                    label={config.defaultBaseUrl ? "Base URL (leave for the public host)" : "Base URL"}
                    value={form.base_url}
                    onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                    placeholder={config.baseUrlPlaceholder}
                  />
                  <TextField
                    label="Webhook secret"
                    hint={config.secretHint}
                    value={form.webhook_secret}
                    onChange={(event) => setForm({ ...form, webhook_secret: event.target.value })}
                  />
                  <TextField
                    label="API token (optional)"
                    hint={config.tokenHint}
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
                    <p className="text-[12px] text-danger-text">{errorMessage(createConnection.error)}</p>
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
    </div>
  );
}

/** Per-connection repo filtering (RADD-882): the repos render inside a map over
 * connections, where a hook cannot live — this wrapper owns one list's filter. */
function RepoSearch({
  repos,
  children,
}: {
  repos: ForgejoRepo[];
  children: (search: {
    filter: string;
    setFilter: (next: string) => void;
    filtered: ForgejoRepo[];
    filtering: boolean;
  }) => ReactNode;
}) {
  const search = useListFilter(repos, (repo) => [repo.full_name]);
  return <>{children(search)}</>;
}
