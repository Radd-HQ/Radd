import { useEffect, useState } from "react";
import type { Comment } from "../../lib/types";

type ThreadRow = Pick<Comment, "id" | "is_thread" | "resolved_at">;

/** RADD-1448: replies show unless the thread is resolved — a resolved one is settled business. */
export function repliesOpenByDefault(row: ThreadRow): boolean {
  return !(row.is_thread && row.resolved_at);
}

/** Manual choices survive query refreshes, but resolution changes get the new default. */
export function useThreadExpansion(linkedRoot?: string) {
  const [choices, setChoices] = useState<Record<string, { open: boolean; resolved: boolean }>>({});
  const [revealed, setRevealed] = useState<string>();
  useEffect(() => { setRevealed(linkedRoot); }, [linkedRoot]);
  const isOpen = (row: ThreadRow) => {
    if (revealed === row.id) return true;
    const choice = choices[row.id];
    return choice && choice.resolved === !!row.resolved_at ? choice.open : repliesOpenByDefault(row);
  };
  const toggle = (row: ThreadRow) => {
    const open = !isOpen(row);
    // Only this row's own reveal gives way; a linked thread stays open while others toggle.
    if (revealed === row.id) setRevealed(undefined);
    setChoices(previous => ({ ...previous, [row.id]: { open, resolved: !!row.resolved_at } }));
  };
  return { isOpen, toggle };
}
