import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, todayIso, Button, ErrorText, Switch, TextField } from "@radd/plugin-sdk";
import { invalidateLeave, type Kind, type Period } from "./types";

interface Props {
  kind: Kind;
  /** The subject fields the POST carries: `{}` for the reader's own leave, `{ user_id }`, `{ team_id }`. */
  subject: Record<string, string>;
  /** The zone the dates and times are read in (RADD-1481); sent with every row. */
  timezone: string;
  disabled?: boolean;
}

/** One form for every kind of period. A holiday is a whole day, so only leave offers times:
 *  the All day switch is on by default; off, a time beside each date narrows that end, and an
 *  empty time keeps the whole day at that end — which is how "Monday 16:00 until Wednesday" reads. */
export function PeriodForm({ kind, subject, timezone, disabled = false }: Props) {
  const client = useQueryClient();
  const holiday = kind === "holiday";
  const [label, setLabel] = useState("");
  const [startDate, setStartDate] = useState(() => todayIso());
  const [endDate, setEndDate] = useState(() => todayIso());
  const [allDay, setAllDay] = useState(true);
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const timed = !holiday && !allDay;
  const save = useMutation({
    mutationFn: () => api.post<Period>("/leave", {
      label: label.trim(), start_date: startDate, end_date: endDate, timezone, ...subject,
      ...(timed ? { start_time: startTime || null, end_time: endTime || null } : {}),
    }),
    onSuccess: () => { void invalidateLeave(client); setLabel(""); },
  });
  const ordered = startDate < endDate || (startDate === endDate && (!timed || !startTime || !endTime || startTime < endTime));
  const canSave = !disabled && startDate !== "" && endDate !== "" && ordered;
  const submit = (event: FormEvent) => { event.preventDefault(); if (canSave && !save.isPending) save.mutate(); };
  const toggleAllDay = (next: boolean) => { setAllDay(next); if (next) { setStartTime(""); setEndTime(""); } };
  return <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }} aria-label={holiday ? "Add holiday" : "Add leave"}>
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "end", gap: 12 }}>
      <TextField label={holiday ? "Holiday name" : "Label (optional)"} value={label} onChange={event => setLabel(event.target.value)} placeholder={holiday ? "Bastille Day" : "Summer vacation"} maxLength={200} style={{ width: 192 }} />
      <TextField label="From" type="date" value={startDate} onChange={event => setStartDate(event.target.value)} />
      {timed && <TextField label="From time" type="time" value={startTime} onChange={event => setStartTime(event.target.value)} />}
      <TextField label="To" type="date" value={endDate} onChange={event => setEndDate(event.target.value)} />
      {timed && <TextField label="To time" type="time" value={endTime} onChange={event => setEndTime(event.target.value)} />}
      {!holiday && <Switch label="All day" checked={allDay} onChange={toggleAllDay} className="h-8" data-testid="leave-all-day" />}
      <Button type="submit" disabled={!canSave || save.isPending}>{save.isPending ? "Adding…" : holiday ? "Add holiday" : "Add leave"}</Button>
    </div>
    {timed && <p className="text-xs text-fg-muted" style={{ margin: 0 }}>Times are in {timezone}. Leave a time empty to cover the whole day at that end.</p>}
    {!ordered && <ErrorText error="The leave must end after it starts." />}
    <ErrorText error={save.error} />
  </form>;
}
