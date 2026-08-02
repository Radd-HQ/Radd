import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { shortDate } from "../lib/dates";
import { currentLeaveQuery } from "../lib/queries/leave";
import type { CurrentLeave } from "../lib/types";

/** The one on-leave lookup every indicator shares (Avatar, PersonName). */
export function useOnLeave(userId: string | undefined): CurrentLeave | undefined {
  const leave = useQuery(currentLeaveQuery);
  return userId ? leave.data?.find((entry) => entry.user_id === userId) : undefined;
}

/** Away-today ids, for STRING-labeled pickers (TokenMultiSelect chips filter
 * on plain text, so those suffix "🌴" instead of rendering the icon node). */
export function useOnLeaveIds(): Set<string> {
  const leave = useQuery(currentLeaveQuery);
  return useMemo(() => new Set((leave.data ?? []).map((entry) => entry.user_id)), [leave.data]);
}

export function leaveTitle(name: string, onLeave: CurrentLeave): string {
  return (
    `${name} — on leave until ${shortDate(onLeave.until)}` +
    (onLeave.label ? ` (${onLeave.label})` : "")
  );
}

/** The "away" chip a name carries while its person is on leave — words, not
 * pictograms: icons smear at these sizes, "away" reads instantly. */
export function AwayChip() {
  return (
    <span
      aria-label="On leave"
      className="shrink-0 rounded bg-amber-400/15 px-1 py-px text-[10px] font-medium leading-3 text-amber-300"
    >
      away
    </span>
  );
}

/**
 * A person's name with the on-leave "away" chip ATTACHED to it:
 * the text-rendering counterpart of Avatar's status dot, for select options,
 * comment author lines, menu rows — anywhere a person is named without an
 * avatar. Away today → chip + tooltip; otherwise renders just the name.
 */
export function PersonName({
  user,
  className = "",
}: {
  user: { id: string; name: string };
  className?: string;
}) {
  const onLeave = useOnLeave(user.id);
  if (!onLeave) return <span className={className}>{user.name}</span>;
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className}`}
      title={leaveTitle(user.name, onLeave)}
    >
      {user.name}
      <AwayChip />
    </span>
  );
}
