import { useMemo, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FileText, Plus } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { ApiPath, RoutePath, pageTreeExpandStorageKey } from "../../lib/constants";
import type { Page, PageCreate } from "../../lib/types";

/** The bits a row must carry to render in the tree — satisfied by the authed
 * PageSummary AND the public-KB PublicPageNode (spec 74). */
interface PageTreeRow {
  id: string;
  parent_id: string | null;
  title: string;
  slug: string;
  position: number;
}

/** Where a row's link points: the authed pages (default) or the public ones.
 * Both routes carry the same $spaceSlug/$pageSlug params, so `Link` stays typed. */
type PageRoutePath = typeof RoutePath.page | typeof RoutePath.publicPage;

interface TreeNode {
  row: PageTreeRow;
  children: TreeNode[];
}

/** Flat rows → nested tree. Rows arrive position-sorted; orphans go to root. */
export function buildTree(rows: PageTreeRow[]): TreeNode[] {
  const byId = new Map(rows.map((row) => [row.id, { row, children: [] } as TreeNode]));
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.row.parent_id ? byId.get(node.row.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function loadExpanded(spaceId: string): Set<string> {
  try {
    const raw = localStorage.getItem(pageTreeExpandStorageKey(spaceId));
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

/**
 * Collapsible page tree for a page space (spec 43). Expand/collapse state is
 * persisted per space in localStorage; "+ page" appears at the root and per
 * node when the caller may write docs.
 */
export function PageTree({
  spaceId,
  spaceSlug,
  rows,
  selectedId,
  canWrite,
  pageRoute = RoutePath.page,
}: {
  spaceId: string;
  /** The space's URL segment — rows build `/pages/<space>/<page>` (RADD-702). */
  spaceSlug: string;
  rows: PageTreeRow[];
  selectedId?: string;
  canWrite: boolean;
  /** Public trees (spec 74) link to /public-pages instead of the authed pages. */
  pageRoute?: PageRoutePath;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => loadExpanded(spaceId));
  const tree = useMemo(() => buildTree(rows), [rows]);

  const toggle = (pageId: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(pageId)) next.delete(pageId);
      else next.add(pageId);
      localStorage.setItem(pageTreeExpandStorageKey(spaceId), JSON.stringify([...next]));
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-0.5">
      {tree.map((node) => (
        <TreeRow
          key={node.row.id}
          spaceId={spaceId}
          spaceSlug={spaceSlug}
          node={node}
          depth={0}
          expanded={expanded}
          onToggle={toggle}
          selectedId={selectedId}
          canWrite={canWrite}
          pageRoute={pageRoute}
        />
      ))}
      {canWrite && <NewPageButton spaceId={spaceId} spaceSlug={spaceSlug} parentId={null} depth={0} />}
    </div>
  );
}

function TreeRow({
  spaceId,
  spaceSlug,
  node,
  depth,
  expanded,
  onToggle,
  selectedId,
  canWrite,
  pageRoute,
}: {
  spaceId: string;
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (pageId: string) => void;
  selectedId?: string;
  canWrite: boolean;
  pageRoute: PageRoutePath;
  spaceSlug: string;
}) {
  const { row, children } = node;
  const isOpen = expanded.has(row.id);
  const Caret = isOpen ? ChevronDown : ChevronRight;
  return (
    <>
      <div
        className={
          "group/docrow flex items-center gap-1 rounded-md pr-1 text-[13px] " +
          (row.id === selectedId
            ? "bg-elevated text-heading"
            : "text-fg-secondary hover:bg-elevated/60 hover:text-fg")
        }
        style={{ paddingLeft: `${depth * 14 + 4}px` }}
      >
        {children.length > 0 ? (
          <button
            type="button"
            onClick={() => onToggle(row.id)}
            aria-label={isOpen ? `Collapse ${row.title}` : `Expand ${row.title}`}
            className="rounded p-0.5 text-fg-faint hover:text-fg cursor-pointer"
          >
            <Caret size={13} aria-hidden />
          </button>
        ) : (
          <FileText size={12} className="ml-0.5 shrink-0 text-fg-faint" aria-hidden />
        )}
        <Link
          to={pageRoute}
          params={{ spaceSlug, pageSlug: row.slug }}
          className="min-w-0 flex-1 truncate py-1"
        >
          {row.title}
        </Link>
        {canWrite && (
          <span className="opacity-0 transition-opacity focus-within:opacity-100 group-hover/docrow:opacity-100">
            <NewPageButton spaceId={spaceId} spaceSlug={spaceSlug} parentId={row.id} depth={depth} iconOnly />
          </span>
        )}
      </div>
      {isOpen &&
        children.map((child) => (
          <TreeRow
            key={child.row.id}
            spaceId={spaceId}
            spaceSlug={spaceSlug}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            onToggle={onToggle}
            selectedId={selectedId}
            canWrite={canWrite}
            pageRoute={pageRoute}
          />
        ))}
    </>
  );
}

/** Creates an untitled page (at root or under a node) and navigates to it. */
function NewPageButton({
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
  const create = useMutation({
    mutationFn: () =>
      api.post<Page>(ApiPath.pages, {
        space_id: spaceId,
        parent_id: parentId,
        title: "Untitled",
      } satisfies PageCreate),
    onSuccess: (page) =>
      void navigate({ to: RoutePath.page, params: { spaceSlug, pageSlug: page.slug } }),
    onSettled: () => void invalidateEntities(queryClient, Entity.page, Entity.docSpace),
  });

  if (iconOnly) {
    return (
      <button
        type="button"
        onClick={() => create.mutate()}
        disabled={create.isPending}
        aria-label="New page inside"
        title="New page inside"
        className="rounded p-0.5 text-fg-faint hover:bg-strong hover:text-fg cursor-pointer disabled:opacity-50"
      >
        <Plus size={12} aria-hidden />
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={() => create.mutate()}
      disabled={create.isPending}
      className="mt-1 flex items-center gap-1.5 rounded-md py-1 text-xs text-fg-faint hover:text-fg cursor-pointer disabled:opacity-50"
      style={{ paddingLeft: `${depth * 14 + 6}px` }}
    >
      <Plus size={12} aria-hidden />
      New page
    </button>
  );
}
