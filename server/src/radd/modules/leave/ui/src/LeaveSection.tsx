import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ErrorText, Select, Spinner, tokens, useCurrentUser, useIsInstanceAdmin } from "@radd/plugin-sdk";
import { readerZone } from "./format";
import { PeriodForm } from "./PeriodForm";
import { PeriodList } from "./PeriodList";
import { LEAVE_QUERY, type Kind, type Period, type TeamRef } from "./types";

/** Both settings sections belong to Leave; the host owns only the slot anchors. */
export function LeaveSection({ kind }: { kind: Kind }) {
  const user = useCurrentUser();
  const isAdmin = useIsInstanceAdmin();
  const holiday = kind === "holiday";
  const periods = useQuery({
    queryKey: [LEAVE_QUERY, holiday ? "holidays" : "mine"],
    queryFn: ({ signal }) => api.get<Period[]>(holiday ? "/leave/holidays" : "/leave/mine", { signal }),
  });
  const readonly = holiday && !isAdmin;
  return (
    <section aria-label={holiday ? "Holidays" : "Leave"} style={holiday ? { marginBottom: 32 } : { marginTop: 32, paddingTop: 24, borderTop: `1px solid ${tokens.border}` }}>
      <h2 style={{ margin: "0 0 4px", fontSize: 14, fontWeight: 600, color: tokens.heading }}>{holiday ? "Holidays" : "Leave"}</h2>
      <p style={{ margin: "0 0 16px", fontSize: 12, color: tokens.textMuted }}>
        {holiday
          ? "Per-team public holidays — regional teams differ, which is the point. They mark every current member of the team away on the timesheet and exempt those days from the outlier flags above."
          : "Your absences show on the timesheet and dim your avatar everywhere while you're away. Whole days by default; switch All day off to leave at an hour or come back at one. Team-wide holidays are set under Settings → Time logging."}
      </p>
      {periods.isPending ? <Spinner /> : periods.isError ? <ErrorText error={periods.error} /> : <>
        <PeriodList periods={periods.data} readonly={readonly} empty={holiday ? "No team holidays defined." : "No leave recorded."} subject={holiday ? "team" : undefined} />
        {user && !readonly && (holiday ? <HolidayForm /> : <PeriodForm kind="leave" subject={{}} timezone={readerZone()} />)}
      </>}
    </section>
  );
}

function HolidayForm() {
  const teams = useQuery({ queryKey: [LEAVE_QUERY, "teams"], queryFn: ({ signal }) => api.get<TeamRef[]>("/teams", { signal }) });
  const [teamId, setTeamId] = useState("");
  return <div style={{ display: "flex", flexWrap: "wrap", alignItems: "end", gap: 12 }}>
    <Select label="Team" value={teamId} onChange={event => setTeamId(event.target.value)}>
      <option value="">Select team…</option>
      {(teams.data ?? []).map(team => <option key={team.id} value={team.id}>{team.name}</option>)}
    </Select>
    <PeriodForm kind="holiday" subject={{ team_id: teamId }} timezone={readerZone()} disabled={teamId === ""} />
    <ErrorText error={teams.error} />
  </div>;
}
