import { useQuery } from "@tanstack/react-query";
import { groupReachQuery } from "../../lib/queries";

/**
 * The RADD-832 guardrail: before a grant to a directory group is saved, show
 * how many people it resolves to — TRANSITIVELY, from the server's closure,
 * not the picker's direct count. A parent group can reach hundreds through
 * nesting that is invisible in the dropdown; the number is what makes the
 * admin notice before an access review does.
 */
export function GroupReachHint({ groupId }: { groupId: string }) {
  const reach = useQuery(groupReachQuery(groupId));
  if (reach.data == null) return null;
  const n = reach.data.user_count;
  return (
    <span className="text-[11px] text-amber-400">
      resolves to {n} {n === 1 ? "person" : "people"} (nesting included)
    </span>
  );
}
