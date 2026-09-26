import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { GitBranch, History, Trash2 } from "lucide-react";
import { api, errorMessage, invalidateEntities, useConfirm, Button, IconButton, SelectField, Slot, Switch } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT } from "@radd-plugin-ui/projects/picker-contract";
import type { WorkCategoryChoice } from "@radd-plugin-ui/timelogging/lookup-contract";
import { hostEntities, hostPaths } from "./queries";
import type { HostBackfillReport, HostConnection, HostRepo } from "./types";

/** What a repository row may change in one PATCH. */
type RepoPatch = Partial<Pick<HostRepo,
  "enabled" | "link_all_projects" | "mirror_time" | "move_on_merge" | "publish_on_release" | "project_id" | "time_category_id">>;

/** The work categories a mirrored worklog can carry — `undefined` while loading. */
export type Categories = { rows: WorkCategoryChoice[] | undefined; unavailable: boolean };

/** One registered repository: where its versions publish, the category mirrored time carries, its
 *  switches. Each row owns its mutations, so saving one repository never disables the others. */
export function RepoRow({ provider, changeNoun, connection, repo, categories }: {
  provider: string;
  /** What a merged change is called on this host ("merge request", "pull request"). */
  changeNoun: string;
  connection: HostConnection;
  repo: HostRepo;
  categories: Categories;
}) {
  const queryClient = useQueryClient();
  const paths = hostPaths(provider);
  const refresh = () => invalidateEntities(queryClient, ...hostEntities(provider));
  const [confirmDialog, confirm] = useConfirm();
  const [report, setReport] = useState<HostBackfillReport | null>(null);
  const patch = useMutation({
    mutationFn: (values: RepoPatch) => api.patch<HostRepo>(paths.repo(repo.id), values),
    onSettled: refresh,
  });
  const remove = useMutation({ mutationFn: () => api.delete<void>(paths.repo(repo.id)), onSettled: refresh });
  const backfill = useMutation({
    mutationFn: () => api.post<HostBackfillReport>(paths.backfill(repo.id), {}),
    onSuccess: (result) => {
      setReport(result);
      void refresh();
    },
  });
  const askRemove = async () => {
    const ok = await confirm({
      title: `Remove ${repo.full_name}?`,
      message: "Webhooks from it stop being accepted. Links it already made to issues stay.",
      confirmLabel: "Remove repository",
      danger: true,
    });
    if (ok) remove.mutate();
  };
  const error = [patch, remove, backfill].find((mutation) => mutation.isError)?.error;

  return (
    <li className="flex flex-col gap-2 px-4 py-2.5" data-repo={repo.full_name}>
      {confirmDialog}
      <div className="flex min-w-0 items-center gap-2">
        <GitBranch size={13} className="shrink-0 text-fg-muted" aria-hidden />
        <span data-repo-name={repo.id} className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg">{repo.full_name}</span>
        <Button size="sm" variant="ghost" onClick={() => backfill.mutate()}
          disabled={backfill.isPending || !connection.has_token || !connection.active || !repo.enabled}
          title={connection.has_token ? "Link branches, requests and commits that predate the webhook" : "Backfill reads the host's API — this connection has no token"}>
          <History size={13} aria-hidden /> {backfill.isPending ? "Backfilling…" : "Backfill"}
        </Button>
        <IconButton danger aria-label={`Remove ${repo.full_name}`} onClick={() => void askRemove()} disabled={remove.isPending}>
          <Trash2 size={13} aria-hidden />
        </IconButton>
      </div>
      <div className="flex flex-wrap items-end gap-3 pl-5">
        <div className="min-w-56 max-w-80 flex-1">
          <Slot id={PROJECT_SELECT_SLOT} value={repo.project_id ?? ""} label="Default project" emptyLabel="No project"
            onChange={(id: string) => patch.mutate({ project_id: id || null })}
            fallback={<span className="text-xs text-fg-muted">Projects are unavailable.</span>} />
        </div>
        <CategorySelect repo={repo} categories={categories} onChange={(id) => patch.mutate({ time_category_id: id })} />
      </div>
      {/* Switches stay live while another field saves: each is its own PATCH,
          and disabling them swallowed a click that arrived mid-save (RADD-1370). */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 pl-5">
        <Switch label="Ingest webhooks" checked={repo.enabled}
          onChange={(next) => patch.mutate({ enabled: next })} data-ingest={repo.full_name} />
        <Switch label="Link across projects" checked={repo.link_all_projects}
          onChange={(next) => patch.mutate({ link_all_projects: next })} />
        <Switch label="Mirror time" checked={repo.mirror_time}
          onChange={(next) => patch.mutate({ mirror_time: next })} data-mirror-time={repo.full_name} />
      </div>
      {/* RADD-1369: what a delivery DOES beyond linking — off until switched on here. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 pl-5">
        <Switch label={`Move linked issues to waiting for release when a ${changeNoun} merges`}
          checked={repo.move_on_merge}
          onChange={(next) => patch.mutate({ move_on_merge: next })} data-move-on-merge={repo.full_name} />
        <Switch label="Publish a version on release and ship what is waiting"
          checked={repo.publish_on_release} disabled={!repo.project_id && !repo.publish_on_release}
          onChange={(next) => patch.mutate({ publish_on_release: next })} data-publish-on-release={repo.full_name} />
        {!repo.project_id && <span className="text-[11px] text-fg-muted">Publishing needs a default project.</span>}
      </div>
      {error && <p role="alert" className="pl-5 text-xs text-status-danger-ink">{errorMessage(error)}</p>}
      {report && (
        <details className="pl-5 text-xs text-fg-muted" open>
          <summary>{report.linked} linked · {report.branches} branches · {report.commits} commits · {report.pull_requests} requests</summary>
          {(report.unknown_keys ?? []).length > 0 && <p>Unknown issue keys: {report.unknown_keys.join(", ")}</p>}
          {Object.entries(report.worklogs ?? {}).map(([key, value]) => (
            <p key={key}>Time — {key.replaceAll("_", " ")}: {Array.isArray(value) ? value.join(", ") : String(value)}</p>
          ))}
          {(report.errors ?? []).map((line, index) => <p key={index} className="text-status-danger-ink">{line}</p>)}
        </details>
      )}
    </li>
  );
}

/** RADD-1258: the work category a worklog mirrored from this repository carries.
 * A saved category that is archived still shows its name; one that no longer
 * exists says so — never a raw id, and nothing is guessed while loading. */
function CategorySelect({ repo, categories, onChange }: {
  repo: HostRepo;
  categories: Categories;
  onChange: (id: string | null) => void;
}) {
  const rows = categories.rows;
  const saved = repo.time_category_id ? rows?.find((row) => row.id === repo.time_category_id) : undefined;
  const savedLabel = !repo.time_category_id ? null
    : !rows ? (categories.unavailable ? "Saved category (categories unavailable)" : "Loading…")
    : !saved ? "A deleted category"
    : saved.archived ? `${saved.name} (archived)` : null;
  return (
    <div className="w-56">
      <SelectField label="Work category for mirrored time" ariaLabel={`Work category for time mirrored from ${repo.full_name}`}
        value={repo.time_category_id ?? ""}
        onChange={(event) => onChange(event.target.value || null)} disabled={!rows || categories.unavailable}>
        <option value="">Development (default)</option>
        {savedLabel && <option value={repo.time_category_id ?? ""}>{savedLabel}</option>}
        {(rows ?? []).filter((row) => !row.archived).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
      </SelectField>
    </div>
  );
}
