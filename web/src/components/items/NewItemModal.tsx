import { TeamSelect } from "../teams/TeamSelect";
import { CycleSelect } from "../cycles/CycleSelect";
import { Fragment, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import {
  customFieldErrors,
  findingsByField,
  validationBlocking,
  validationFindings,
} from "../../lib/api";
import type { BucketCreatePreset } from "../../lib/axis-dnd";
import { fieldInScope } from "../../lib/field-scope";
import { PARENT_SEARCH_LIMIT, RoutePath } from "../../lib/constants";
import { pushToast, ToastKind } from "../../lib/toast";
import { useDebounced, useItemWritability, usePointsEnabled } from "../../lib/hooks";
import { useValidateItem } from "../../lib/item-mutations";
import {
  KIND_META,
  KIND_ORDER,
  PRIORITY_META,
  PRIORITY_ORDER,
  VISIBILITY_META,
  VISIBILITY_ORDER,
} from "../../lib/meta";
import {
  issueTypesQuery,
  fieldsQuery,
  linkSearchQuery,
  releasesQuery,
  statesQuery,
  usersQuery,
  validationContextQuery,
  effectiveScreenQuery,
} from "../../lib/queries";
import {
  ItemVisibility,
  type ItemVisibilityValue,
  IntakeCommit,
  ItemKind,
  ScreenPlacement,
  Priority,
  type CustomFieldValue,
  type CustomFields,
  type ItemCreate,
  type ItemKindValue,
  type ItemLinkSearchResult,
  type Finding,
  type IntakeCommitValue,
  type PriorityValue,
  type Project,
} from "../../lib/types";
import { Button, ButtonVariant } from "../Button";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { PersonName } from "../PersonName";
import { TextField } from "../TextField";
import { CustomFieldsForm } from "./CustomFieldsForm";
import { DeflectionPanel } from "./DeflectionPanel";
import { FindingsPanel } from "./FindingsPanel";
import { LabelsEditor } from "./LabelsEditor";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";
import { CollapsibleCard } from "../CollapsibleCard";

interface NewItemModalProps {
  project: Project;
  /** Field prefill (board quick-add into a column, spec-24 axis semantics) —
   * seeds the initial state only; the user can change anything before saving. */
  initial?: BucketCreatePreset;
  onClose: () => void;
}

/** How a finding names a custom field (spec 119) — the same `cf.<key>` form the
 * card-layout attribute catalogue uses. */
const CUSTOM_FIELD_PREFIX = "cf.";

/** Builtin field keys as a person would name them, for the findings panel.
 * Mirrors the server's `BuiltinItemField`; anything not listed simply shows the
 * message with no prefix, which is the right degradation for a field this build
 * has not heard of. */
const BUILTIN_FIELD_LABELS: Record<string, string> = {
  title: "Title",
  description: "Description",
  state: "State",
  priority: "Priority",
  assignee: "Assignee",
  reporter: "Reporter",
  team: "Team",
  labels: "Labels",
  parent: "Parent",
  start_date: "Start date",
  target_date: "Target date",
  cycle: "Cycle",
  release: "Release",
  flagged: "Flag",
  estimate_points: "Points",
};

/** The kind a parent must have (spec-02 ladder): issue → epic, subtask → issue. */
function requiredParentKind(kind: ItemKindValue): ItemKindValue | null {
  if (kind === ItemKind.issue) return ItemKind.epic;
  if (kind === ItemKind.subtask) return ItemKind.issue;
  return null;
}

export function NewItemModal({ project, initial, onClose }: NewItemModalProps) {
  const states = useQuery(statesQuery(project.id));
  const fields = useQuery(fieldsQuery());
  const projectFields = useMemo(
    () => (fields.data ?? []).filter(field => fieldInScope(field, project.id)),
    [fields.data, project.id],
  );
  const users = useQuery(usersQuery);
  const releases = useQuery(releasesQuery(project.id));
  const types = useQuery(issueTypesQuery(project.id));
  const createItem = useValidateItem();
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
  // Spec 121: "" = the project's default (`item_default_visibility`), decided server-side.
  const [visibility, setVisibility] = useState<ItemVisibilityValue | "">("");
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
  // RADD-1292: the create form follows the type's screen like the issue view
  // does — hidden fields stay out, secondary ones sit under "More fields". A
  // field with a finding against it always shows: you cannot fix what you
  // cannot see.
  const screen = useQuery(effectiveScreenQuery(project.id, effectiveTypeId || null));
  const placementOf = (field: string) =>
    screen.data?.fields.find((row) => row.field === field)?.placement ?? ScreenPlacement.primary;
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
  // Intake validation (spec 119). Re-queried on TYPE change: a project may
  // validate only its Bug type, and a button that kept saying "Create" after
  // someone switched to it would misdescribe what pressing it does.
  const validation = useQuery(validationContextQuery(project.id, typeId || defaultTypeId));
  const governed = validation.data?.governed ?? false;
  // THE LAST VERDICT this modal saw — the findings and whether they REFUSE the
  // creation, held together in one piece of state.
  //
  // They have to travel together, and `blocking` has to come from the server.
  // It decides the panel's voice and whether "Create anyway" is offered, and it
  // is the same property the server answers a `commit: always` 409 by — so
  // computing it here from the cached context read (`mode === "required"`) got
  // it wrong twice over: the read is a minute old, and a required graph merely
  // WATCHING a draft that only tripped an advisory one is not a refusal. Both
  // the 200 verdict and the 422 body carry it. The context read survives only
  // as what the button should SAY before anything has been submitted.
  const [verdict, setVerdict] = useState<{ findings: Finding[]; blocking: boolean }>({
    findings: [],
    blocking: false,
  });
  const findings = verdict.findings;
  const blocking = verdict.blocking;

  const fieldErrors = createItem.isError ? customFieldErrors(createItem.error) : {};
  // Findings addressed at a control merge into the same per-field error map the
  // registry's 422 already fills — the inputs need no second concept.
  const findingErrors = findingsByField(findings);
  const errorFor = (key: string) => fieldErrors[key] ?? findingErrors[key];
  // `cf.<key>` → the bare key the custom-field form is keyed by.
  const customFieldFindings = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [key, message] of Object.entries(findingErrors)) {
      if (key.startsWith(CUSTOM_FIELD_PREFIX)) out[key.slice(CUSTOM_FIELD_PREFIX.length)] = message;
    }
    return out;
  }, [findingErrors]);
  /** A finding's field key as a person would name it, for the panel. */
  const labelForField = (key: string): string | undefined => {
    if (key.startsWith(CUSTOM_FIELD_PREFIX)) {
      const bare = key.slice(CUSTOM_FIELD_PREFIX.length);
      return projectFields.find((definition) => definition.key === bare)?.name ?? bare;
    }
    return BUILTIN_FIELD_LABELS[key];
  };

  const setCustomField = (key: string, value: CustomFieldValue) => {
    setCustomFields((previous) => ({ ...previous, [key]: value }));
  };

  const submit = (commit: IntakeCommitValue) => {
    // Only send values the user set — the registry 422s on missing required keys.
    const setValues: CustomFields = {};
    for (const [key, value] of Object.entries(customFields)) {
      if (value !== null && value !== undefined && projectFields.some(field => field.key === key)) {
        setValues[key] = value;
      }
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
    if (visibility) body.visibility = visibility;
    if (kind !== ItemKind.epic && parentPick) body.parent_id = parentPick.id;
    if (cycleId) body.cycle_id = cycleId;
    if (releaseId) body.release_id = releaseId;
    if (startDate) body.start_date = startDate;
    if (targetDate) body.target_date = targetDate;
    if (pointsEnabled && points.trim() !== "") body.estimate_points = Number(points);
    createItem.mutate(
      { body, commit },
      {
        onSuccess: (result) => {
          setVerdict({
            findings: result.verdict.findings,
            blocking: result.verdict.blocking,
          });
          // `created` is null exactly when the draft did not survive — the
          // checks refused it. Keeping the modal open is the point: the person
          // is about to fix what it says.
          if (result.created) {
            // RADD-1230: the modal closes wherever it was opened from — a
            // board, the pins bar — so the one thing the person wants next,
            // the issue itself, is a click away rather than a search away.
            pushToast(`Created ${result.created.key}`, ToastKind.success, {
              label: "Open",
              to: RoutePath.issue,
              params: { itemKey: result.created.key },
            });
            onClose();
          }
        },
        // This endpoint answers with a VERDICT, so findings normally arrive
        // above. Parsed here too because the same draft can also be refused by
        // the enforcement path's spec-119 422 (a graph bound after this modal
        // read its context), and a surface that showed "request failed" for
        // that would hide the very list it exists to show.
        //
        // An error that carries NO findings — a 409 from "create anyway" under
        // a required binding, a 503 while the checks are down, a field-registry
        // 422 — leaves the list alone. Blanking it was the bug: the 409 is a
        // refusal to bypass the very findings it then erased, so the panel
        // vanished at the exact moment it was being argued with.
        onError: (error) => {
          const refused = validationFindings(error);
          const answered = validationBlocking(error);
          if (refused.length > 0 || answered !== null) {
            setVerdict((previous) => ({
              findings: refused.length > 0 ? refused : previous.findings,
              blocking: answered ?? previous.blocking,
            }));
          }
        },
      },
    );
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit(IntakeCommit.pass);
  };

  // RADD-1292: screen placement for the optional fields (see placementOf).
  const secondary: ReactNode[] = [];
  const place = (field: string, node: ReactNode) => {
    // Until the screen is known, hold the optional fields back rather than show
    // ones it may hide a moment later (a failed lookup falls back to showing all).
    if (screen.isPending) return null;
    const placement = placementOf(field);
    if (errorFor(field) || placement === ScreenPlacement.primary) return node;
    if (placement === ScreenPlacement.secondary) secondary.push(<Fragment key={field}>{node}</Fragment>);
    return null;
  };
  const customPlacement = (key: string) =>
    fieldErrors[key] || customFieldFindings[key] ? ScreenPlacement.primary : placementOf(`cf:${key}`);
  const shownFields = screen.isPending ? [] : projectFields.filter((field) => customPlacement(field.key) === ScreenPlacement.primary);
  const moreFields = projectFields.filter((field) => customPlacement(field.key) === ScreenPlacement.secondary);

  return (
    <Modal title={`New issue in ${project.key}`} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <TextField
          label="Title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Short, imperative summary"
          maxLength={500}
          required
          error={errorFor("title")}
        />

        {/* KB deflection (spec 66): maybe an article or a resolved issue already answers it. */}
        <DeflectionPanel query={title} projectId={project.id} />

        <div className="flex flex-col gap-1.5" data-field="description">
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
          {/* The rich editor is not a `TextField` and has no error slot, so a
              finding about the description sits beneath it — same colour, same
              size, in the place the eye already goes for an input's error. */}
          {errorFor("description") && (
            <p className="text-xs text-status-danger-ink">{errorFor("description")}</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Kind"
            // RADD-1292 (kind vs type stays, 2026-09-23 — explained, not merged).
            hint="Where it sits: an epic holds issues, an issue holds subtasks. Type says what it is."
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
            error={errorFor("state")}
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
            error={errorFor("priority")}
            onChange={(event) => setPriority(event.target.value as PriorityValue)}
          >
            {PRIORITY_ORDER.map((value) => (
              <option key={value} value={value}>
                {PRIORITY_META[value].label}
              </option>
            ))}
          </SelectField>

          <SelectField
            label="Visibility"
            value={visibility}
            onChange={(event) => setVisibility(event.target.value as ItemVisibilityValue | "")}
          >
            <option value="">Project default</option>
            {VISIBILITY_ORDER.filter(
              (value) => project.public || value !== ItemVisibility.internal,
            ).map((value) => (
              <option key={value} value={value} title={VISIBILITY_META[value].description}>
                {project.public ? VISIBILITY_META[value].label : VISIBILITY_META[value].privateLabel}
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
                  <IconButton
                    onClick={() => setParentPick(null)}
                    aria-label="Clear parent"
                  >
                    <X size={13} aria-hidden />
                  </IconButton>
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

          {place("assignee", <SelectField
            label="Assignee"
            value={assigneeId}
            {...lock("assignee")}
            error={errorFor("assignee")}
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
          </SelectField>)}

          {place("team", <TeamSelect label="Team" value={teamId} onChange={setTeamId} {...lock("team")} error={errorFor("team")} />)}

          {place("cycle", <CycleSelect label="Cycle" value={cycleId} onChange={setCycleId} projectId={project.id} {...lock("cycle")} error={errorFor("cycle")} />)}

          {place("release", <SelectField
            label="Release"
            value={releaseId}
            {...lock("release")}
            error={errorFor("release")}
            onChange={(event) => setReleaseId(event.target.value)}
            hint={(releases.data ?? []).length === 0 ? "No releases yet" : undefined}
          >
            <option value="">No release</option>
            {(releases.data ?? []).map((release) => (
              <option key={release.id} value={release.id}>
                {release.version}
              </option>
            ))}
          </SelectField>)}

          {place("start_date", <TextField
            label="Start date"
            type="date"
            value={startDate}
            {...lock("start_date")}
            error={errorFor("start_date")}
            onChange={(event) => setStartDate(event.target.value)}
            className="[color-scheme:dark]"
          />)}

          {place("target_date", <TextField
            label="Target date"
            type="date"
            value={targetDate}
            {...lock("target_date")}
            error={errorFor("target_date")}
            onChange={(event) => setTargetDate(event.target.value)}
            className="[color-scheme:dark]"
          />)}

          {pointsEnabled && place("points",
            <TextField
              label="Points"
              type="number"
              value={points}
              error={errorFor("estimate_points")}
              onChange={(event) => setPoints(event.target.value)}
              placeholder="Story points"
              min={0}
              max={999}
              step={0.5}
            />
          )}
        </div>

        {place("labels", <div className="flex flex-col gap-1.5" data-field="labels">
          <LabelsEditor
            value={labels}
            onChange={setLabels}
            disabled={writ.restricted("labels")}
            lockedReason={writ.reasonFor("labels")}
          />
          {/* The token editor is not a `TextField` and has no error slot, so a
              finding about the labels sits beneath it — the same shape the
              description uses, and the same place the eye already goes. */}
          {errorFor("labels") && (
            <p className="text-xs text-status-danger-ink">{errorFor("labels")}</p>
          )}
        </div>)}

        {shownFields.length > 0 && (
          <fieldset className="flex flex-col gap-3 rounded-md border border-subtle p-3">
            <legend className="px-1 text-xs font-medium text-fg-muted">Custom fields</legend>
            <CustomFieldsForm
              fields={shownFields}
              values={customFields}
              // `cf.<key>` is how a finding names a custom field; the form keys
              // by the bare key, and that is the only translation between them.
              errors={{ ...fieldErrors, ...customFieldFindings }}
              onChange={setCustomField}
              lockFor={(key) => ({ locked: writ.restricted(key), reason: writ.reasonFor(key) })}
            />
          </fieldset>
        )}

        {(secondary.length > 0 || moreFields.length > 0) && (
          <div data-more-fields>
            <CollapsibleCard title="More fields" count={secondary.length + moreFields.length}>
              <div className="grid grid-cols-2 gap-3">{secondary}</div>
              {moreFields.length > 0 && (
                <div className="mt-3">
                  <CustomFieldsForm
                    fields={moreFields}
                    values={customFields}
                    errors={{ ...fieldErrors, ...customFieldFindings }}
                    onChange={setCustomField}
                    lockFor={(key) => ({ locked: writ.restricted(key), reason: writ.reasonFor(key) })}
                  />
                </div>
              )}
            </CollapsibleCard>
          </div>
        )}

        {/* Every finding, including ones already against a control: one may be
            attached to an input the person has not scrolled to. */}
        <FindingsPanel findings={findings} blocking={blocking} labelFor={labelForField} />

        {/* Judged on THIS error's shape rather than on whether findings are on
            screen: "Create anyway" refused with a 409, or a 503 while the checks
            are down, arrives with the panel full — and testing the list meant
            the presses that fail for a reason of their own said nothing. */}
        {createItem.isError &&
          Object.keys(fieldErrors).length === 0 &&
          validationFindings(createItem.error).length === 0 && (
            <ErrorText error={createItem.error} />
          )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          {/* Offered exactly when the server would honour it. `blocking` IS the
              condition `commit: always` is refused by (409), read off the answer
              rather than recomputed here — a button that is refused on press is
              worse than one that is absent, and a button that is absent where
              the server would have accepted it is a rule nobody wrote. */}
          {findings.length > 0 && !blocking && (
            <Button
              variant={ButtonVariant.secondary}
              onClick={() => submit(IntakeCommit.always)}
              disabled={createItem.isPending || title.trim() === ""}
            >
              Create anyway
            </Button>
          )}
          <Button type="submit" disabled={createItem.isPending || title.trim() === ""}>
            {createItem.isPending
              ? governed
                ? "Checking…"
                : "Creating…"
              : governed
                ? "Validate & create"
                : "Create issue"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
