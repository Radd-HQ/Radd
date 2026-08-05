import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, GitBranch, Plus, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiItemVcsLinksPath, apiVcsLinkPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import {
  CI_STATE_META,
  VCS_PROVIDER_LABELS,
  VCS_REF_TYPE_META,
  VCS_REF_TYPE_ORDER,
  vcsRefVisual,
} from "../../lib/meta";
import { itemVcsLinksQuery } from "../../lib/queries";
import {
  Permission,
  VcsRefType,
  type Item,
  type Project,
  type VcsLink,
  type VcsLinkCreate,
  type VcsRefTypeValue,
} from "../../lib/types";
import { Button } from "../Button";
import { Select } from "../Select";
import { Spinner } from "../Spinner";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";

/**
 * The Version-control tab: branches, commits, and merge/pull requests linked to
 * the item. Populated automatically by connectors (GitLab/GitHub) later via the
 * backend upsert seam; for now links can be added manually.
 */
export function VcsPanel({ item, project }: { item: Item; project: Project }) {
  const perms = usePermissions();
  const canWrite = perms.project(project, Permission.itemUpdate);
  const links = useQuery(itemVcsLinksQuery(item.id));

  if (links.isPending) return <Spinner label="Loading version control…" />;
  if (links.isError) {
    return <p className="text-xs text-red-400">Failed to load: {errorMessage(links.error)}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {links.data.length === 0 ? (
        <div className="rounded-md border border-dashed border-subtle px-3 py-3 text-xs text-fg-muted">
          <p className="flex items-center gap-2 text-fg-secondary">
            <GitBranch size={13} aria-hidden />
            No branches or pull requests linked yet.
          </p>
          <p className="mt-1">
            Branches, commits and pull requests link themselves when a connected host
            mentions this issue&rsquo;s key
            {canWrite ? " — or add one manually below." : "."}
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {links.data.map((link) => (
            <VcsRow key={link.id} link={link} canWrite={canWrite} />
          ))}
        </ul>
      )}
      {canWrite && <AddVcsForm itemId={item.id} />}
    </div>
  );
}

function VcsRow({ link, canWrite }: { link: VcsLink; canWrite: boolean }) {
  const queryClient = useQueryClient();
  // Type AND state pick the glyph: a merged pull request is not an open one with
  // a different word next to it (RADD-650).
  const visual = vcsRefVisual(link.ref_type, link.status ?? "");
  const Icon = visual.icon;
  const ci = link.ci_state ? CI_STATE_META[link.ci_state] : undefined;
  const CiIcon = ci?.icon;
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiVcsLinkPath(link.id)),
    onSettled: () => void invalidateEntities(queryClient, Entity.vcsLink),
  });
  return (
    <li className="group/vcs flex items-center gap-2 rounded-md border border-subtle bg-surface/50 px-2.5 py-1.5">
      <Icon
        size={14}
        className={`shrink-0 ${visual.iconClassName}`}
        aria-hidden
      />
      <span className="sr-only">{visual.label}</span>
      <a
        href={link.url}
        target="_blank"
        rel="noreferrer"
        title={visual.label}
        className="flex min-w-0 flex-1 items-center gap-2 text-[13px] hover:underline"
      >
        <span className="truncate text-fg">{link.title}</span>
        <ExternalLink size={11} className="shrink-0 text-fg-faint" aria-hidden />
      </a>
      {ci && CiIcon && (
        // Absent ci_state renders nothing at all: an unreported build must not
        // look like a failed one.
        <a
          href={link.ci_url || link.url}
          target="_blank"
          rel="noreferrer"
          title={ci.label}
          className={`flex shrink-0 items-center gap-1 rounded border px-1.5 py-px text-[11px] ${ci.className}`}
        >
          <CiIcon size={11} aria-hidden />
          <span className="sr-only">{ci.label}</span>
        </a>
      )}
      {link.status && (
        <span
          className={`shrink-0 rounded border px-1.5 py-px text-[11px] ${visual.pillClassName}`}
        >
          {link.status}
        </span>
      )}
      <span className="shrink-0 text-[11px] text-fg-faint">
        {VCS_PROVIDER_LABELS[link.provider] ?? link.provider}
      </span>
      {canWrite && (
        <IconButton
          danger
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          aria-label={`Remove ${link.title}`}
        >
          <X size={13} />
        </IconButton>
      )}
    </li>
  );
}

function AddVcsForm({ itemId }: { itemId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [refType, setRefType] = useState<VcsRefTypeValue>(VcsRefType.merge_request);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post<VcsLink>(apiItemVcsLinksPath(itemId), {
        ref_type: refType,
        title: title.trim(),
        url: url.trim(),
      } satisfies VcsLinkCreate),
    onSuccess: () => {
      setTitle("");
      setUrl("");
      setOpen(false);
    },
    onSettled: () => void invalidateEntities(queryClient, Entity.vcsLink),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (title.trim() && url.trim()) create.mutate();
  };

  if (!open) {
    return (
      <Button variant="secondary" size="sm" className="w-fit" onClick={() => setOpen(true)}>
        <Plus size={12} aria-hidden />
        Link a branch or pull request
      </Button>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-2 rounded-lg border border-subtle bg-surface/40 p-3"
    >
      <div className="flex flex-wrap gap-2">
        <Select
          value={refType}
          onChange={(value) => setRefType(value as VcsRefTypeValue)}
          aria-label="Reference type"
          options={VCS_REF_TYPE_ORDER.map((value) => ({
            value,
            label: VCS_REF_TYPE_META[value].label,
          }))}
        />
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Title (e.g. feature/login or !42)"
          className="h-8 min-w-40 flex-1 rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
      </div>
      <input
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="URL"
        type="url"
        className="h-8 w-full rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
      {create.isError && <ErrorText error={create.error} />}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending || !title.trim() || !url.trim()}>
          {create.isPending ? "Linking…" : "Link"}
        </Button>
      </div>
    </form>
  );
}
