import { useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, FilePlus, FileText, Plus } from "lucide-react";
import { api, invalidateEntities, DropdownMenu } from "@radd/plugin-sdk";
import { PageApi } from "../endpoints";
import { pageLink } from "../links";
import { Tag } from "../queries";
import type { Page, PageCreate, PageTemplate } from "../types";

/** Creates an untitled page (at root or under a node) and navigates to it.
 * The root button offers the space's templates (RADD-1100) — blank stays one
 * click; a template renders `{{title}}/{{date}}/{{author}}` server-side. */
export function NewPageButton({
  spaceId,
  spaceSlug,
  parentId,
  depth,
  iconOnly = false,
}: {
  spaceId: string;
  spaceSlug: string;
  parentId: string | null;
  depth: number;
  iconOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const templates = useQuery({
    queryKey: ["page-templates", spaceId],
    queryFn: ({ signal }) =>
      api.get<PageTemplate[]>(PageApi.templates, { signal, query: { space_id: spaceId } }),
    enabled: !iconOnly,
    staleTime: 60_000,
  });
  const create = useMutation({
    mutationFn: (template?: string) =>
      api.post<Page>(PageApi.pages, {
        space_id: spaceId,
        parent_id: parentId,
        title: "Untitled",
        template,
      } satisfies PageCreate),
    onSuccess: (page) =>
      void navigate(pageLink(spaceSlug, page.path)),
    onSettled: () => void invalidateEntities(queryClient, Tag.page, Tag.space),
  });

  if (iconOnly) {
    return (
      <button
        type="button"
        onClick={() => create.mutate(undefined)}
        disabled={create.isPending}
        aria-label="New page inside"
        title="New page inside"
        className="rounded p-0.5 text-fg-faint hover:bg-strong hover:text-fg cursor-pointer disabled:opacity-50"
      >
        <Plus size={12} aria-hidden />
      </button>
    );
  }

  const triggerClass =
    "mt-1 flex items-center gap-1.5 rounded-md py-1 text-xs text-fg-faint hover:text-fg cursor-pointer disabled:opacity-50";
  const available = templates.data ?? [];
  if (available.length === 0) {
    return (
      <button
        type="button"
        onClick={() => create.mutate(undefined)}
        disabled={create.isPending}
        className={triggerClass}
        style={{ paddingLeft: `${depth * 14 + 6}px` }}
      >
        <Plus size={12} aria-hidden />
        New page
      </button>
    );
  }
  return (
    <DropdownMenu
      label="New page"
      widthClass="w-56"
      items={[
        {
          kind: "action",
          label: "Blank page",
          icon: FileText,
          onSelect: () => create.mutate(undefined),
        },
        { kind: "separator" },
        ...available.map((template) => ({
          kind: "action" as const,
          label: template.icon ? `${template.icon} ${template.name}` : template.name,
          icon: FilePlus,
          onSelect: () => create.mutate(template.name),
        })),
      ]}
      trigger={({ ref, toggle }) => (
        <button
          ref={ref}
          type="button"
          onClick={toggle}
          disabled={create.isPending}
          className={triggerClass}
          style={{ paddingLeft: `${depth * 14 + 6}px` }}
        >
          <Plus size={12} aria-hidden />
          New page
          <ChevronDown size={11} aria-hidden />
        </button>
      )}
    />
  );
}
