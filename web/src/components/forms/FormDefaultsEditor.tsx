import { useQuery } from "@tanstack/react-query";
import {
  KIND_META,
  KIND_ORDER,
  PRIORITY_META,
  PRIORITY_ORDER,
} from "../../lib/meta";
import { cyclesQuery, releasesQuery, statesQuery, usersQuery } from "../../lib/queries";
import {
  type FormDefaults,
  type ItemKindValue,
  type PriorityValue,
} from "../../lib/types";
import { LabelsEditor } from "../items/LabelsEditor";
import { SelectField } from "../SelectField";
import { PersonName } from "../PersonName";

interface FormDefaultsEditorProps {
  projectId: string;
  value: FormDefaults;
  onChange: (defaults: FormDefaults) => void;
}

/**
 * Defaults applied to the item a submission creates (spec 20): kind, state,
 * priority, labels, assignee, cycle, release. Names/versions resolve at submit
 * time; every field is optional (null = leave the item's own default).
 */
export function FormDefaultsEditor({
  projectId,
  value,
  onChange,
}: FormDefaultsEditorProps) {
  const states = useQuery(statesQuery(projectId));
  const cycles = useQuery(cyclesQuery());
  const releases = useQuery(releasesQuery(projectId));
  const users = useQuery(usersQuery);
  const set = (patch: Partial<FormDefaults>) => onChange({ ...value, ...patch });

  return (
    <fieldset className="flex flex-col gap-3 rounded-md border border-subtle p-3">
      <legend className="px-1 text-xs font-medium text-fg-muted">Defaults (optional)</legend>
      <div className="grid grid-cols-2 gap-3">
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

        <SelectField
          label="Assignee"
          value={value.assignee_email ?? ""}
          onChange={(event) => set({ assignee_email: event.target.value || null })}
        >
          <option value="">Unassigned</option>
          {(users.data ?? [])
            .filter((user) => user.active)
            .map((user) => (
              <option key={user.id} value={user.email}>
                <PersonName user={user} /> ({user.email})
              </option>
            ))}
        </SelectField>

        <SelectField
          label="Cycle"
          value={value.cycle_name ?? ""}
          onChange={(event) => set({ cycle_name: event.target.value || null })}
          hint={(cycles.data ?? []).length === 0 ? "No cycles yet" : undefined}
        >
          <option value="">No cycle</option>
          {(cycles.data ?? []).map((cycle) => (
            <option key={cycle.id} value={cycle.name}>
              {cycle.name}
            </option>
          ))}
        </SelectField>

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
    </fieldset>
  );
}

/** A blank defaults object (used when creating a form). */
export const emptyDefaults: FormDefaults = {
  kind: null,
  state_name: null,
  priority: null,
  labels: [],
  assignee_email: null,
  cycle_name: null,
  release_version: null,
};
