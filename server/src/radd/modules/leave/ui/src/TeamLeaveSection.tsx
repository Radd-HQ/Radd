import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, isoDaysAgo, ErrorText, Select, Spinner, tokens, useCurrentUser, useIsInstanceAdmin } from "@radd/plugin-sdk";
import { readerZone } from "./format";
import { PeriodForm } from "./PeriodForm";
import { PeriodList } from "./PeriodList";
import { LEAVE_QUERY, TEAM_LEAVE_LOOKBACK_DAYS, type TeamLeave, type TeamRef } from "./types";

/** A steward's view of their team's absences (RADD-1481): the teams they own or manage,
 *  one team's members and recorded leave, and the same form aimed at a member. The server
 *  already allowed the write (`may_manage_user`); this is the surface that reaches it. Rendered
 *  only for someone `/auth/me` says manages a team, or an admin — nobody else pays a request. */
export function TeamLeaveSection() {
  const user = useCurrentUser();
  const isAdmin = useIsInstanceAdmin();
  const eligible = Boolean(user && (user.manages_teams || isAdmin));
  const teams = useQuery({
    queryKey: [LEAVE_QUERY, "stewarded"],
    queryFn: ({ signal }) => api.get<TeamRef[]>("/leave/teams", { signal }),
    enabled: eligible,
  });
  const [teamId, setTeamId] = useState("");
  const chosen = teams.data?.find(team => team.id === teamId) ? teamId : teams.data?.[0]?.id ?? "";
  if (!eligible || (teams.isSuccess && teams.data.length === 0)) return null;
  return (
    <section aria-label="Team leave" style={{ marginTop: 32, paddingTop: 24, borderTop: `1px solid ${tokens.border}` }}>
      <h2 style={{ margin: "0 0 4px", fontSize: 14, fontWeight: 600, color: tokens.heading }}>Team leave</h2>
      <p style={{ margin: "0 0 16px", fontSize: 12, color: tokens.textMuted }}>
        Record leave for the people on the teams you own or manage. It appears under their own profile and beside their name everywhere, exactly as if they had recorded it.
      </p>
      {teams.isPending ? <Spinner /> : teams.isError ? <ErrorText error={teams.error} /> : <>
        {teams.data.length > 1 && <Select label="Team" value={chosen} onChange={event => setTeamId(event.target.value)} style={{ marginBottom: 12 }}>
          {teams.data.map(team => <option key={team.id} value={team.id}>{team.name}</option>)}
        </Select>}
        {chosen && <TeamLeave teamId={chosen} />}
      </>}
    </section>
  );
}

function TeamLeave({ teamId }: { teamId: string }) {
  const since = isoDaysAgo(TEAM_LEAVE_LOOKBACK_DAYS);
  const team = useQuery({
    queryKey: [LEAVE_QUERY, "team", teamId, since],
    queryFn: ({ signal }) => api.get<TeamLeave>(`/leave/teams/${teamId}`, { signal, query: { since } }),
  });
  const [memberId, setMemberId] = useState("");
  useEffect(() => { setMemberId(""); }, [teamId]);
  if (team.isPending) return <Spinner />;
  if (team.isError) return <ErrorText error={team.error} />;
  const member = team.data.members.find(m => m.id === memberId);
  return <>
    <PeriodList periods={team.data.periods} readonly={false} empty={`Nobody on ${team.data.team_name} has leave recorded since ${since}.`} subject="user" />
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "end", gap: 12 }}>
      <Select label="Member" value={memberId} onChange={event => setMemberId(event.target.value)}>
        <option value="">Select member…</option>
        {team.data.members.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
      </Select>
      <PeriodForm key={memberId} kind="leave" subject={{ user_id: memberId }} timezone={member?.timezone || readerZone()} disabled={memberId === ""} />
    </div>
  </>;
}
