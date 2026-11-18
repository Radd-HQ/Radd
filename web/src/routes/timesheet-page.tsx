import { useState } from "react";
import { todayIso } from "@radd/plugin-sdk";
import { TeamReport } from "../components/timelog/TeamReport";
import { TimeLogCalendar } from "../components/timelog/TimeLogCalendar";
import { useCurrentUser, usePermissions } from "../lib/hooks";
import { Permission } from "../lib/types";
import { readUrlState, writeUrlState } from "../lib/url-state";
import { TimesheetReport } from "./timesheet";

const Mode = { log: "log", report: "report", team: "team" } as const;
type ModeValue = (typeof Mode)[keyof typeof Mode];

const MODES: { value: ModeValue; label: string }[] = [
  { value: Mode.log, label: "My week" },
  { value: Mode.report, label: "Report" },
];
/** Offered to people who may see others' time: `timesheet.view`, or a team of
 *  their own to lead (RADD-1576). */
const TEAM_MODE = { value: Mode.team, label: "Team" };

/**
 * /timesheet — two surfaces over the same worklogs (RADD-1541).
 *
 * **My week** is for ENTERING time: one person's week as a calendar of cards.
 * **Report** is for READING it: the grid across people, periods and groupings.
 *
 * Which one is open lives in the URL (`m`), so a link or a refresh lands where
 * it was sent. The calendar is the default: logging is the daily act, a report
 * the weekly one.
 *
 * **Team** (RADD-1574) is the manager's question: who logged what against what
 * was expected, and whose logging is not believable. For people who may see
 * others' time: everyone's with `timesheet.view`, their own team's for a
 * team's owner or manager (RADD-1576).
 */
export function TimesheetPage() {
  const url = readUrlState();
  const seesEveryone = usePermissions().global(Permission.timesheetView);
  const canSeeOthers = seesEveryone || Boolean(useCurrentUser()?.manages_teams);
  // A link that carries the report's own state — a grouping, a period, a
  // project, team or person filter, a query — was made on the report and opens
  // it, whether or not it says so: every timesheet link from before the split.
  const reportLink = Boolean(url.g || url.p || url.pr || url.tm || url.u || url.q);
  const [mode, setModeState] = useState<ModeValue>(
    url.m === Mode.team
      ? Mode.team
      : url.m === Mode.report || (!url.m && reportLink)
        ? Mode.report
        : Mode.log,
  );
  const [anchor, setAnchorState] = useState(url.d ?? todayIso());
  const setMode = (value: ModeValue) => {
    setModeState(value);
    writeUrlState({ m: value === Mode.log ? null : value });
  };
  const setAnchor = (value: string) => {
    setAnchorState(value);
    writeUrlState({ d: value });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-subtle px-6 pt-3">
        <div role="tablist" aria-label="Timesheet" className="flex gap-1">
          {(canSeeOthers ? [...MODES, TEAM_MODE] : MODES).map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={mode === option.value}
              data-timesheet-mode={option.value}
              onClick={() => setMode(option.value)}
              className={`-mb-px border-b-2 px-3 pb-2 text-row cursor-pointer ${
                mode === option.value
                  ? "border-accent font-medium text-heading"
                  : "border-transparent text-fg-secondary hover:text-fg"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      {mode === Mode.team && canSeeOthers ? (
        <div className="min-h-0 flex-1 overflow-hidden">
          <TeamReport
            everyone={seesEveryone}
            onOpenPerson={(userId, day, teamId) => {
              // The report reads its filters from the URL when it mounts. A
              // team lead's report is filtered by team, not person: the people
              // filter lists the whole instance, which is not theirs to see.
              writeUrlState(
                seesEveryone
                  ? { u: userId, d: day, g: "person", tm: null }
                  : { u: null, d: day, g: "person", tm: teamId || null },
              );
              setMode(Mode.report);
            }}
          />
        </div>
      ) : mode === Mode.log ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          <TimeLogCalendar anchor={anchor} onAnchor={setAnchor} />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <TimesheetReport />
        </div>
      )}
    </div>
  );
}
