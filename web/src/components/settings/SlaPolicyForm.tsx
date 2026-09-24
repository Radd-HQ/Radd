import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Save } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiSlaPolicyPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { PRIORITY_META, PRIORITY_ORDER } from "../../lib/meta";
import { issueTypesQuery, statesQuery } from "../../lib/queries";
import { parseClockMinutes } from "../../lib/duration";
import { SlaMetOn, type PriorityValue, type SlaPolicy } from "../../lib/types";
import { SlaMetOnField, metRuleValid, type MetRule } from "./SlaMetOnField";
import { TeamAudience } from "../teams/TeamAudience";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { TokenMultiSelect } from "../TokenMultiSelect";

export function minutesLabel(minutes: number | null): string {
  if (minutes === null) return "—";
  if (minutes % (24 * 60) === 0) return `${minutes / (24 * 60)}d`;
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

/** "09:00–17:30" for a policy's business window; null when it has none. */
export function windowLabel(startMinute: number | null, endMinute: number | null): string | null {
  if (startMinute === null || endMinute === null) return null;
  const hhmm = (minutes: number) =>
    `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  return `${hhmm(startMinute)}–${hhmm(endMinute)}`;
}

/** Minutes → the text the duration fields take ("1h", "90m", "2d"); null → "". */
function durationText(minutes: number | null): string {
  return minutes === null ? "" : minutesLabel(minutes);
}

/** Minutes from midnight → "HH:MM" for an <input type="time">; null → "". */
function minutesToTime(minutes: number | null): string {
  if (minutes === null) return "";
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

/** "HH:MM" (from an <input type="time">) → minutes from midnight; "" → null. */
function timeToMinutes(value: string): number | null {
  if (!value) return null;
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

const timeInputClasses =
  "h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading " +
  "focus:outline-2 focus:outline-offset-1 focus:outline-focus [color-scheme:dark]";

/** Create AND edit form for an SLA policy (specs 30/63, RADD-1300): targets +
 * "met when" rules + pause states + priority / issue-type / reporter-team
 * filters + daily business-hours window. ONE form for both, seeded from
 * `policy` when editing — two forms over one resource is how they drift.
 * The policy's project comes from the page URL (spec 67: policies are
 * project-level — no scope picker), which is also what scopes the issue types
 * and states offered. */
export function SlaPolicyForm({
  projectId,
  nextPosition,
  policy,
  onDone,
}: {
  projectId: string;
  /** Appended at the bottom of the first-match order (create only). */
  nextPosition: number;
  /** Present = edit this policy (PATCH, same id and position). */
  policy?: SlaPolicy;
  /** Called after a successful save or on Cancel (edit only). */
  onDone?: () => void;
}) {
  const queryClient = useQueryClient();
  const editing = Boolean(policy);
  const [name, setName] = useState(policy?.name ?? "");
  const [responseMinutes, setResponseMinutes] = useState(policy ? durationText(policy.response_minutes) : "1h");
  const [resolutionMinutes, setResolutionMinutes] = useState(durationText(policy?.resolution_minutes ?? null));
  const [warningMinutes, setWarningMinutes] = useState(durationText(policy?.warning_minutes ?? null));
  // RADD-1286: picked from the project's states, never typed. Stored by NAME,
  // which is how SLA policies have always resolved them.
  const [pauseStates, setPauseStates] = useState<string[]>(policy?.pause_state_names ?? []);
  const [workWeekOnly, setWorkWeekOnly] = useState(policy?.work_week_only ?? false);
  const [priorities, setPriorities] = useState<PriorityValue[]>(policy?.priorities ?? []);
  const [issueTypeIds, setIssueTypeIds] = useState<string[]>(policy?.issue_type_ids ?? []);
  const [windowStart, setWindowStart] = useState(minutesToTime(policy?.business_start_minute ?? null));
  const [windowEnd, setWindowEnd] = useState(minutesToTime(policy?.business_end_minute ?? null));
  // RADD-1299: what satisfies each target, and the reporter-team filter.
  const [responseRule, setResponseRule] = useState<MetRule>({
    metOn: policy?.response_met_on ?? SlaMetOn.firstReply,
    stateIds: policy?.response_state_ids ?? [],
    teamIds: policy?.response_team_ids ?? [],
  });
  const [resolutionRule, setResolutionRule] = useState<MetRule>({
    metOn: policy?.resolution_met_on ?? SlaMetOn.done,
    stateIds: policy?.resolution_state_ids ?? [],
    teamIds: policy?.resolution_team_ids ?? [],
  });
  const [reporterTeamIds, setReporterTeamIds] = useState<string[]>(policy?.reporter_team_ids ?? []);

  const togglePriority = (priority: PriorityValue) =>
    setPriorities((current) =>
      current.includes(priority)
        ? current.filter((entry) => entry !== priority)
        : [...current, priority],
    );

  // The same issue-type query every other project surface uses (one cache
  // entry, one staleTime) — a filter over types must not disagree with the
  // pickers that assign them.
  const issueTypes = useQuery(issueTypesQuery(projectId));
  const states = useQuery(statesQuery(projectId));
  const typeOptions = useMemo(
    () => (issueTypes.data ?? []).map((type) => ({ value: type.id, label: type.name })),
    [issueTypes.data],
  );

  // Every field, every time: a field cleared in the form (the warning, the
  // business window) must be cleared on the server, not left as it was.
  const body = () => ({
    name: name.trim(),
    response_minutes: parseClockMinutes(responseMinutes),
    resolution_minutes: parseClockMinutes(resolutionMinutes),
    warning_minutes: parseClockMinutes(warningMinutes),
    pause_state_names: pauseStates,
    work_week_only: workWeekOnly,
    priorities,
    issue_type_ids: issueTypeIds,
    business_start_minute: timeToMinutes(windowStart),
    business_end_minute: timeToMinutes(windowEnd),
    reporter_team_ids: reporterTeamIds,
    response_met_on: responseRule.metOn,
    response_state_ids: responseRule.stateIds,
    response_team_ids: responseRule.teamIds,
    resolution_met_on: resolutionRule.metOn,
    resolution_state_ids: resolutionRule.stateIds,
    resolution_team_ids: resolutionRule.teamIds,
  });
  const create = useMutation({
    mutationFn: () =>
      policy
        ? api.patch<SlaPolicy>(apiSlaPolicyPath(policy.id), body())
        : api.post<SlaPolicy>(ApiPath.slaPolicies, { project_id: projectId, position: nextPosition, ...body() }),
    onSuccess: () => {
      if (policy) {
        onDone?.();
        return;
      }
      setName("");
      setPauseStates([]);
      setPriorities([]);
      setIssueTypeIds([]);
      setWindowStart("");
      setWindowEnd("");
      setWarningMinutes("");
      setResponseRule({ metOn: SlaMetOn.firstReply, stateIds: [], teamIds: [] });
      setResolutionRule({ metOn: SlaMetOn.done, stateIds: [], teamIds: [] });
      setReporterTeamIds([]);
    },
    onSettled: () => invalidateEntities(queryClient, Entity.slaPolicy),
  });

  // Business hours: both-or-neither, start strictly before end (409 server-side).
  const windowInvalid =
    Boolean(windowStart) !== Boolean(windowEnd) ||
    (Boolean(windowStart) && Boolean(windowEnd) && windowStart >= windowEnd);
  // RADD-1288: durations take units ("1h 30m"); a bare number is minutes.
  const parsed = [responseMinutes, resolutionMinutes, warningMinutes].map(parseClockMinutes);
  const badDuration = parsed.some((minutes) => Number.isNaN(minutes));
  const durationHint = (text: string, fallback?: string) => {
    const minutes = parseClockMinutes(text);
    if (minutes === null) return fallback;
    return Number.isNaN(minutes) ? "Use minutes or units, e.g. 90, 1h 30m, 8h, 2d." : `= ${minutesLabel(minutes)}`;
  };
  // A rule only matters for a target that is set; an incomplete one blocks save.
  const rulesValid =
    (!responseMinutes || metRuleValid(responseRule)) && (!resolutionMinutes || metRuleValid(resolutionRule));
  const valid = name.trim() && (responseMinutes || resolutionMinutes) && !windowInvalid && !badDuration && rulesValid;
  const stateOptions = (states.data ?? []).map((state) => ({ id: state.id, name: state.name }));

  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        if (valid) create.mutate();
      }}
      className={"grid grid-cols-2 gap-3 rounded-lg border border-subtle p-4 " + (editing ? "bg-surface" : "mt-4")}
      data-sla-policy-form={editing ? "edit" : "create"}
    >
      <div className="col-span-2">
        <TextField
          label="Policy name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="TD standard"
          maxLength={200}
        />
      </div>
      <TextField
        label="Response target"
        value={responseMinutes}
        onChange={(event) => setResponseMinutes(event.target.value)}
        placeholder="1h"
        hint={durationHint(responseMinutes)}
        data-duration="response"
      />
      <TextField
        label="Resolution target"
        value={resolutionMinutes}
        onChange={(event) => setResolutionMinutes(event.target.value)}
        placeholder="8h"
        hint={durationHint(resolutionMinutes)}
        data-duration="resolution"
      />
      {/* RADD-1299: what satisfies each target — shown for the targets that are set. */}
      <div>
        {responseMinutes && (
          <SlaMetOnField target="response" rule={responseRule} onChange={setResponseRule} states={stateOptions} />
        )}
      </div>
      <div>
        {resolutionMinutes && (
          <SlaMetOnField target="resolution" rule={resolutionRule} onChange={setResolutionRule} states={stateOptions} />
        )}
      </div>
      <div className="col-span-2">
        <TextField
          label="Warn before breach"
          value={warningMinutes}
          onChange={(event) => setWarningMinutes(event.target.value)}
          placeholder="30m"
          hint={durationHint(warningMinutes, "Optional: sends one due-soon alert (and fires the SLA due soon automation trigger) when this much time is left.")}
        />
      </div>
      <div className="col-span-2 flex flex-col gap-1.5">
        <span className="text-xs font-medium text-fg-secondary">
          Applies to priorities (none selected = all)
        </span>
        <div className="flex flex-wrap gap-1.5">
          {PRIORITY_ORDER.map((priority) => {
            const selected = priorities.includes(priority);
            return (
              <button
                key={priority}
                type="button"
                onClick={() => togglePriority(priority)}
                aria-pressed={selected}
                className={
                  "rounded-full border px-2.5 py-1 text-xs cursor-pointer transition-colors " +
                  (selected
                    ? "border-accent-hover/60 bg-accent/15 text-accent-text-strong"
                    : "border-strong text-fg-secondary hover:border-emphasis hover:text-fg")
                }
              >
                {PRIORITY_META[priority].label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="col-span-2 flex flex-col gap-1.5">
        <span className="text-xs font-medium text-fg-secondary">
          Applies to issue types (none selected = all)
        </span>
        <TokenMultiSelect
          value={issueTypeIds}
          onChange={setIssueTypeIds}
          options={typeOptions}
          placeholder={typeOptions.length === 0 ? "No issue types in this project" : "Add a type…"}
          disabled={typeOptions.length === 0}
          ariaLabel="Applies to issue types"
        />
      </div>
      <div className="col-span-2 flex flex-col gap-1.5" data-reporter-teams>
        <span className="text-xs font-medium text-fg-secondary">Applies when the reporter is in these teams</span>
        <TeamAudience
          value={reporterTeamIds}
          onChange={setReporterTeamIds}
          emptyText="Any reporter."
          hint="Membership is read live, including members through linked directory groups."
          addLabel="Add reporter team"
        />
      </div>
      <div className="col-span-2 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1.5 text-xs font-medium text-fg-secondary">
          Business hours from
          <input
            type="time"
            value={windowStart}
            onChange={(event) => setWindowStart(event.target.value)}
            className={timeInputClasses}
            aria-label="Business hours start"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-xs font-medium text-fg-secondary">
          to
          <input
            type="time"
            value={windowEnd}
            onChange={(event) => setWindowEnd(event.target.value)}
            className={timeInputClasses}
            aria-label="Business hours end"
          />
        </label>
        <span className={"pb-2 text-[11px] " + (windowInvalid ? "text-red-400" : "text-fg-faint")}>
          {windowInvalid
            ? "Set both times, start before end."
            : "Optional: the clock only runs inside this daily window (leave empty for 24h)."}
        </span>
      </div>
      <div className="col-span-2">
        <span className="mb-1 block text-xs font-medium text-fg-secondary">Pause the clock in these states</span>
        <TokenMultiSelect
          value={pauseStates}
          onChange={setPauseStates}
          options={(states.data ?? []).map((state) => ({ value: state.name, label: state.name }))}
          placeholder="Add a state…"
          ariaLabel="Pause the clock in these states"
        />
      </div>
      <label className="col-span-2 flex items-center gap-2 text-xs text-fg-secondary">
        <input
          type="checkbox"
          checked={workWeekOnly}
          onChange={(event) => setWorkWeekOnly(event.target.checked)}
          className="accent-accent"
        />
        Count working days only (weekends pause the clock — instance work week)
      </label>
      <div className="col-span-2 flex items-center gap-2">
        {editing ? (
          <>
            <Button type="submit" disabled={create.isPending || !valid}>
              <Save size={14} aria-hidden />
              {create.isPending ? "Saving…" : "Save changes"}
            </Button>
            <Button variant="ghost" onClick={() => onDone?.()} disabled={create.isPending}>
              Cancel
            </Button>
          </>
        ) : (
          <Button type="submit" disabled={create.isPending || !valid}>
            <Plus size={14} aria-hidden />
            {create.isPending ? "Creating…" : "Create policy"}
          </Button>
        )}
        {create.isError && (
          <span className="text-xs text-red-400">{errorMessage(create.error)}</span>
        )}
      </div>
    </form>
  );
}
