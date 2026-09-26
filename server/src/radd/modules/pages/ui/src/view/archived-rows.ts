import type { PageSummary } from "../types";
import { comparePagesNaturally } from "./PageTree";

/** One archived page as the browser lists it: where it lived, when it went,
 * and what went with it. */
export interface ArchivedRow {
  page: PageSummary;
  /** Ancestor titles, root first — the path it was archived from. */
  path: string[];
  /** Archived ancestors — restoring this page restores them too. */
  archivedAncestors: PageSummary[];
  /** Descendants hidden with it (any state): what comes back on restore. */
  hiddenBelow: number;
}

/** Pure: the `include_archived` listing → the archive browser's rows. A page
 * is listed when IT is archived; a live descendant hidden under an archived
 * ancestor is not a row — it rides along with the ancestor's restore. */
export function archivedRows(rows: PageSummary[]): ArchivedRow[] {
  const byId = new Map(rows.map((row) => [row.id, row]));
  const childrenOf = new Map<string | null, PageSummary[]>();
  for (const row of rows) {
    const siblings = childrenOf.get(row.parent_id) ?? [];
    siblings.push(row);
    childrenOf.set(row.parent_id, siblings);
  }
  const countBelow = (id: string): number => {
    let total = 0;
    const queue = [...(childrenOf.get(id) ?? [])];
    for (let guard = 0; queue.length && guard < rows.length; guard++) {
      const next = queue.shift()!;
      total += 1;
      queue.push(...(childrenOf.get(next.id) ?? []));
    }
    return total;
  };
  const out: ArchivedRow[] = [];
  for (const page of rows) {
    if (!page.archived_at) continue;
    const path: string[] = [];
    const archivedAncestors: PageSummary[] = [];
    let cursor = page.parent_id ? byId.get(page.parent_id) : undefined;
    for (let guard = 0; cursor && guard < rows.length; guard++) {
      path.unshift(cursor.title);
      if (cursor.archived_at) archivedAncestors.unshift(cursor);
      cursor = cursor.parent_id ? byId.get(cursor.parent_id) : undefined;
    }
    out.push({ page, path, archivedAncestors, hiddenBelow: countBelow(page.id) });
  }
  // Most recently archived first — "what did I just lose" is the usual question.
  return out.sort(
    (a, b) =>
      (b.page.archived_at ?? "").localeCompare(a.page.archived_at ?? "") ||
      comparePagesNaturally(a.page, b.page),
  );
}

/** Pure: the rows whose title or path contains every word of the query. */
export function filterArchivedRows(rows: ArchivedRow[], query: string): ArchivedRow[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return rows;
  return rows.filter((row) => {
    const haystack = `${row.page.title} ${row.path.join(" / ")}`.toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}
