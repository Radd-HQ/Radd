import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api, ErrorText, IconButton, tokens } from "@radd/plugin-sdk";
import { spanText, zoneNote } from "./format";
import { invalidateLeave, type Period } from "./types";

interface Props {
  periods: Period[];
  readonly: boolean;
  empty: string;
  /** Which subject each row names beside its span: the team (holidays) or the person (a team's leave). */
  subject?: "team" | "user";
}

export function PeriodList({ periods, readonly, empty, subject }: Props) {
  const client = useQueryClient();
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/leave/${id}`),
    onSuccess: () => invalidateLeave(client),
  });
  return <>
    {periods.length === 0 ? <p style={{ marginBottom: 12, fontSize: 13, color: tokens.textFaint }}>{empty}</p> :
      <ul style={{ margin: "0 0 12px", padding: 0, listStyle: "none" }}>
        {periods.map(period => {
          const name = subject === "team" ? period.team_name : subject === "user" ? period.user_name : null;
          const zone = zoneNote(period);
          return <li key={period.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "6px 0", fontSize: 13, borderBottom: `1px solid ${tokens.border}` }}>
            {name && <span style={{ fontWeight: 500, color: tokens.heading }}>{name}</span>}
            <span>{spanText(period)}</span>
            {zone && <span style={{ color: tokens.textFaint, fontSize: 12 }} title="The zone these times are read in">{zone}</span>}
            <span style={{ color: tokens.textMuted }}>{period.label}</span>
            {!readonly && <IconButton danger className="ml-auto" disabled={remove.isPending} onClick={() => remove.mutate(period.id)} aria-label={`Remove ${spanText(period)}`}><X size={13} aria-hidden /></IconButton>}
          </li>;
        })}
      </ul>}
    <ErrorText error={remove.error} />
  </>;
}
