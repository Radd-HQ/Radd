import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FilePlus, FileText, Plus } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { ApiPath, RoutePath, pageTreeExpandStorageKey } from "../../lib/constants";
import type { Page, PageCreate, PageTemplate } from "../../lib/types";
import { DropdownMenu } from "../DropdownMenu";
import { ListSearchInput } from "../ListSearchInput";

/** Below this many pages the tree needs no filter chrome (RADD-882). */
const FILTER_THRESHOLD = 8;

/** The bits a row must carry to render in the tree — satisfied by the authed
 * PageSummary (a public space renders through the same rows — spec 121 §5). */
interface PageTreeRow {
  id: string;
  parent_id: string | null;
  title: string;
  slug: string;
  position: number;
}

interface TreeNode {
  row: PageTreeRow;
  children: TreeNode[];
}

/** RADD-859: siblings order NATURALLY (numeric-aware), not by creation —
 * "0.18.1" belongs between "0.18.0" and "0.19.0" regardless of when the page
 * was written, and plain alphabetical would put 0.10.0 before 0.2.0. Shared
 * by the tree, radd:children and the child index so the three cannot drift. */
export function comparePagesNaturally(
  a: { title: string },
  b: { title: string },
): number {
  return a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: "base" });
}

/** Flat rows → nested tree; siblings natural-sorted; orphans go to root. */
export function buildTree(rows: PageTreeRow[]): TreeNode[] {
  const byId = new Map(rows.map((row) => [row.id, { row, children: [] } as TreeNode]));
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.row.parent_id ? byId.get(node.row.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const sortRec = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => comparePagesNaturally(a.row, b.row));
    for (const node of nodes) sortRec(node.children);
  };
  sortRec(roots);
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
}: {
  spaceId: string;
  /** The space's URL segment — rows build `/pages/<space>/<page>` (RADD-702). */
  spaceSlug: string;
  rows: PageTreeRow[];
  selectedId?: string;
  canWrite: boolean;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => loadExpanded(spaceId));

  // Title filter (RADD-882): a match renders with its ANCESTOR CHAIN — a hit
  // must stay reachable in tree shape, never float as an orphan row.
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const filtering = needle.length > 0;
  const visibleRows = useMemo(() => {
    if (!needle) return rows;
    const byId = new Map(rows.map((row) => [row.id, row]));
    const keep = new Set<string>();
    for (const row of rows) {
      if (!row.title.toLowerCase().includes(needle)) continue;
      let cursor: PageTreeRow | undefined = row;
      for (let guard = 0; cursor && guard < rows.length; guard++) {
        if (keep.has(cursor.id)) break;
        keep.add(cursor.id);
        cursor = cursor.parent_id ? byId.get(cursor.parent_id) : undefined;
      }
    }
    return rows.filter((row) => keep.has(row.id));
  }, [rows, needle]);
  const tree = useMemo(() => buildTree(visibleRows), [visibleRows]);

  // RADD-714: open to the selected page on load. Landing on a deep page from
  // search or a link previously showed a collapsed tree that gave no clue where
  // you were — the one cue the rail exists to provide.
  const parentOf = useMemo(
    () => new Map(rows.map((row) => [row.id, row.parent_id])),
    [rows],
  );
  useEffect(() => {
    if (!selectedId) return;
    setExpanded((current) => {
      const next = new Set(current);
      let cursor = parentOf.get(selectedId) ?? null;
      let added = false;
      // Bounded by the tree's depth — a cycle is impossible (the move guard
      // rejects one) but a bad row must not hang the rail.
      for (let guard = 0; cursor && guard < rows.length; guard++) {
        if (!next.has(cursor)) {
          next.add(cursor);
          added = true;
        }
        cursor = parentOf.get(cursor) ?? null;
      }
      if (!added) return current;
      localStorage.setItem(pageTreeExpandStorageKey(spaceId), JSON.stringify([...next]));
      return next;
    });
  }, [selectedId, parentOf, rows.length, spaceId]);

  // The trail from the root to the selected page, so the rail shows WHERE you
  // are and not merely what is open.
  const ancestorsOfSelected = useMemo(() => {
    const trail = new Set<string>();
    let cursor = selectedId ? (parentOf.get(selectedId) ?? null) : null;
    for (let guard = 0; cursor && guard < rows.length; guard++) {
      trail.add(cursor);
      cursor = parentOf.get(cursor) ?? null;
    }
    return trail;
  }, [selectedId, parentOf, rows.length]);

  const toggle = (pageId: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(pageId)) next.delete(pageId);
      else next.add(pageId);
      localStorage.setItem(pageTreeExpandStorageKey(spaceId), JSON.stringify([...next]));
      return next;
    });
  };

  // While filtering, every kept node is expanded — the matches must be VISIBLE,
  // and the persisted expand state stays untouched for when the filter clears.
  const effectiveExpanded = useMemo(
    () => (filtering ? new Set(visibleRows.map((row) => row.id)) : expanded),
    [filtering, visibleRows, expanded],
  );

  return (
    // data-page-tree: the print proof asserts this tree is ABSENT from the
    // print view — without the attribute on the live tree the check passed
    // vacuously against every page (RADD-880).
    <div data-page-tree className="flex flex-col gap-0.5">
      {rows.length > FILTER_THRESHOLD && (
        <ListSearchInput
          className="mb-1.5"
          value={filter}
          onChange={setFilter}
          placeholder="Filter pages…"
          ariaLabel="Filter pages by title"
          total={rows.length}
          matched={visibleRows.length}
          noun="pages"
        />
      )}
      {filtering && tree.length === 0 && (
        <p className="px-1 py-1.5 text-xs text-fg-faint">No pages match “{filter.trim()}”.</p>
      )}
      {tree.map((node) => (
        <TreeRow
          key={node.row.id}
          spaceId={spaceId}
          spaceSlug={spaceSlug}
          node={node}
          depth={0}
          expanded={effectiveExpanded}
          onToggle={toggle}
          selectedId={selectedId}
          ancestors={ancestorsOfSelected}
          canWrite={canWrite}
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
  ancestors,
  onToggle,
  selectedId,
  canWrite,
}: {
  spaceId: string;
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  ancestors: Set<string>;
  onToggle: (pageId: string) => void;
  selectedId?: string;
  canWrite: boolean;
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
            : ancestors.has(row.id)
              ? "text-fg hover:bg-elevated/60"
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
          to={RoutePath.page}
          params={{ spaceSlug, pageSlug: row.slug }}
          className="min-w-0 flex-1 truncate py-1"
        >
          {row.title}
        </Link>
        {/* RADD-714: how big is this section, without expanding it. */}
        {children.length > 0 && !isOpen && (
          <span className="shrink-0 rounded bg-elevated px-1 font-mono text-[10px] text-fg-faint">
            {children.length}
          </span>
        )}
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
            ancestors={ancestors}
            onToggle={onToggle}
            selectedId={selectedId}
            canWrite={canWrite}
            />
        ))}
    </>
  );
}

/** Creates an untitled page (at root or under a node) and navigates to it.
 * The root button offers the space's templates (RADD-1100) — blank stays one
 * click; a template renders `{{title}}/{{date}}/{{author}}` server-side. */
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
  const templates = useQuery({
    queryKey: ["page-templates", spaceId],
    queryFn: ({ signal }) =>
      api.get<PageTemplate[]>(ApiPath.pageTemplates, { signal, query: { space_id: spaceId } }),
    enabled: !iconOnly,
    staleTime: 60_000,
  });
  const create = useMutation({
    mutationFn: (template?: string) =>
      api.post<Page>(ApiPath.pages, {
        space_id: spaceId,
        parent_id: parentId,
        title: "Untitled",
        template,
      } satisfies PageCreate),
    onSuccess: (page) =>
      void navigate({ to: RoutePath.page, params: { spaceSlug, pageSlug: page.slug } }),
    onSettled: () => void invalidateEntities(queryClient, Entity.page, Entity.docSpace),
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
