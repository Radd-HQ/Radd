import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { shortDate } from "../lib/dates";
import { useIsAuthenticated } from "../lib/hooks";
import { currentLeaveQuery } from "../lib/queries/leave";
import type { CurrentLeave } from "../lib/types";

/** The one on-leave lookup every indicator shares (Avatar, PersonName). */
export function useOnLeave(userId: string | undefined): CurrentLeave | undefined {
  // Spec 121: leave is a signed-in fact; a visitor's avatars carry no dot.
  const leave = useQuery({ ...currentLeaveQuery, enabled: useIsAuthenticated() });
  return userId ? leave.data?.find((entry) => entry.user_id === userId) : undefined;
}

/** Away-today ids, for STRING-labeled pickers (TokenMultiSelect chips filter
 * on plain text, so those suffix "🌴" instead of rendering the icon node). */
export function useOnLeaveIds(): Set<string> {
  const leave = useQuery({ ...currentLeaveQuery, enabled: useIsAuthenticated() });
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
/** The quiet "service" chip an automation identity carries in every picker and
 * byline (RADD-869) — the rendering half of `UserDirectoryEntry.source`. */
function ServiceChip() {
  return (
    <span
      aria-label="Service account"
      className="shrink-0 rounded bg-elevated px-1 py-px text-[10px] font-medium leading-3 text-fg-muted"
    >
      service
    </span>
  );
}

export function PersonName({
  user,
  className = "",
}: {
  user: { id: string; name: string; source?: string };
  className?: string;
}) {
  const onLeave = useOnLeave(user.id);
  const isService = user.source === "service";
  if (!onLeave && !isService) return <span className={className}>{user.name}</span>;
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className}`}
      title={onLeave ? leaveTitle(user.name, onLeave) : undefined}
    >
      {user.name}
      {isService && <ServiceChip />}
      {onLeave && <AwayChip />}
    </span>
  );
}
