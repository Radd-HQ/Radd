import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { customFieldErrors, errorMessage } from "../../lib/api";
import type { BucketCreatePreset } from "../../lib/axis-dnd";
import { PARENT_SEARCH_LIMIT } from "../../lib/constants";
import { useDebounced, useItemWritability, usePointsEnabled } from "../../lib/hooks";
import { useCreateItem } from "../../lib/item-mutations";
import { KIND_META, KIND_ORDER, PRIORITY_META, PRIORITY_ORDER } from "../../lib/meta";
import {
  cyclesQuery,
  issueTypesQuery,
  fieldsQuery,
  linkSearchQuery,
  releasesQuery,
  statesQuery,
  teamsQuery,
  usersQuery,
} from "../../lib/queries";
import {
  ItemKind,
  Priority,
  type CustomFieldValue,
  type CustomFields,
  type ItemCreate,
  type ItemKindValue,
  type ItemLinkSearchResult,
  type PriorityValue,
  type Project,
} from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { PersonName } from "../PersonName";
import { TextField } from "../TextField";
import { CustomFieldsForm } from "./CustomFieldsForm";
import { DeflectionPanel } from "./DeflectionPanel";
import { LabelsEditor } from "./LabelsEditor";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";

interface NewItemModalProps {
  project: Project;
  /** Field prefill (board quick-add into a column, spec-24 axis semantics) —
   * seeds the initial state only; the user can change anything before saving. */
  initial?: BucketCreatePreset;
  onClose: () => void;
}

/** The kind a parent must have (spec-02 ladder): issue → epic, subtask → issue. */
function requiredParentKind(kind: ItemKindValue): ItemKindValue | null {
  if (kind === ItemKind.issue) return ItemKind.epic;
  if (kind === ItemKind.subtask) return ItemKind.issue;
  return null;
}

export function NewItemModal({ project, initial, onClose }: NewItemModalProps) {
  const states = useQuery(statesQuery(project.id));
  const fields = useQuery(fieldsQuery());
  const users = useQuery(usersQuery);
  const teams = useQuery(teamsQuery());
  const cycles = useQuery(cyclesQuery());
  const releases = useQuery(releasesQuery(project.id));
  const types = useQuery(issueTypesQuery(project.id));
  const createItem = useCreateItem(project.id);
  // Story points (spec 70): the input exists only where the project opted in.
  const pointsEnabled = usePointsEnabled(project.id);
  // Per-field write grants apply on create too (spec 92): item.create already gates this whole
  // modal, so lock only the individual fields a grant restricts — disabled, dimmed, with a reason.
  const writ = useItemWritability(project);
  const lock = (name: string) => ({
    disabled: writ.restricted(name),
    title: writ.restricted(name) ? writ.reasonFor(name) : undefined,
  });

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<ItemKindValue>(initial?.kind ?? ItemKind.issue);
  const [typeId, setTypeId] = useState("");
  const [stateId, setStateId] = useState(initial?.state_id ?? "");
  const [priority, setPriority] = useState<PriorityValue>(initial?.priority ?? Priority.normal);
  const [assigneeId, setAssigneeId] = useState(initial?.assignee_id ?? "");
  const [teamId, setTeamId] = useState(initial?.team_id ?? "");
  // Parent picker (spec 80): server-wide typeahead, same-project candidates
  // ranked first by the server; the kind ladder filters client-side.
  const [parentPick, setParentPick] = useState<ItemLinkSearchResult | null>(null);
  const [parentSearch, setParentSearch] = useState("");
  const [parentOpen, setParentOpen] = useState(false);
  const [cycleId, setCycleId] = useState(initial?.cycle_id ?? "");
  const [releaseId, setReleaseId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [points, setPoints] = useState("");
  const [labels, setLabels] = useState<string[]>([]);
  const [customFields, setCustomFields] = useState<CustomFields>({});

  const defaultStateId = useMemo(
    () => states.data?.find((state) => state.is_default)?.id ?? states.data?.[0]?.id ?? "",
    [states.data],
  );
  const defaultTypeId = useMemo(
    () => types.data?.find((issueType) => issueType.is_default)?.id ?? "",
    [types.data],
  );

  // Issue templates (spec 76): selecting a type with a template prefills the
  // description while it's still PRISTINE — empty, or exactly the template a
  // previous selection inserted (tracked below, so switching types swaps the
  // template but never clobbers what the user typed). The rich editor is
  // uncontrolled (create-once), so a programmatic swap remounts it via `key`.
  const [insertedTemplate, setInsertedTemplate] = useState<string | null>(null);
  const [editorSeed, setEditorSeed] = useState(0);
  const effectiveTypeId = typeId || defaultTypeId;
  useEffect(() => {
    const template =
      types.data?.find((issueType) => issueType.id === effectiveTypeId)?.description_template ??
      null;
    const pristine =
      description === "" || (insertedTemplate !== null && description === insertedTemplate);
    if (!pristine || (template ?? "") === description) return;
    // Swap in the new type's template, or back to empty when it has none.
    setDescription(template ?? "");
    setInsertedTemplate(template);
    setEditorSeed((seed) => seed + 1);
    // Reacts to type changes only — description/insertedTemplate are read
    // fresh but must not re-trigger (user edits stick).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveTypeId, types.data]);

  const parentKind = requiredParentKind(kind);
  const parentQuery = useDebounced(parentSearch.trim(), 200);
  const parentSearchResults = useQuery({
    ...linkSearchQuery(project.id, parentQuery, undefined, PARENT_SEARCH_LIMIT),
    enabled: parentKind !== null && parentOpen,
  });
  const parents = useMemo(
    () =>
      (parentSearchResults.data ?? []).filter((candidate) => candidate.kind === parentKind),
    [parentSearchResults.data, parentKind],
  );
  const fieldErrors = createItem.isError ? customFieldErrors(createItem.error) : {};

  const setCustomField = (key: string, value: CustomFieldValue) => {
    setCustomFields((previous) => ({ ...previous, [key]: value }));
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    // Only send values the user set — the registry 422s on missing required keys.
    const setValues: CustomFields = {};
    for (const [key, value] of Object.entries(customFields)) {
      if (value !== null && value !== undefined) setValues[key] = value;
    }
    const body: ItemCreate = {
      project_id: project.id,
      title: title.trim(),
      description,
      kind,
      priority,
      labels,
      custom_fields: setValues,
    };
    const chosenState = stateId || defaultStateId;
    if (chosenState) body.state_id = chosenState;
    const chosenType = typeId || defaultTypeId;
    if (chosenType) body.type_id = chosenType;
    if (assigneeId) body.assignee_id = assigneeId;
    if (teamId) body.team_id = teamId;
    if (kind !== ItemKind.epic && parentPick) body.parent_id = parentPick.id;
    if (cycleId) body.cycle_id = cycleId;
    if (releaseId) body.release_id = releaseId;
    if (startDate) body.start_date = startDate;
    if (targetDate) body.target_date = targetDate;
    if (pointsEnabled && points.trim() !== "") body.estimate_points = Number(points);
    createItem.mutate(body, { onSuccess: onClose });
  };

  return (
    <Modal title={`New item in ${project.key}`} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <TextField
          label="Title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Short, imperative summary"
          maxLength={500}
          required
        />

        {/* KB deflection (spec 66): maybe an article or a resolved issue already answers it. */}
        <DeflectionPanel query={title} projectId={project.id} />

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-fg-secondary">Description</label>
          {/* No item id yet, so image upload is off until the issue exists.
              Keyed so a template swap (spec 76) reseeds the uncontrolled editor. */}
          <RichEditor
            key={editorSeed}
            value={description}
            onChange={setDescription}
            placeholder="Context, repro steps, links…"
            className="[&_.ProseMirror]:min-h-[8rem]"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Kind"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as ItemKindValue);
              setParentPick(null);
              setParentSearch("");
            }}
          >
            {KIND_ORDER.map((value) => (
              <option key={value} value={value}>
                {KIND_META[value].label}
              </option>
            ))}
          </SelectField>

          <SelectField
            label="Type"
            value={typeId || defaultTypeId}
            onChange={(event) => setTypeId(event.target.value)}
          >
            {(types.data ?? []).map((issueType) => (
              <option key={issueType.id} value={issueType.id}>
                {issueType.name}
              </option>
            ))}
          </SelectField>

          <SelectField
            label="State"
            value={stateId || defaultStateId}
            {...lock("state")}
            onChange={(event) => setStateId(event.target.value)}
          >
            {(states.data ?? []).map((state) => (
              <option key={state.id} value={state.id}>
                {state.name}
              </option>
            ))}
          </SelectField>

          <SelectField
            label="Priority"
            value={priority}
            {...lock("priority")}
            onChange={(event) => setPriority(event.target.value as PriorityValue)}
          >
            {PRIORITY_ORDER.map((value) => (
              <option key={value} value={value}>
                {PRIORITY_META[value].label}
              </option>
            ))}
          </SelectField>

          {kind !== ItemKind.epic && (
            <div className="relative flex flex-col gap-1.5">
              <label htmlFor="parent-search" className="text-xs font-medium text-fg-secondary">
                {kind === ItemKind.subtask ? "Parent issue" : "Parent epic"}
              </label>
              {parentPick ? (
                <div className="flex h-8 items-center gap-2 rounded-md border border-strong bg-surface px-2.5 text-[13px]">
                  <span className="shrink-0 font-mono text-[11px] text-fg-muted">
                    {parentPick.key}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-fg">{parentPick.title}</span>
                  <button
                    type="button"
                    onClick={() => setParentPick(null)}
                    aria-label="Clear parent"
                    className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-focus cursor-pointer"
                  >
                    <X size={13} aria-hidden />
                  </button>
                </div>
              ) : (
                <>
                  <input
                    id="parent-search"
                    value={parentSearch}
                    onChange={(event) => {
                      setParentSearch(event.target.value);
                      setParentOpen(true);
                    }}
                    onFocus={() => setParentOpen(true)}
                    onBlur={() => setTimeout(() => setParentOpen(false), 120)}
                    autoComplete="off"
                    // Candidates span every project (spec 80) — same-project first.
                    placeholder={
                      kind === ItemKind.subtask
                        ? "Search issues across all projects…"
                        : "Search epics across all projects…"
                    }
                    className="h-8 rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
                  />
                  {parentOpen && parents.length > 0 && (
                    <ul className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-md border border-strong bg-surface py-1 shadow-xl">
                      {parents.map((candidate) => (
                        <li key={candidate.id}>
                          <button
                            type="button"
                            // onMouseDown fires before the input's onBlur, so the pick lands.
                            onMouseDown={(event) => {
                              event.preventDefault();
                              setParentPick(candidate);
                              setParentOpen(false);
                            }}
                            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] hover:bg-elevated cursor-pointer"
                          >
                            <span className="shrink-0 font-mono text-[11px] text-fg-muted">
                              {candidate.key}
                            </span>
                            <span className="truncate text-fg">{candidate.title}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          )}

          <SelectField
            label="Assignee"
            value={assigneeId}
            {...lock("assignee")}
            onChange={(event) => setAssigneeId(event.target.value)}
          >
            <option value="">Unassigned</option>
            {(users.data ?? [])
              .filter((user) => user.active)
              .map((user) => (
                <option key={user.id} value={user.id} label={user.name}>
                  <PersonName user={user} />
                </option>
              ))}
          </SelectField>

          <SelectField
            label="Team"
            value={teamId}
            {...lock("team")}
            onChange={(event) => setTeamId(event.target.value)}
            hint={(teams.data ?? []).length === 0 ? "No teams yet" : undefined}
          >
            <option value="">None</option>
            {(teams.data ?? []).map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </SelectField>

          <SelectField
            label="Cycle"
            value={cycleId}
            {...lock("cycle")}
            onChange={(event) => setCycleId(event.target.value)}
            hint={(cycles.data ?? []).length === 0 ? "No cycles yet" : undefined}
          >
            <option value="">No cycle</option>
            {(cycles.data ?? []).map((cycle) => (
              <option key={cycle.id} value={cycle.id}>
                {cycle.name}
              </option>
            ))}
          </SelectField>

          <SelectField
            label="Release"
            value={releaseId}
            {...lock("release")}
            onChange={(event) => setReleaseId(event.target.value)}
            hint={(releases.data ?? []).length === 0 ? "No releases yet" : undefined}
          >
            <option value="">No release</option>
            {(releases.data ?? []).map((release) => (
              <option key={release.id} value={release.id}>
                {release.version}
              </option>
            ))}
          </SelectField>

          <TextField
            label="Start date"
            type="date"
            value={startDate}
            {...lock("start_date")}
            onChange={(event) => setStartDate(event.target.value)}
            className="[color-scheme:dark]"
          />

          <TextField
            label="Target date"
            type="date"
            value={targetDate}
            {...lock("target_date")}
            onChange={(event) => setTargetDate(event.target.value)}
            className="[color-scheme:dark]"
          />

          {pointsEnabled && (
            <TextField
              label="Points"
              type="number"
              value={points}
              onChange={(event) => setPoints(event.target.value)}
              placeholder="Story points"
              min={0}
              max={999}
              step={0.5}
            />
          )}
        </div>

        <LabelsEditor
          value={labels}
          onChange={setLabels}
          disabled={writ.restricted("labels")}
          lockedReason={writ.reasonFor("labels")}
        />

        {(fields.data ?? []).length > 0 && (
          <fieldset className="flex flex-col gap-3 rounded-md border border-subtle p-3">
            <legend className="px-1 text-xs font-medium text-fg-muted">Custom fields</legend>
            <CustomFieldsForm
              fields={fields.data ?? []}
              values={customFields}
              errors={fieldErrors}
              onChange={setCustomField}
              lockFor={(key) => ({ locked: writ.restricted(key), reason: writ.reasonFor(key) })}
            />
          </fieldset>
        )}

        {createItem.isError && Object.keys(fieldErrors).length === 0 && (
          <p className="text-xs text-red-400">{errorMessage(createItem.error)}</p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={createItem.isPending || title.trim() === ""}>
            {createItem.isPending ? "Creating…" : "Create item"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
