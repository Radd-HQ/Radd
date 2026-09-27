/** The Add participant node's form: this plugin's automation action (RADD-1387), so its form lives
 *  here, not in Automations. It always runs once per issue — sharing is a property of one issue. */
import { OptionSelect, usePermissions, type AutomationNodeInspectorProps } from "@radd/plugin-sdk";

/** Stored in saved graphs from when the action was built in: never rename it. */
export const ADD_PARTICIPANT_NODE = "action.add_participant";

/** The auth plugin's people option resource. */
const PEOPLE_OPTIONS = "users";

/** People named relative to the issue — the server's `PersonRole`, which the node resolves per issue. */
const PersonRole = { assignee: "assignee", reporter: "reporter" } as const;
const ROLE_CHOICES = [
  { value: PersonRole.assignee, label: "Its assignee", hint: "" },
  { value: PersonRole.reporter, label: "Its reporter", hint: "" },
];

export function AddParticipantInspector({ params, onChange }: AutomationNodeInspectorProps) {
  const canBrowsePeople = usePermissions().global("user.manage");
  return (
    <div className="flex flex-col gap-1" data-add-participant-inspector>
      <OptionSelect
        resource={PEOPLE_OPTIONS}
        label="Person"
        value={typeof params.user === "string" ? params.user : ""}
        canBrowse={canBrowsePeople}
        presets={ROLE_CHOICES}
        onChange={(user) => onChange({ ...params, user })}
      />
      <p className="text-xs text-fg-muted">A role resolves against each issue; an email names one person.</p>
    </div>
  );
}
