import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api, invalidatePluginData, shortDate, todayIso, Button, IconButton, Select, Spinner, TextField, tokens, useCurrentUser, useIsInstanceAdmin } from "@radd/plugin-sdk";

type Kind = "leave" | "holiday";
interface Period {
  id: string;
  team_name: string | null;
  label: string;
  start_date: string;
  end_date: string;
}
interface Team { id: string; name: string }

function ErrorText({ error }: { error: unknown }) {
  return <p role="alert" style={{ color: tokens.danger, fontSize: 13 }}>{error instanceof Error ? error.message : "The request failed."}</p>;
}

/** Both settings sections belong to Leave; the host owns only the slot anchors. */
export function LeaveSection({ kind }: { kind: Kind }) {
  const user = useCurrentUser();
  const isAdmin = useIsInstanceAdmin();
  const holiday = kind === "holiday";
  const periods = useQuery({
    queryKey: ["leave", holiday ? "holidays" : "mine"],
    queryFn: ({ signal }) => api.get<Period[]>(holiday ? "/leave/holidays" : "/leave/mine", { signal }),
  });
  const readonly = holiday && !isAdmin;
  return (
    <section aria-label={holiday ? "Holidays" : "Leave"} style={holiday ? { marginBottom: 32 } : { marginTop: 32, paddingTop: 24, borderTop: `1px solid ${tokens.border}` }}>
      <h2 style={{ margin: "0 0 4px", fontSize: 14, fontWeight: 600, color: tokens.heading }}>{holiday ? "Holidays" : "Leave"}</h2>
      <p style={{ margin: "0 0 16px", fontSize: 12, color: tokens.textMuted }}>
        {holiday
          ? "Per-team public holidays — regional teams differ, which is the point. They mark every current member of the team away on the timesheet and exempt those days from the outlier flags above."
          : "Your absences show on the timesheet and dim your avatar everywhere while you're away. Team-wide holidays are set under Settings → Time logging."}
      </p>
      {periods.isPending ? <Spinner /> : periods.isError ? <ErrorText error={periods.error} /> : <>
        <PeriodList periods={periods.data} holiday={holiday} readonly={readonly} />
        {user && !readonly && <AddPeriodForm kind={kind} />}
      </>}
    </section>
  );
}

function PeriodList({ periods, holiday, readonly }: { periods: Period[]; holiday: boolean; readonly: boolean }) {
  const client = useQueryClient();
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/leave/${id}`),
    onSuccess: () => Promise.all([client.invalidateQueries({ queryKey: ["leave"], predicate: (query) => query.queryKey[1] !== "teams" }), invalidatePluginData(client, "leave")]),
  });
  return <>
    {periods.length === 0 ? <p style={{ marginBottom: 12, fontSize: 13, color: tokens.textFaint }}>{holiday ? "No team holidays defined." : "No leave recorded."}</p> :
      <ul style={{ margin: "0 0 12px", padding: 0, listStyle: "none" }}>
        {periods.map(period => <li key={period.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "6px 0", fontSize: 13, borderBottom: `1px solid ${tokens.border}` }}>
          <span>{shortDate(period.start_date)} – {shortDate(period.end_date)}</span>
          {holiday && period.team_name && <span style={{ color: tokens.textMuted }}>{period.team_name}</span>}
          <span style={{ color: tokens.textMuted }}>{period.label}</span>
          {!readonly && <IconButton danger className="ml-auto" disabled={remove.isPending} onClick={() => remove.mutate(period.id)} aria-label={`Remove ${shortDate(period.start_date)} – ${shortDate(period.end_date)}`}><X size={13} aria-hidden /></IconButton>}
        </li>)}
      </ul>}
    {remove.isError && <ErrorText error={remove.error} />}
  </>;
}

function AddPeriodForm({ kind }: { kind: Kind }) {
  const client = useQueryClient();
  const teams = useQuery({ queryKey: ["leave", "teams"], queryFn: ({ signal }) => api.get<Team[]>("/teams", { signal }), enabled: kind === "holiday" });
  const [teamId, setTeamId] = useState("");
  const [label, setLabel] = useState("");
  const [startDate, setStartDate] = useState(() => todayIso());
  const [endDate, setEndDate] = useState(() => todayIso());
  const save = useMutation({
    mutationFn: () => api.post<Period>("/leave", { label: label.trim(), start_date: startDate, end_date: endDate, ...(kind === "holiday" ? { team_id: teamId } : {}) }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["leave"], predicate: (query) => query.queryKey[1] !== "teams" }); void invalidatePluginData(client, "leave"); setLabel(""); },
  });
  const canSave = startDate !== "" && endDate !== "" && endDate >= startDate && (kind !== "holiday" || teamId !== "");
  const submit = (event: FormEvent) => { event.preventDefault(); if (canSave && !save.isPending) save.mutate(); };
  return <form onSubmit={submit} style={{ display: "flex", flexWrap: "wrap", alignItems: "end", gap: 12 }}>
    {kind === "holiday" && <Select label="Team" value={teamId} onChange={event => setTeamId(event.target.value)}>
      <option value="">Select team…</option>
      {(teams.data ?? []).map(team => <option key={team.id} value={team.id}>{team.name}</option>)}
    </Select>}
    <TextField label={kind === "holiday" ? "Holiday name" : "Label (optional)"} value={label} onChange={event => setLabel(event.target.value)} placeholder={kind === "holiday" ? "Bastille Day" : "Summer vacation"} maxLength={200} style={{ width: 192 }} />
    <TextField label="From" type="date" value={startDate} onChange={event => setStartDate(event.target.value)} />
    <TextField label="To" type="date" value={endDate} onChange={event => setEndDate(event.target.value)} />
    <Button type="submit" disabled={!canSave || save.isPending}>{save.isPending ? "Adding…" : kind === "holiday" ? "Add holiday" : "Add leave"}</Button>
    {teams.isError && <ErrorText error={teams.error} />}
    {save.isError && <ErrorText error={save.error} />}
  </form>;
}
