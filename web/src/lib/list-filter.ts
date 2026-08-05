import { useState } from "react";

/**
 * Client-side list filtering for settings-scale lists (RADD-882) — the cycles
 * page's pattern, extracted. Correct wherever the page already fetches the
 * full list (a few thousand rows filter in well under a frame); a list whose
 * FETCH is the problem needs the server-backed `q` instead (RADD-883).
 *
 * `keys` must be pure — it runs per row per keystroke.
 */
export function useListFilter<T>(rows: T[], keys: (row: T) => (string | null | undefined)[]) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const filtered = needle
    ? rows.filter((row) => keys(row).some((key) => key?.toLowerCase().includes(needle)))
    : rows;
  return {
    filter,
    setFilter,
    /** Normalized needle — truthy exactly while a filter is applied. */
    needle,
    filtered,
    /** While filtering, folded sections should OPEN themselves: searching for a
     * row that turns out to live in a collapsed fold should FIND it (the
     * cycles-page rule). OR this into any `open` state. */
    filtering: needle.length > 0,
  };
}
