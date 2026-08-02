import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Link2, Plus, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiItemWebLinksPath, apiWebLinkPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { WEBLINK_CATEGORY_META, WEBLINK_CATEGORY_ORDER } from "../../lib/meta";
import { itemWebLinksQuery } from "../../lib/queries";
import {
  Permission,
  WebLinkCategory,
  type Item,
  type Project,
  type WebLink,
  type WebLinkCategoryValue,
  type WebLinkCreate,
} from "../../lib/types";
import { Button } from "../Button";
import { Select } from "../Select";

/**
 * Related / external links on an item (`weblinks` module): docs, design files,
 * external references — anything URL-addressable that isn't a dependency link or
 * a version-control ref. Lives in the reading column under Dependencies.
 */
export function RelatedLinksSection({ item, project }: { item: Item; project: Project }) {
  const perms = usePermissions();
  const canWrite = perms.project(project, Permission.itemUpdate);
  const links = useQuery(itemWebLinksQuery(item.id));

  if (links.isError) {
    return <p className="text-xs text-red-400">Failed to load links: {errorMessage(links.error)}</p>;
  }

  const data = links.data ?? [];
  return (
    <div className="flex flex-col gap-2">
      {data.length === 0 ? (
        <p className="text-[13px] text-fg-faint">No related links yet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {data.map((link) => (
            <WebLinkRow key={link.id} link={link} canWrite={canWrite} />
          ))}
        </ul>
      )}
      {canWrite && <AddWebLinkForm itemId={item.id} />}
    </div>
  );
}

function WebLinkRow({ link, canWrite }: { link: WebLink; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const meta = WEBLINK_CATEGORY_META[link.category];
  const Icon = meta?.icon ?? Link2;
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiWebLinkPath(link.id)),
    onSettled: () => void invalidateEntities(queryClient, Entity.webLink),
  });
  return (
    <li className="group/wl flex items-center gap-2 rounded-md border border-subtle bg-surface/50 px-2.5 py-1.5">
      <Icon size={14} className="shrink-0 text-fg-muted" aria-hidden />
      <a
        href={link.url}
        target="_blank"
        rel="noreferrer"
        className="flex min-w-0 flex-1 items-center gap-2 text-[13px] hover:underline"
        title={link.url}
      >
        <span className="truncate text-fg">{link.title || link.url}</span>
        <ExternalLink size={11} className="shrink-0 text-fg-faint" aria-hidden />
      </a>
      <span className="shrink-0 text-[11px] text-fg-faint">{meta?.label ?? link.category}</span>
      {canWrite && (
        <button
          type="button"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          aria-label={`Remove link ${link.title || link.url}`}
          className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-50"
        >
          <X size={13} />
        </button>
      )}
    </li>
  );
}

function AddWebLinkForm({ itemId }: { itemId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<WebLinkCategoryValue>(WebLinkCategory.external);

  const create = useMutation({
    mutationFn: () =>
      api.post<WebLink>(apiItemWebLinksPath(itemId), {
        url: url.trim(),
        title: title.trim(),
        category,
      } satisfies WebLinkCreate),
    onSuccess: () => {
      setUrl("");
      setTitle("");
      setCategory(WebLinkCategory.external);
      setOpen(false);
    },
    onSettled: () => void invalidateEntities(queryClient, Entity.webLink),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (url.trim()) create.mutate();
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-fit items-center gap-1.5 rounded border border-strong px-2 py-1 text-xs text-fg hover:bg-elevated cursor-pointer"
      >
        <Plus size={12} aria-hidden />
        Add link
      </button>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-2 rounded-lg border border-subtle bg-surface/40 p-3"
    >
      <input
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="URL"
        type="url"
        autoFocus
        className="h-8 w-full rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
      <div className="flex flex-wrap gap-2">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Title (optional)"
          className="h-8 min-w-40 flex-1 rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
        <Select
          value={category}
          onChange={(value) => setCategory(value as WebLinkCategoryValue)}
          aria-label="Link category"
          options={WEBLINK_CATEGORY_ORDER.map((value) => ({
            value,
            label: WEBLINK_CATEGORY_META[value].label,
          }))}
        />
      </div>
      {create.isError && <p className="text-xs text-red-400">{errorMessage(create.error)}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending || !url.trim()}>
          {create.isPending ? "Adding…" : "Add link"}
        </Button>
      </div>
    </form>
  );
}
