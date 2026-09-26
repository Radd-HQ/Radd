import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { Button, DirectoryPager, QueryError } from "@radd/plugin-sdk";
import { teamReferencesQuery, TEAM_REFERENCE_PAGE_SIZE as TEAMS_PAGE_SIZE } from "./references";
import { TeamChoices } from "./RelationshipSelect";
import type { TeamAudienceProps } from "./relationship-contract";

/** Complete audience IDs stay in the draft; only one window of labels/counts mounts.
 * Each consuming feature supplies its own audience semantics. */
export function TeamAudience({ value, onChange, emptyText = "No teams selected.", hint, addLabel = "Add audience team" }: TeamAudienceProps) {
  const [page, setPage] = useState(0);
  const [choosing, setChoosing] = useState(false);
  const ids = value.slice(page * TEAMS_PAGE_SIZE, (page + 1) * TEAMS_PAGE_SIZE);
  const definition = teamReferencesQuery(ids, Boolean(onChange));
  const references = useQuery({ ...definition, staleTime: 30_000 });
  const names = new Map(references.data?.map(row => [row.id, row]));
  useEffect(() => {
    if (page > 0 && page * TEAMS_PAGE_SIZE >= value.length) setPage(Math.max(0, Math.ceil(value.length / TEAMS_PAGE_SIZE) - 1));
  }, [page, value.length]);
  return <div className="w-full min-w-0 space-y-2">
    {value.length === 0 ? <p className="text-[11px] text-fg-muted">{emptyText}</p> : <>
      <p className="text-xs text-fg-secondary">{value.length} selected team{value.length === 1 ? "" : "s"}</p>
      <ul aria-label="Selected audience teams" className="flex max-h-40 flex-wrap gap-1 overflow-y-auto">{ids.map(id => {
        const team = names.get(id);
        return <li key={id} className="flex min-w-0 items-center gap-1 rounded border border-subtle px-2 text-xs">
          <span className="min-w-0 break-words [overflow-wrap:anywhere]">{team?.name ?? (references.isPending ? "Loading team…" : "Unavailable team")}
            {team?.member_count != null && ` (${team.member_count} member${team.member_count === 1 ? "" : "s"})`}</span>
          {onChange && <Button size="sm" variant="ghost" aria-label={`Remove audience team ${team?.name ?? id}`} onClick={() => onChange(value.filter(current => current !== id))}><X size={12} aria-hidden /></Button>}
        </li>;
      })}</ul>
      <DirectoryPager page={page} pageSize={TEAMS_PAGE_SIZE} total={value.length} busy={references.isFetching} onPage={setPage} label="audience teams" />
      {hint && <p className="text-[11px] text-fg-muted">{hint}</p>}
    </>}
    {references.isError && <div><QueryError label="audience teams" error={references.error} /><Button variant="ghost" size="sm" onClick={() => void references.refetch()}>Retry audience teams</Button></div>}
    {onChange && <Button variant="secondary" size="sm" aria-haspopup="dialog" onClick={() => setChoosing(true)}>{addLabel}</Button>}
    {choosing && <AudienceChoices value={value} onClose={() => setChoosing(false)} onApply={ids => { onChange?.(ids); setChoosing(false); }} />}
  </div>;
}

/** Stage additions across search pages, then hydrate the chosen audience once. */
function AudienceChoices({ value, onApply, onClose }: { value: string[]; onApply: (ids: string[]) => void; onClose: () => void }) {
  const [selected, setSelected] = useState(value);
  return <TeamChoices selected={selected} onClose={onClose} onSelect={id => setSelected(current => [...new Set([...current, id])])}
    footer={<div className="mt-3 flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-fg-secondary" role="status">{selected.length} selected teams</p>
      <Button onClick={() => onApply(selected)}>Apply teams</Button>
    </div>} />;
}

