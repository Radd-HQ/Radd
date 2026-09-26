import { useEffect, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, CornerLeftUp, FileText, MoreHorizontal } from "lucide-react";
import { DropdownMenu, ListSearchInput } from "@radd/plugin-sdk";
import { treeExpandStorageKey } from "../endpoints";
import { pageLink } from "../links";
import { MovePageModal } from "./MovePageModal";
import { NewPageButton } from "./NewPageButton";
import { ancestorIds, buildTree, type TreeNode } from "./page-tree";

/** Below this many pages the tree needs no filter chrome (RADD-882). */
const FILTER_THRESHOLD = 8;

/** The fields a tree row renders. */
interface PageTreeRow {
  id: string;
  parent_id: string | null;
  title: string;
  slug: string;
  /** RADD-1233: the row's space-relative address — what its link carries. */
  path: string;
  position: number;
}

function loadExpanded(spaceId: string): Set<string> {
  try {
    const raw = localStorage.getItem(treeExpandStorageKey(spaceId));
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
  /** The space's URL segment — rows build `/pages/<space>/<path>` (RADD-702, RADD-1233). */
  spaceSlug: string;
  rows: PageTreeRow[];
  selectedId?: string;
  canWrite: boolean;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => loadExpanded(spaceId));
  const parentOf = useMemo(
    () => new Map(rows.map((row) => [row.id, row.parent_id])),
    [rows],
  );

  // Title filter (RADD-882): a match renders with its ANCESTOR CHAIN — a hit
  // must stay reachable in tree shape, never float as an orphan row.
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const filtering = needle.length > 0;
  const visibleRows = useMemo(() => {
    if (!needle) return rows;
    const keep = new Set<string>();
    for (const row of rows) {
      if (!row.title.toLowerCase().includes(needle)) continue;
      keep.add(row.id);
      for (const id of ancestorIds(parentOf, row.id, rows.length)) keep.add(id);
    }
    return rows.filter((row) => keep.has(row.id));
  }, [rows, needle, parentOf]);
  const tree = useMemo(() => buildTree(visibleRows), [visibleRows]);

  // The trail from the root to the selected page, so the rail shows WHERE you
  // are and not merely what is open.
  const ancestorsOfSelected = useMemo(
    () => new Set(selectedId ? ancestorIds(parentOf, selectedId, rows.length) : []),
    [selectedId, parentOf, rows.length],
  );
  const persistExpanded = (next: Set<string>) =>
    localStorage.setItem(treeExpandStorageKey(spaceId), JSON.stringify([...next]));
  // Open the tree to the selected page (RADD-714).
  useEffect(() => {
    if (!ancestorsOfSelected.size) return;
    setExpanded((current) => {
      if ([...ancestorsOfSelected].every((id) => current.has(id))) return current;
      const next = new Set([...current, ...ancestorsOfSelected]);
      persistExpanded(next);
      return next;
    });
  }, [ancestorsOfSelected, spaceId]);

  const toggle = (pageId: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(pageId)) next.delete(pageId);
      else next.add(pageId);
      persistExpanded(next);
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
          rows={rows}
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
  rows,
  node,
  depth,
  expanded,
  ancestors,
  onToggle,
  selectedId,
  canWrite,
}: {
  spaceId: string;
  /** The whole space's rows (unfiltered) — what "Move to…" picks a parent from. */
  rows: PageTreeRow[];
  node: TreeNode<PageTreeRow>;
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
  const [moving, setMoving] = useState(false);
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
          {...pageLink(spaceSlug, row.path)}
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
          <span className="flex items-center opacity-0 transition-opacity focus-within:opacity-100 group-hover/docrow:opacity-100">
            <NewPageButton spaceId={spaceId} spaceSlug={spaceSlug} parentId={row.id} depth={depth} iconOnly />
            <DropdownMenu
              label={`Actions for ${row.title}`}
              align="end"
              widthClass="w-40"
              items={[
                { kind: "action", label: "Move to…", icon: CornerLeftUp, onSelect: () => setMoving(true) },
              ]}
              trigger={({ ref, toggle, open }) => (
                <button
                  ref={ref}
                  type="button"
                  onClick={toggle}
                  aria-label={`Actions for ${row.title}`}
                  aria-expanded={open}
                  className="rounded p-0.5 text-fg-faint hover:bg-strong hover:text-fg cursor-pointer"
                >
                  <MoreHorizontal size={12} aria-hidden />
                </button>
              )}
            />
          </span>
        )}
      </div>
      {moving && <MovePageModal page={row} rows={rows} onClose={() => setMoving(false)} />}
      {isOpen &&
        children.map((child) => (
          <TreeRow
            key={child.row.id}
            spaceId={spaceId}
            spaceSlug={spaceSlug}
            rows={rows}
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
