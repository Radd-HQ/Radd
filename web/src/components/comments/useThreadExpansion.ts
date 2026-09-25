import { useEffect, useState } from "react";
import type { Comment } from "../../lib/types";

/** Manual choices survive query refreshes, but resolution changes get the new default. */
export function useThreadExpansion(linkedRoot?: string) {
  const [choices, setChoices] = useState<Record<string, { open: boolean; resolved: boolean }>>({});
  const [revealed, setRevealed] = useState<string>();
  useEffect(() => { setRevealed(linkedRoot); }, [linkedRoot]);
  const isOpen = (row: Comment) => {
    if (revealed === row.id) return true;
    const choice = choices[row.id];
    return choice && choice.resolved === !!row.resolved_at
      ? choice.open : !!row.is_thread && !row.resolved_at;
  };
  const toggle = (row: Comment) => {
    const open = !isOpen(row);
    setRevealed(undefined);
    setChoices(previous => ({ ...previous, [row.id]: { open, resolved: !!row.resolved_at } }));
  };
  return { isOpen, toggle };
}
