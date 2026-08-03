import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Inbox, Users } from "lucide-react";
import { errorMessage } from "../../lib/api";
import { portalRequestsQuery } from "../../lib/queries";
import type { PortalRequest } from "../../lib/types";
import { usePeek } from "../../lib/hooks";
import { ListSection } from "./ListSection";
import { RequestRow } from "./RequestRow";

/**
 * The grouped request list, shared by `/portal` and My Work (RADD-799).
 *
 * Hussein's note was that My Work read as messy while Portal's grouped sections
 * read well, so this is Portal's shape extracted rather than a third design. One
 * component means a fix to either page is a fix to both — the two drifted apart
 * precisely because they each drew this themselves.
 *
 * Grouping is MINE first, then one section per team (RADD-798). A team section
 * only exists once something has been shared with it, so the page does not grow
 * a row of empty headings for every team someone happens to belong to.
 */
export function MyRequests({ compact = false }: { compact?: boolean }) {
  const requests = useQuery(portalRequestsQuery);
  // The app's ONE way to open a row (RADD-803): `?peek=<key>`, the same drawer
  // an issue opens in. The first version used a modal, which was a new
  // interaction pattern nobody asked for.
  const { open } = usePeek();

  const groups = useMemo(() => split(requests.data ?? []), [requests.data]);

  if (requests.isPending) return null;
  if (requests.isError) {
    return <p className="text-sm text-red-400">{errorMessage(requests.error)}</p>;
  }
  if (!groups.length) return null;

  return (
    <div className="flex flex-col gap-5">
      {groups.map((group) => (
        <Section
          key={group.label}
          label={group.label}
          icon={group.mine ? Inbox : Users}
          rows={group.rows}
          compact={compact}
          onOpen={open}
        />
      ))}
    </div>
  );
}

interface Group {
  label: string;
  mine: boolean;
  rows: PortalRequest[];
}

/** Mine, then a section per team — teams sorted by name so the page is stable. */
function split(rows: PortalRequest[]): Group[] {
  const mine: PortalRequest[] = [];
  const byTeam = new Map<string, Group>();
  for (const row of rows) {
    if (!row.team_id || !row.team) {
      mine.push(row);
      continue;
    }
    const group = byTeam.get(row.team_id) ?? { label: row.team, mine: false, rows: [] };
    group.rows.push(row);
    byTeam.set(row.team_id, group);
  }
  return [
    ...(mine.length ? [{ label: "My requests", mine: true, rows: mine }] : []),
    ...[...byTeam.values()].sort((a, b) => a.label.localeCompare(b.label)),
  ];
}

const COMPACT_ROWS = 5;

function Section({
  label,
  icon: Icon,
  rows,
  compact,
  onOpen,
}: {
  label: string;
  icon: typeof Inbox;
  rows: PortalRequest[];
  compact: boolean;
  onOpen: (key: string) => void;
}) {
  // Anything waiting on the reader comes first, whatever its date: the reason to
  // open this list is that somebody asked you something.
  const ordered = [...rows].sort(
    (a, b) => Number(b.awaiting_requester) - Number(a.awaiting_requester),
  );
  const shown = compact ? ordered.slice(0, COMPACT_ROWS) : ordered;
  const waiting = rows.filter((r) => r.awaiting_requester).length;

  return (
    <div className="flex flex-col gap-2">
      <ListSection icon={Icon} title={label} count={shown.length} badge={waiting || undefined}>
        {shown.map((request) => (
          <RequestRow key={request.key} request={request} onOpen={onOpen} />
        ))}
      </ListSection>
      {compact && ordered.length > COMPACT_ROWS && (
        <p className="text-[11px] text-fg-faint">
          Showing {COMPACT_ROWS} of {ordered.length} — the Portal has the rest.
        </p>
      )}
    </div>
  );
}
