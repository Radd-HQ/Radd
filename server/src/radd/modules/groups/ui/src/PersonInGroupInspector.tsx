/** The "Person is in directory group" gate's form (RADD-1498): this plugin's node, so its form lives
 *  here. The person is a role on the issue, the event's actor, or an email; the groups come from the
 *  mirror's option source (stored by id — the gate also accepts a name or a DN from a hand-written graph). */
import { OptionNameValues, OptionSelect, Switch, usePermissions, type AutomationNodeInspectorProps } from "@radd/plugin-sdk";

/** Stored in saved graphs: never rename it. */
export const PERSON_IN_GROUP_NODE = "gate.person_in_group";

const PEOPLE_OPTIONS = "users";
const GROUP_OPTIONS = "groups";

/** The server's `GatePerson` vocabulary. */
const PERSON_PRESETS = [
  { value: "reporter", label: "Its reporter", hint: "" },
  { value: "assignee", label: "Its assignee", hint: "" },
  { value: "actor", label: "Whoever made the change", hint: "" },
];

export function PersonInGroupInspector({ params, onChange }: AutomationNodeInspectorProps) {
  const canBrowsePeople = usePermissions().global("user.manage");
  const groups = Array.isArray(params.groups) ? (params.groups as string[]) : [];
  return (
    <div className="flex flex-col gap-2" data-person-in-group-inspector>
      <OptionSelect
        resource={PEOPLE_OPTIONS}
        label="Person"
        value={typeof params.person === "string" ? params.person : "reporter"}
        canBrowse={canBrowsePeople}
        presets={PERSON_PRESETS}
        onChange={(person) => onChange({ ...params, person })}
      />
      <OptionNameValues
        resource={GROUP_OPTIONS}
        label="Is in one of these directory groups"
        value={groups}
        onChange={(next) => onChange({ ...params, groups: next })}
      />
      <p className="text-xs text-fg-muted">Membership is nested: a member of a group inside one of these counts.</p>
      <Switch
        label="Invert — true when they are NOT in any of them"
        checked={Boolean(params.negate)}
        onChange={(negate) => onChange({ ...params, negate })}
      />
    </div>
  );
}
