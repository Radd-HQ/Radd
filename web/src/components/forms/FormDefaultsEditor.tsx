import { CycleSelect } from "../cycles/CycleSelect";
import { useQuery } from "@tanstack/react-query";
import {
  KIND_META,
  KIND_ORDER,
  PRIORITY_META,
  PRIORITY_ORDER,
} from "../../lib/meta";
import {
  issueTypesQuery,
  releasesQuery,
  statesQuery,
} from "../../lib/queries";
import {
  Permission,
  type FormDefaults,
  type ItemKindValue,
  type PriorityValue,
} from "../../lib/types";
import { LabelsEditor } from "../items/LabelsEditor";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { OptionTextField } from "../DirectoryChoices";
import { OptionResource } from "../../lib/queries/options";
import { usePermissions } from "../../lib/hooks";

interface FormDefaultsEditorProps {
  projectId: string;
  value: FormDefaults;
  onChange: (defaults: FormDefaults) => void;
}

/**
 * Defaults applied to the item a submission creates (spec 20 → RADD-801).
 *
 * Names and versions resolve at submit; every field is optional (null = leave
 * the item's own default).
 *
 * KIND and TYPE are two different axes and both are here, which is the fix
 * RADD-801 exists for: `kind` is the epic/issue/subtask ladder, spec 51's TYPE
 * is Bug/Feature/Story. The form used to offer only `kind`, labelled in a way
 * that read as "type", so the control you reached for set the wrong thing.
 */
export function FormDefaultsEditor({
  projectId,
  value,
  onChange,
}: FormDefaultsEditorProps) {
  const states = useQuery(statesQuery(projectId));
  const issueTypes = useQuery(issueTypesQuery(projectId));
  const releases = useQuery(releasesQuery(projectId));
  const permissions = usePermissions();
  const set = (patch: Partial<FormDefaults>) => onChange({ ...value, ...patch });

  return (
    <fieldset className="flex flex-col gap-3 rounded-md border border-subtle p-3">
      <legend className="px-1 text-xs font-medium text-fg-muted">Defaults (optional)</legend>
      <div className="grid grid-cols-2 gap-3">
        <SelectField
          label="Issue type"
          value={value.type_name ?? ""}
          onChange={(event) => set({ type_name: event.target.value || null })}
          hint="Bug, Feature, … — separate from Kind below"
        >
          <option value="">The project's default</option>
          {(issueTypes.data ?? []).map((type) => (
            <option key={type.id} value={type.name}>
              {type.name}
            </option>
          ))}
        </SelectField>

        <SelectField
          label="Kind"
          value={value.kind ?? ""}
          onChange={(event) => set({ kind: (event.target.value || null) as ItemKindValue | null })}
        >
          <option value="">Default (Issue)</option>
          {KIND_ORDER.map((kind) => (
            <option key={kind} value={kind}>
              {KIND_META[kind].label}
            </option>
          ))}
        </SelectField>

        <SelectField
          label="Priority"
          value={value.priority ?? ""}
          onChange={(event) =>
            set({ priority: (event.target.value || null) as PriorityValue | null })
          }
        >
          <option value="">Default (Normal)</option>
          {PRIORITY_ORDER.map((priority) => (
            <option key={priority} value={priority}>
              {PRIORITY_META[priority].label}
            </option>
          ))}
        </SelectField>

        <SelectField
          label="State"
          value={value.state_name ?? ""}
          onChange={(event) => set({ state_name: event.target.value || null })}
          hint={(states.data ?? []).length === 0 ? "No states loaded" : undefined}
        >
          <option value="">Project default</option>
          {(states.data ?? []).map((state) => (
            <option key={state.id} value={state.name}>
              {state.name}
            </option>
          ))}
        </SelectField>

        <OptionTextField label="Assignee" resource={OptionResource.user} value={value.assignee_email ?? ""}
          onChange={email => set({ assignee_email: email || null })} canBrowse={permissions.global(Permission.userManage)}
          placeholder="Unassigned" hint="Enter a known email address; leave empty for unassigned." />

        <CycleSelect label="Cycle" valueBy="name" value={value.cycle_name ?? ""} onChange={cycle => set({ cycle_name: cycle || null })} />

        <SelectField
          label="Release"
          value={value.release_version ?? ""}
          onChange={(event) => set({ release_version: event.target.value || null })}
          hint={(releases.data ?? []).length === 0 ? "No releases yet" : undefined}
        >
          <option value="">No release</option>
          {(releases.data ?? []).map((release) => (
            <option key={release.id} value={release.version}>
              {release.version}
            </option>
          ))}
        </SelectField>
      </div>

      <LabelsEditor value={value.labels} onChange={(labels) => set({ labels })} />

      {/* RADD-801 — scheduling and estimation reached ItemCreate in specs 24/70
          and never reached the form until now. */}
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Start date"
          type="date"
          value={value.start_date ?? ""}
          onChange={(event) => set({ start_date: event.target.value || null })}
        />
        <TextField
          label="Target date"
          type="date"
          value={value.target_date ?? ""}
          onChange={(event) => set({ target_date: event.target.value || null })}
        />
        <TextField
          label="Estimate (points)"
          type="number"
          min={0}
          max={999}
          step={0.5}
          value={value.estimate_points == null ? "" : String(value.estimate_points)}
          onChange={(event) =>
            set({ estimate_points: event.target.value === "" ? null : Number(event.target.value) })
          }
        />
        <label className="flex cursor-pointer items-center gap-2 self-end pb-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={value.flagged}
            onChange={(event) => set({ flagged: event.target.checked })}
            className="size-4 accent-accent"
          />
          Flagged on arrival
        </label>
      </div>
    </fieldset>
  );
}

/** A blank defaults object (used when creating a form). */
export const emptyDefaults: FormDefaults = {
  kind: null,
  type_name: null,
  state_name: null,
  priority: null,
  labels: [],
  assignee_email: null,
  cycle_name: null,
  release_version: null,
  start_date: null,
  target_date: null,
  flagged: false,
  estimate_points: null,
};
