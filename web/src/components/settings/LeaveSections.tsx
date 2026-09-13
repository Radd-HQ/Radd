import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { shortDate, todayIso } from "../../lib/dates";
import { useCurrentUser } from "../../lib/hooks";
import { holidaysQuery, myLeaveQuery, teamsQuery } from "../../lib/queries";
import { InstanceRole, type LeaveCreate, type LeavePeriod } from "../../lib/types";
import { Button } from "../Button";
import { SelectField } from "../SelectField";
import { Spinner } from "../Spinner";
import { TextField } from "../TextField";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";

/**
 * Leave UI, split across its two audiences (settings reorg 2026-08-01):
 * `MyLeaveSection` lives on the Profile page (your absences belong with your
 * account), `TeamHolidaysSection` on Settings → Holidays (People group —
 * admins define per-team public holidays; regional teams differ, the point).
 * Both render bare list+form; the hosting page provides heading + framing.
 */

export function MyLeaveSection() {
  const mine = useQuery(myLeaveQuery);
  if (mine.isPending) return <Spinner />;
  return (
    <>
      <PeriodList periods={mine.data ?? []} emptyText="No leave recorded." />
      <AddPeriodForm kind="leave" />
    </>
  );
}

export function TeamHolidaysSection() {
  const user = useCurrentUser();
  const isAdmin = user?.instance_role === InstanceRole.admin;
  const holidays = useQuery(holidaysQuery);
  if (holidays.isPending) return <Spinner />;
  return (
    <>
      <PeriodList
        periods={holidays.data ?? []}
        emptyText="No team holidays defined."
        showTeam
        readonly={!isAdmin}
      />
      {isAdmin && <AddPeriodForm kind="holiday" />}
    </>
  );
}

function PeriodList({
  periods,
  emptyText,
  showTeam = false,
  readonly = false,
}: {
  periods: LeavePeriod[];
  emptyText: string;
  showTeam?: boolean;
  readonly?: boolean;
}) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${ApiPath.leave}/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["leave"] }),
  });
  if (periods.length === 0) {
    return <p className="mb-3 text-[13px] text-fg-faint">{emptyText}</p>;
  }
  return (
    <ul className="mb-3 divide-y divide-subtle/60">
      {periods.map((period) => (
        <li key={period.id} className="flex items-center gap-3 py-1.5 text-[13px]">
          <span className="tnum text-fg">
            {shortDate(period.start_date)} – {shortDate(period.end_date)}
          </span>
          {showTeam && period.team_name && (
            <span className="rounded bg-elevated px-1.5 py-px text-[11px] text-fg-secondary">
              {period.team_name}
            </span>
          )}
          <span className="min-w-0 truncate text-fg-muted">{period.label}</span>
          {!readonly && (
            <IconButton
              danger
              onClick={() => remove.mutate(period.id)}
              aria-label="Remove"
              title="Remove"
              className="ml-auto"
            >
              <X size={13} />
            </IconButton>
          )}
        </li>
      ))}
    </ul>
  );
}

function AddPeriodForm({ kind }: { kind: "leave" | "holiday" }) {
  const queryClient = useQueryClient();
  const teams = useQuery({ ...teamsQuery(), enabled: kind === "holiday" });
  const [teamId, setTeamId] = useState("");
  const [label, setLabel] = useState("");
  const [startDate, setStartDate] = useState(() => todayIso());
  const [endDate, setEndDate] = useState(() => todayIso());

  const save = useMutation({
    mutationFn: () => {
      const body: LeaveCreate = { label: label.trim(), start_date: startDate, end_date: endDate };
      if (kind === "holiday") body.team_id = teamId;
      return api.post<LeavePeriod>(ApiPath.leave, body);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leave"] });
      setLabel("");
    },
  });

  const canSave =
    startDate !== "" && endDate !== "" && endDate >= startDate && (kind !== "holiday" || teamId !== "");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave && !save.isPending) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      {kind === "holiday" && (
        <SelectField
          label="Team"
          value={teamId}
          onChange={(event) => setTeamId(event.target.value)}
          className="w-44"
        >
          <option value="">Select team…</option>
          {(teams.data ?? []).map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </SelectField>
      )}
      <TextField
        label={kind === "holiday" ? "Holiday name" : "Label (optional)"}
        value={label}
        onChange={(event) => setLabel(event.target.value)}
        placeholder={kind === "holiday" ? "Bastille Day" : "Summer vacation"}
        maxLength={200}
        className="w-48"
      />
      <TextField
        label="From"
        type="date"
        value={startDate}
        onChange={(event) => setStartDate(event.target.value)}
      />
      <TextField
        label="To"
        type="date"
        value={endDate}
        onChange={(event) => setEndDate(event.target.value)}
      />
      <Button type="submit" disabled={!canSave || save.isPending}>
        {save.isPending ? "Adding…" : kind === "holiday" ? "Add holiday" : "Add leave"}
      </Button>
      {save.isError && <ErrorText className="w-full" error={save.error} />}
    </form>
  );
}
