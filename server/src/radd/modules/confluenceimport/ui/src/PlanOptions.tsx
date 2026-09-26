import { SelectField } from "@radd/plugin-sdk";
import { MappingTarget } from "./MappingTarget";
import { ConfluenceUnresolvedPrincipal, type ConfluencePlanOptions } from "./types";

/** What the run brings besides the pages themselves, and what it does about an unknown principal. */
export function PlanOptions({
  options,
  onChange,
}: {
  options: ConfluencePlanOptions;
  onChange: (options: ConfluencePlanOptions) => void;
}) {
  const set = (changes: Partial<ConfluencePlanOptions>) => onChange({ ...options, ...changes });
  return (
    <fieldset className="mt-4 rounded-lg border border-subtle p-3">
      <legend className="px-1 text-[12px] font-medium text-fg-secondary">Options</legend>
      <div className="flex flex-col gap-2 text-[13px] text-fg-secondary">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.quiet}
            onChange={(e) => set({ quiet: e.target.checked })}
          />
          Import quietly (no notifications, webhooks or automations)
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.import_attachments}
            onChange={(e) => set({ import_attachments: e.target.checked })}
          />
          Bring attachments
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.import_comments}
            onChange={(e) => set({ import_comments: e.target.checked })}
          />
          Bring comments
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.import_restrictions}
            onChange={(e) => set({ import_restrictions: e.target.checked })}
          />
          Bring page restrictions
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={options.include_history}
            onChange={(e) => set({ include_history: e.target.checked })}
          />
          Bring version history (only if the download captured it)
        </label>
        <SelectField
          label="When a restriction names someone we cannot find"
          value={options.unresolved_principal}
          onChange={(e) =>
            set({ unresolved_principal: e.target.value as ConfluencePlanOptions["unresolved_principal"] })
          }
          hint="Refusing is the safe default: importing a restricted page open exposes it, and nobody notices."
        >
          <option value={ConfluenceUnresolvedPrincipal.fail}>Do not import that page</option>
          <option value={ConfluenceUnresolvedPrincipal.map_to}>Restrict it to a chosen group or team</option>
        </SelectField>
        {options.unresolved_principal === ConfluenceUnresolvedPrincipal.map_to && <MappingTarget section="groups" row={{action:"map",group_id:options.unresolved_group_id,team_id:options.unresolved_team_id}} onChange={changes => set({unresolved_group_id:changes.group_id as string | null,unresolved_team_id:changes.team_id as string | null})}/>}
      </div>
    </fieldset>
  );
}
