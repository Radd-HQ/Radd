import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { FilePlus } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { ApiPath } from "../../lib/constants";
import { ExtensionCard, usePageExtensionContext } from "../../lib/page-extensions";
import type { Page } from "../../lib/types";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { pageLink } from "../../lib/page-links";

/**
 * `radd:new-from-template` — a button that creates a CHILD of the page it sits
 * on, from a named template (RADD-712).
 *
 * This is what makes a section self-service: the landing page carries the
 * button, and everyone adds correctly-shaped children without being told how or
 * being trusted to copy last time's page and remember to change everything.
 */
export function NewFromTemplate({ params }: { params: Record<string, unknown> }) {
  const ctx = usePageExtensionContext();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [asking, setAsking] = useState(false);

  const template = typeof params.template === "string" ? params.template : "";
  const label = typeof params.label === "string" ? params.label : "New page";
  const prompt =
    typeof params.title_prompt === "string" ? params.title_prompt : "Title for the new page";

  const create = useMutation({
    mutationFn: () =>
      api.post<Page>(ApiPath.pages, {
        space_id: ctx.spaceId,
        parent_id: ctx.pageId,
        title: title.trim(),
        template,
      }),
    onSuccess: (page) => {
      setAsking(false);
      setTitle("");
      void invalidateEntities(queryClient, Entity.page);
      void navigate(pageLink(page.space.slug, page.path));
    },
  });

  if (!template) {
    return (
      <ExtensionCard label="New page from template">
        <p className="text-[13px] text-fg-secondary">
          Set <code className="font-mono">template</code> to the name of a template.
        </p>
      </ExtensionCard>
    );
  }

  if (!ctx.pageId) {
    // Previews and non-page surfaces have nothing to parent a new page to.
    return (
      <ExtensionCard label="New page from template">
        <p className="text-[13px] text-fg-faint">Available on a page.</p>
      </ExtensionCard>
    );
  }

  return (
    <div className="my-2">
      {asking ? (
        <div className="flex items-end gap-2 rounded-lg border border-subtle bg-surface p-2">
          <TextField
            label={prompt}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            autoFocus
            onKeyDown={(event) => {
              if (event.key === "Enter" && title.trim()) create.mutate();
              if (event.key === "Escape") setAsking(false);
            }}
          />
          <Button size="sm" disabled={!title.trim() || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Creating…" : "Create"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button size="sm" onClick={() => setAsking(true)}>
          <FilePlus size={13} aria-hidden />
          {label}
        </Button>
      )}
      {create.isError && (
        <p className="mt-1 text-xs text-red-400">
          Could not create the page — is there a template called “{template}”?
        </p>
      )}
    </div>
  );
}
