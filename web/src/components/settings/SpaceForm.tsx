import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Plus, X } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath, apiPageSpacePath, apiPageSpacePublicAccessPath, spacePublicUrl } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import type { PageSpace, PageSpaceCreate, PageSpaceUpdate, SpacePublicAccessUpdate } from "../../lib/types";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { ErrorText } from "../ErrorText";

/** The shareable wiki URL + a copy button (the spec-62 PublicLinkRow idiom). */
function PublicPagesLinkRow({ spaceSlug }: { spaceSlug: string }) {
  const [copied, setCopied] = useState(false);
  const url = spacePublicUrl(spaceSlug);
  const copy = async () => {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        readOnly
        value={url}
        onFocus={(event) => event.target.select()}
        className="h-7 min-w-0 flex-1 rounded-md border border-strong bg-surface px-2 font-mono text-[12px] text-fg"
      />
      <Button size="sm" variant="secondary" className="shrink-0" onClick={copy}>
        {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

export function SpaceForm({
  existing,
  onDone,
}: {
  existing?: PageSpace;
  onDone?: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [isPublic, setIsPublic] = useState(existing?.public ?? false);

  const save = useMutation({
    mutationFn: () =>
      existing
        ? api
            .patch<PageSpace>(apiPageSpacePath(existing.id), {
              name: name.trim(),
              description,
            } satisfies PageSpaceUpdate)
            .then((saved) =>
              // Spec 121 §5: the switch is a grant, written through its own call.
              isPublic === Boolean(existing.public)
                ? saved
                : api.put<PageSpace>(apiPageSpacePublicAccessPath(existing.id), {
                    public: isPublic,
                  } satisfies SpacePublicAccessUpdate),
            )
        : api.post<PageSpace>(ApiPath.pageSpaces, {
            name: name.trim(),
            description,
          } satisfies PageSpaceCreate),
    onSuccess: () => {
      if (!existing) {
        setName("");
        setDescription("");
      }
      onDone?.();
    },
    onSettled: () => invalidateEntities(queryClient, Entity.docSpace),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3">
      <TextField
        label={existing ? "Name" : "New space name"}
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Engineering handbook"
        maxLength={200}
      />
      <TextField
        label="Description (optional)"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        placeholder="What lives in this space"
      />
      {existing && (
        <div className="flex flex-col gap-2 rounded-lg border border-subtle bg-surface/40 p-3">
          <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(event) => setIsPublic(event.target.checked)}
              className="size-4 accent-accent"
            />
            Public — anyone with the link can read this space's pages, no sign-in
          </label>
          <p className="text-xs text-fg-muted">
            Archived pages stay hidden. Use external image URLs in public pages — attachment
            links still need a login.
          </p>
          {isPublic && <PublicPagesLinkRow spaceSlug={existing.slug} />}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={save.isPending || !name.trim()}>
          <Plus size={14} aria-hidden />
          {save.isPending ? "Saving…" : existing ? "Save changes" : "Create space"}
        </Button>
        {existing && (
          <Button size="sm" variant="ghost" onClick={onDone}>
            <X size={12} aria-hidden />
            Cancel
          </Button>
        )}
        {save.isError && <ErrorText error={save.error} />}
      </div>
    </form>
  );
}
