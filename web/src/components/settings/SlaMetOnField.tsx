import { SelectField } from "../SelectField";
import { TokenMultiSelect } from "../TokenMultiSelect";
import { TeamAudience } from "../teams/TeamAudience";
import { SlaMetOn, type SlaMetOnValue } from "../../lib/types";

/** RADD-1299: one target's "met when" choice plus the states/teams it names. */
export interface MetRule {
  metOn: SlaMetOnValue;
  stateIds: string[];
  teamIds: string[];
}

const LABELS: Record<SlaMetOnValue, string> = {
  [SlaMetOn.firstReply]: "First public reply (anyone but the reporter)",
  [SlaMetOn.replyByTeams]: "First public reply by members of chosen teams",
  [SlaMetOn.replyByAssignedTeam]: "First public reply by the issue's team (anyone if it has none)",
  [SlaMetOn.done]: "Issue reaches a done state",
  [SlaMetOn.entersStates]: "Issue enters one of these states",
  [SlaMetOn.leavesStates]: "Issue leaves these states (moves anywhere else)",
};

/** Is the rule complete enough to save? (The server refuses the same cases.) */
export function metRuleValid(rule: MetRule): boolean {
  if (rule.metOn === SlaMetOn.entersStates || rule.metOn === SlaMetOn.leavesStates) return rule.stateIds.length > 0;
  if (rule.metOn === SlaMetOn.replyByTeams) return rule.teamIds.length > 0;
  return true;
}

/** Plain words for a policy summary: "met on leaving Triage". */
export function metRuleSummary(metOn: SlaMetOnValue, stateNames: string[], teamCount: number): string {
  switch (metOn) {
    case SlaMetOn.replyByTeams: return `met by a reply from ${teamCount} team${teamCount === 1 ? "" : "s"}`;
    case SlaMetOn.replyByAssignedTeam: return "met by the issue's team replying";
    case SlaMetOn.entersStates: return `met on entering ${stateNames.join("/")}`;
    case SlaMetOn.leavesStates: return `met on leaving ${stateNames.join("/")}`;
    case SlaMetOn.done: return "met when done";
    default: return "met by a first reply";
  }
}

export function SlaMetOnField({
  target,
  rule,
  onChange,
  states,
}: {
  target: "response" | "resolution";
  rule: MetRule;
  onChange: (rule: MetRule) => void;
  states: { id: string; name: string }[];
}) {
  const needsStates = rule.metOn === SlaMetOn.entersStates || rule.metOn === SlaMetOn.leavesStates;
  return (
    <div className="flex flex-col gap-2" data-met-rule={target}>
      <SelectField
        label={target === "response" ? "Response is met when" : "Resolution is met when"}
        value={rule.metOn}
        onChange={(event) => onChange({ ...rule, metOn: event.target.value as SlaMetOnValue })}
      >
        {Object.values(SlaMetOn).map((mode) => (
          <option key={mode} value={mode}>{LABELS[mode]}</option>
        ))}
      </SelectField>
      {needsStates && (
        <TokenMultiSelect
          value={rule.stateIds}
          onChange={(stateIds) => onChange({ ...rule, stateIds })}
          options={states.map((state) => ({ value: state.id, label: state.name }))}
          placeholder="Add a state…"
          invalid={rule.stateIds.length === 0}
          ariaLabel={`${target} target states`}
        />
      )}
      {rule.metOn === SlaMetOn.replyByTeams && (
        <TeamAudience
          value={rule.teamIds}
          onChange={(teamIds) => onChange({ ...rule, teamIds })}
          emptyText="Choose the teams whose first public reply meets this target."
          hint="Membership is read live, including members through linked directory groups."
          addLabel="Add team"
        />
      )}
    </div>
  );
}
