/** Page-tree operations over the flat rows a space listing returns. The rail, `radd:toc`,
 * `radd:children`, the print view, Move to… and the archive browser all walk the tree through
 * these, so none of them can list pages in a different order (RADD-1421). No imports: a unit test
 * loads this file directly. */

/** What a walk needs of a row. */
interface TreeRow {
  id: string;
  parent_id: string | null;
  title: string;
}

export interface TreeNode<R extends TreeRow> {
  row: R;
  children: TreeNode<R>[];
}

/** Siblings order NATURALLY (numeric-aware: 0.2.0 < 0.10.0) everywhere pages are listed (RADD-859). */
export function comparePagesNaturally(a: { title: string }, b: { title: string }): number {
  return a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: "base" });
}

/** Children by parent id (null = top level), each sibling list in natural order. */
function childrenByParent<R extends TreeRow>(rows: R[]): Map<string | null, R[]> {
  const byParent = new Map<string | null, R[]>();
  for (const row of rows) {
    const siblings = byParent.get(row.parent_id) ?? [];
    siblings.push(row);
    byParent.set(row.parent_id, siblings);
  }
  for (const siblings of byParent.values()) siblings.sort(comparePagesNaturally);
  return byParent;
}

/** Flat rows → nested tree in natural order; a row whose parent is not listed is a root. */
export function buildTree<R extends TreeRow>(rows: R[]): TreeNode<R>[] {
  const ids = new Set(rows.map((row) => row.id));
  const byParent = childrenByParent(rows);
  const nodes = (siblings: R[]): TreeNode<R>[] =>
    siblings.map((row) => ({ row, children: nodes(byParent.get(row.id) ?? []) }));
  return nodes(rows.filter((row) => !row.parent_id || !ids.has(row.parent_id)).sort(comparePagesNaturally));
}

/** Everything under `rootId`, depth first in tree order, with its level below the root (0 = a child). */
export function descendants<R extends TreeRow>(
  rows: R[],
  rootId: string | null,
  maxDepth = Infinity,
): { page: R; level: number }[] {
  if (!rootId) return [];
  const byParent = childrenByParent(rows);
  const out: { page: R; level: number }[] = [];
  const seen = new Set<string>([rootId]);
  const walk = (parentId: string, level: number) => {
    if (level >= maxDepth) return;
    for (const page of byParent.get(parentId) ?? []) {
      if (seen.has(page.id)) continue;
      seen.add(page.id);
      out.push({ page, level });
      walk(page.id, level + 1);
    }
  };
  walk(rootId, 0);
  return out;
}

/** `rootId` and every page under it. A cycle is impossible (the server refuses one), but a bad row
 * must not hang the caller, so every walk here is bounded. */
export function subtreeIds(rows: TreeRow[], rootId: string): Set<string> {
  const out = new Set<string>([rootId]);
  for (const { page } of descendants(rows, rootId)) out.add(page.id);
  return out;
}

/** The ids above `id`, nearest first, following `parentOf` (id → parent id) for at most `limit` steps. */
export function ancestorIds(parentOf: Map<string, string | null>, id: string, limit: number): string[] {
  const out: string[] = [];
  let cursor = parentOf.get(id) ?? null;
  for (let guard = 0; cursor && guard < limit; guard++) {
    out.push(cursor);
    cursor = parentOf.get(cursor) ?? null;
  }
  return out;
}
