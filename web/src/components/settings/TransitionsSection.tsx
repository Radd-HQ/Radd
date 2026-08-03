import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Plus,
  RotateCcw,
  Trash2,
  User as UserIcon,
  Users,
  X,
} from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { fieldInScope } from "../../lib/field-scope";
import { TRANSITION_MODE_LABELS } from "../../lib/meta";
import { ApiPath, apiTransitionPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import {
  cyclesQuery,
  fieldsQuery,
  issueTypesQuery,
  labelsQuery,
  releasesQuery,
  scopedSettingsQuery,
  teamsQuery,
  transitionsQuery,
  usersQuery,
} from "../../lib/queries";
import {
  ConditionOp,
  ItemKind,
  Permission,
  Priority,
  SettingScope,
  TransitionCheck,
  TransitionMode,
  WORKFLOW_TRANSITION_MODE_KEY,
  type ApproverEntry,
  type ConditionOpValue,
  type FieldConditionParams,
  type FieldDef,
  type Project,
  type State,
  type Transition,
  type TransitionCreate,
  type TransitionRule,
  type TransitionUpdate,
} from "../../lib/types";
import { Button } from "../Button";
import { SelectField } from "../SelectField";
import { SubjectPicker, type Subject } from "./SubjectPicker";
import { TokenMultiSelect, type TokenOption } from "../TokenMultiSelect";

/** Any-state wildcard sentinel for the from-state selects ("" = NULL). */
const ANY_STATE = "";

// Plain-language enforcement labels live in lib/meta (shared with the generic
// scoped-settings editor's enumerated select — spec 107 cleanup).

// --- the condition catalog (mirrors workflow/types.py BUILTIN_OPS) ---

type ValueSource =
  | "none"
  | "user"
  | "team"
  | "priority"
  | "kind"
  | "label"
  | "type"
  | "cycle"
  | "release"
  | "date"
  | "number"
  | "boolean"
  | "text"
  | "select";

interface FieldChoice {
  kind: "builtin" | "custom";
  key: string;
  label: string;
  ops: ConditionOpValue[];
  source: ValueSource;
  options?: string[];
}

const MEMBER_OPS: ConditionOpValue[] = [
  ConditionOp.set,
  ConditionOp.empty,
  ConditionOp.is,
  ConditionOp.isNot,
];
const PRESENCE_OPS: ConditionOpValue[] = [ConditionOp.set, ConditionOp.empty];
const RANGE_OPS: ConditionOpValue[] = [
  ConditionOp.set,
  ConditionOp.empty,
  ConditionOp.gte,
  ConditionOp.lte,
];

const BUILTIN_CHOICES: FieldChoice[] = [
  { kind: "builtin", key: "assignee", label: "Assignee", ops: MEMBER_OPS, source: "user" },
  { kind: "builtin", key: "reporter", label: "Reporter", ops: MEMBER_OPS, source: "user" },
  { kind: "builtin", key: "team", label: "Team", ops: MEMBER_OPS, source: "team" },
  { kind: "builtin", key: "priority", label: "Priority", ops: MEMBER_OPS, source: "priority" },
  { kind: "builtin", key: "labels", label: "Labels", ops: MEMBER_OPS, source: "label" },
  { kind: "builtin", key: "type", label: "Issue type", ops: MEMBER_OPS, source: "type" },
  { kind: "builtin", key: "kind", label: "Kind", ops: MEMBER_OPS, source: "kind" },
  { kind: "builtin", key: "cycle", label: "Cycle", ops: MEMBER_OPS, source: "cycle" },
  { kind: "builtin", key: "release", label: "Release", ops: MEMBER_OPS, source: "release" },
  { kind: "builtin", key: "start_date", label: "Start date", ops: RANGE_OPS, source: "date" },
  { kind: "builtin", key: "target_date", label: "Target date", ops: RANGE_OPS, source: "date" },
  { kind: "builtin", key: "estimate", label: "Estimate", ops: PRESENCE_OPS, source: "none" },
  { kind: "builtin", key: "comment", label: "Comment", ops: PRESENCE_OPS, source: "none" },
];

/** A custom registry field as a condition choice (ops mirror the server's
 * ops_for_field_type). */
function customChoice(field: FieldDef): FieldChoice {
  const base = { kind: "custom" as const, key: field.key, label: field.name };
  switch (field.type) {
    case "number":
    case "duration":
      return { ...base, ops: [...MEMBER_OPS, ConditionOp.gte, ConditionOp.lte], source: "number" };
    case "date":
      return { ...base, ops: RANGE_OPS, source: "date" };
    case "boolean":
      return {
        ...base,
        ops: [ConditionOp.set, ConditionOp.empty, ConditionOp.is],
        source: "boolean",
      };
    case "user":
      return { ...base, ops: MEMBER_OPS, source: "user" };
    case "select":
    case "multi_select":
      return { ...base, ops: MEMBER_OPS, source: "select", options: field.options ?? [] };
    default:
      return { ...base, ops: MEMBER_OPS, source: "text" }; // text, url
  }
}

const choiceId = (entry: { kind: string; key: string }) => `${entry.kind}:${entry.key}`;

function opLabel(op: ConditionOpValue, source: ValueSource): string {
  switch (op) {
    case ConditionOp.set:
      return "is set";
    case ConditionOp.empty:
      return "is empty";
    case ConditionOp.is:
      return "is";
    case ConditionOp.isNot:
      return "is not";
    case ConditionOp.gte:
      return source === "date" ? "is on or after" : "is at least";
    default:
      return source === "date" ? "is on or before" : "is at most";
  }
}

const needsValues = (op: ConditionOpValue) => op !== ConditionOp.set && op !== ConditionOp.empty;
const singleValue = (op: ConditionOpValue) => op === ConditionOp.gte || op === ConditionOp.lte;

/** A row is PATCHable once its operator has the values it needs. */
const conditionComplete = (params: FieldConditionParams) =>
  !needsValues(params.op) || (params.values?.length ?? 0) > 0;

const isCondition = (
  rule: TransitionRule,
): rule is Extract<TransitionRule, { check: typeof TransitionCheck.requireField }> =>
  rule.check === TransitionCheck.requireField;

const approvalEntriesOf = (rules: TransitionRule[]): ApproverEntry[] | undefined => {
  const rule = rules.find((entry) => entry.check === TransitionCheck.requireApproval);
  return rule && rule.check === TransitionCheck.requireApproval
    ? rule.params.approvers
    : undefined;
};

/** The require_field conditions as a bare list (the editor's working shape). */
const conditionsOf = (rules: TransitionRule[]): FieldConditionParams[] =>
  rules.filter(isCondition).map((rule) => rule.params);

/** Rebuild the rules array from the two edited halves (approval sorts last —
 * evaluation puts its failure last anyway). */
const rebuildRules = (
  conditions: FieldConditionParams[],
  approval: ApproverEntry[] | null | undefined,
): TransitionRule[] => [
  ...conditions.map((params) => ({ check: TransitionCheck.requireField, params })),
  ...(approval && approval.length > 0
    ? [{ check: TransitionCheck.requireApproval, params: { approvers: approval } }]
    : []),
];

/**
 * "Transitions" section of the project Workflow settings page (specs 61/107):
 * the enforcement-mode select (a scoped scalar, spec-50 cascade) plus the
 * transition-row editor — a CONDITION BUILDER (field → operator → value) over
 * builtins + custom fields, and per-entry approver rules. Row edits PATCH
 * immediately, like the states list.
 */
export function TransitionsSection({
  project,
  states,
  canManage,
}: {
  project: Project;
  states: State[];
  canManage: boolean;
}) {
  const perms = usePermissions();
  const transitions = useQuery(transitionsQuery(project.id));
  const fields = useQuery(fieldsQuery());
  // The project's field registry: global fields + this project's own.
  const choices = [
    ...BUILTIN_CHOICES,
    ...(fields.data ?? [])
      .filter((field) => fieldInScope(field, project.id))
      .map(customChoice),
  ];

  return (
    <section className="mt-8">
      <h3 className="text-sm font-medium text-heading">Transitions</h3>
      <p className="mt-1 text-xs text-fg-muted">
        Optional guards on state changes: each transition lists the conditions an item must
        meet (and the approvals it needs) before it may move, and can be scoped to specific
        issues via &quot;Applies when&quot;. A transition without a &quot;from&quot; applies
        from every state. Rows are checked top-down — the FIRST transition whose
        &quot;Applies when&quot; matches the item governs its move (so put specific rows
        above general ones; a row with no conditions above a general one is an exemption).
      </p>
      {/* Mode read/write requires project.manage (the scoped-settings gate). */}
      {perms.project(project, Permission.projectManage) && (
        <ModeSetting projectId={project.id} />
      )}
      <ul className="mt-3 rounded-lg border border-subtle">
        {(transitions.data ?? []).map((transition, index, all) => (
          <TransitionRow
            key={transition.id}
            transition={transition}
            neighbours={[all[index - 1], all[index + 1]]}
            states={states}
            choices={choices}
            project={project}
            canManage={canManage}
          />
        ))}
        {transitions.data?.length === 0 && (
          <li className="px-4 py-4 text-center text-xs text-fg-muted">
            No transitions defined — every state change is allowed.
          </li>
        )}
      </ul>
      {canManage && <AddTransitionForm projectId={project.id} states={states} />}
    </section>
  );
}

/** The workflow_transition_mode scalar at project scope (same idiom as the
 * ScopedSettingsEditor rows: effective value + Set here/Inherited + Reset).
 * Options carry friendly labels; the registry description renders below. */
function ModeSetting({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const query = useQuery(scopedSettingsQuery(SettingScope.project, projectId));
  const row = query.data?.find((entry) => entry.key === WORKFLOW_TRANSITION_MODE_KEY);
  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: ["scoped-settings", SettingScope.project, projectId],
    });
    invalidateEntities(queryClient, Entity.transition);
  };

  const save = useMutation({
    mutationFn: (value: string) =>
      api.put(ApiPath.scopedSettings, {
        scope: SettingScope.project,
        scope_id: projectId,
        key: WORKFLOW_TRANSITION_MODE_KEY,
        value,
      }),
    onSuccess: invalidate,
  });
  const reset = useMutation({
    mutationFn: () =>
      api.delete(ApiPath.scopedSettings, {
        query: {
          scope: SettingScope.project,
          scope_id: projectId,
          key: WORKFLOW_TRANSITION_MODE_KEY,
        },
      }),
    onSuccess: invalidate,
  });

  if (!row) return null;
  return (
    <div className="mt-3">
      <div className="flex items-end gap-2">
        <SelectField
          label="Enforcement"
          value={String(row.value)}
          onChange={(event) => save.mutate(event.target.value)}
          disabled={save.isPending}
        >
          {Object.values(TransitionMode).map((mode) => (
            <option key={mode} value={mode}>
              {TRANSITION_MODE_LABELS[mode]}
            </option>
          ))}
        </SelectField>
        <span
          className={
            "mb-2 rounded px-1.5 py-px text-[10px] " +
            (row.set_here ? "bg-accent/15 text-accent-text" : "text-fg-faint")
          }
        >
          {row.set_here ? "Set here" : "Inherited"}
        </span>
        {row.set_here && (
          <Button
            variant="ghost"
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
            title={`Reset to the inherited default (${String(row.default)})`}
          >
            <RotateCcw size={13} aria-hidden />
          </Button>
        )}
        {(save.isError || reset.isError) && (
          <span className="mb-2 text-xs text-red-400">
            {errorMessage(save.error ?? reset.error)}
          </span>
        )}
      </div>
      {row.description && (
        <p className="mt-1 max-w-2xl text-[11px] text-fg-faint">{row.description}</p>
      )}
    </div>
  );
}

/** One transition row: from/to selects, the condition builder, approver rules,
 * reorder + delete. */
function TransitionRow({
  transition,
  neighbours,
  states,
  choices,
  project,
  canManage,
}: {
  transition: Transition;
  neighbours: [Transition | undefined, Transition | undefined];
  states: State[];
  choices: FieldChoice[];
  project: Project;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const me = useCurrentUser();
  const patch = useMutation({
    mutationFn: (body: TransitionUpdate) =>
      api.patch<Transition>(apiTransitionPath(transition.id), body),
    onSettled: () => invalidateEntities(queryClient, Entity.transition),
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiTransitionPath(transition.id)),
    onSettled: () => invalidateEntities(queryClient, Entity.transition),
  });
  // Swap `position` with a neighbour (the ordered list re-sorts on refetch).
  const swapWith = (other: Transition | undefined) => {
    if (!other) return;
    patch.mutate({ position: other.position });
    void api
      .patch<Transition>(apiTransitionPath(other.id), { position: transition.position })
      .then(() => invalidateEntities(queryClient, Entity.transition));
  };

  const patchRules = (rules: TransitionRule[]) => patch.mutate({ rules });
  const approval = approvalEntriesOf(transition.rules);

  return (
    <li className="border-b border-subtle/60 px-4 py-3 last:border-b-0">
      <div className="flex items-end gap-2">
        <SelectField
          label="From"
          value={transition.from_state_id ?? ANY_STATE}
          onChange={(event) =>
            patch.mutate({ from_state_id: event.target.value || null })
          }
          disabled={!canManage || patch.isPending}
        >
          <option value={ANY_STATE}>Any state</option>
          {states.map((state) => (
            <option key={state.id} value={state.id}>
              {state.name}
            </option>
          ))}
        </SelectField>
        <ArrowRight size={14} className="mb-2.5 shrink-0 text-fg-faint" aria-hidden />
        <SelectField
          label="To"
          value={transition.to_state_id}
          onChange={(event) => patch.mutate({ to_state_id: event.target.value })}
          disabled={!canManage || patch.isPending}
        >
          {states.map((state) => (
            <option key={state.id} value={state.id}>
              {state.name}
            </option>
          ))}
        </SelectField>
        {canManage && (
          <div className="mb-1 ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => swapWith(neighbours[0])}
              disabled={!neighbours[0]}
              aria-label="Move transition up"
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg disabled:opacity-30 cursor-pointer"
            >
              <ArrowUp size={13} />
            </button>
            <button
              type="button"
              onClick={() => swapWith(neighbours[1])}
              disabled={!neighbours[1]}
              aria-label="Move transition down"
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg disabled:opacity-30 cursor-pointer"
            >
              <ArrowDown size={13} />
            </button>
            <button
              type="button"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              aria-label="Delete transition"
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
            >
              <Trash2 size={13} />
            </button>
          </div>
        )}
      </div>

      {/* Which items this row governs (spec 107 follow-up) — empty = all;
          rows resolve FIRST-MATCH in list order. */}
      <ConditionListEditor
        conditions={transition.applies_when ?? []}
        choices={choices}
        project={project}
        canManage={canManage}
        pending={patch.isPending}
        label="Applies when"
        emptyText="Every issue — add a condition to scope this transition (e.g. Issue type is Bug)."
        addPrompt="+ Scope by a field…"
        onChange={(conditions) => patch.mutate({ applies_when: conditions })}
      />

      <ConditionListEditor
        conditions={conditionsOf(transition.rules)}
        choices={choices}
        project={project}
        canManage={canManage}
        pending={patch.isPending}
        label="Conditions"
        emptyText="None — the move is not gated on item data."
        addPrompt="+ Add a condition…"
        onChange={(conditions) => patchRules(rebuildRules(conditions, approval))}
      />

      <label className="mt-2 flex items-center gap-1.5 text-xs text-fg">
        <input
          type="checkbox"
          checked={approval !== undefined}
          onChange={() =>
            patchRules(
              rebuildRules(
                conditionsOf(transition.rules),
                approval !== undefined || !me
                  ? null
                  : // Seed with the configuring user (server 409s on empty).
                    [{ kind: "user", id: me.id, name: me.name }],
              ),
            )
          }
          disabled={!canManage || patch.isPending || (approval === undefined && !me)}
          className="size-3.5 accent-accent"
        />
        Require approval
      </label>
      {approval !== undefined && (
        <ApproversEditor
          entries={approval}
          canManage={canManage}
          pending={patch.isPending}
          onChange={(entries) =>
            patchRules(rebuildRules(conditionsOf(transition.rules), entries))
          }
        />
      )}
      {(patch.isError || remove.isError) && (
        <p className="mt-1 text-xs text-red-400">
          {errorMessage(patch.error ?? remove.error)}
        </p>
      )}
    </li>
  );
}

/** A bare condition-list builder (field → operator → value per row, plus an
 * add select) — mounted twice per transition row: "Applies when" (which items
 * the row governs, spec 107 follow-up) and "Conditions" (what the move
 * requires). Rows commit as soon as they're complete; an operator waiting on
 * values holds locally with a hint. */
function ConditionListEditor({
  conditions,
  choices,
  project,
  canManage,
  pending,
  label,
  emptyText,
  addPrompt,
  onChange,
}: {
  conditions: FieldConditionParams[];
  choices: FieldChoice[];
  project: Project;
  canManage: boolean;
  pending: boolean;
  label: string;
  emptyText: string;
  addPrompt: string;
  onChange: (conditions: FieldConditionParams[]) => void;
}) {
  // Rows whose operator still needs values live here until committable.
  const [drafts, setDrafts] = useState<Record<number, FieldConditionParams>>({});

  const clearDraft = (index: number) =>
    setDrafts((current) => {
      const next = { ...current };
      delete next[index];
      return next;
    });

  const commit = (index: number, params: FieldConditionParams) => {
    if (conditionComplete(params)) {
      clearDraft(index);
      onChange(conditions.map((entry, i) => (i === index ? params : entry)));
    } else {
      setDrafts((current) => ({ ...current, [index]: params }));
    }
  };

  const removeAt = (index: number) => {
    clearDraft(index);
    onChange(conditions.filter((_, i) => i !== index));
  };

  const seed = (choice: FieldChoice): FieldConditionParams => ({
    kind: choice.kind,
    key: choice.key,
    op: choice.ops[0], // "set" everywhere — immediately valid
  });

  return (
    <div className="mt-2 flex flex-col gap-1.5">
      <span className="text-[11px] uppercase tracking-wide text-fg-faint">{label}</span>
      {conditions.length === 0 && (
        <p className="text-[11px] text-fg-faint">{emptyText}</p>
      )}
      {conditions.map((params, index) => (
        <ConditionRow
          key={`${index}:${choiceId(params)}`}
          params={drafts[index] ?? params}
          choices={choices}
          project={project}
          disabled={!canManage || pending}
          incomplete={drafts[index] !== undefined}
          onChange={(next) => commit(index, next)}
          onRemove={() => removeAt(index)}
        />
      ))}
      {canManage && (
        <div className="max-w-64">
          <SelectField
            label=""
            value=""
            onChange={(event) => {
              const choice = choices.find((entry) => choiceId(entry) === event.target.value);
              if (choice) onChange([...conditions, seed(choice)]);
            }}
            disabled={pending}
          >
            <option value="">{addPrompt}</option>
            <optgroup label="Fields">
              {BUILTIN_CHOICES.map((choice) => (
                <option key={choiceId(choice)} value={choiceId(choice)}>
                  {choice.label}
                </option>
              ))}
            </optgroup>
            {choices.some((choice) => choice.kind === "custom") && (
              <optgroup label="Custom fields">
                {choices
                  .filter((choice) => choice.kind === "custom")
                  .map((choice) => (
                    <option key={choiceId(choice)} value={choiceId(choice)}>
                      {choice.label}
                    </option>
                  ))}
              </optgroup>
            )}
          </SelectField>
        </div>
      )}
    </div>
  );
}

/** One condition: [field] [operator] [value control]. Switching field reseeds
 * the operator to "is set"; switching to a value operator waits for values. */
function ConditionRow({
  params,
  choices,
  project,
  disabled,
  incomplete,
  onChange,
  onRemove,
}: {
  params: FieldConditionParams;
  choices: FieldChoice[];
  project: Project;
  disabled: boolean;
  incomplete: boolean;
  onChange: (params: FieldConditionParams) => void;
  onRemove: () => void;
}) {
  const choice = choices.find((entry) => choiceId(entry) === choiceId(params));

  if (!choice) {
    // The field left the registry since the rule was written.
    return (
      <div className="flex items-center gap-2 text-xs text-amber-400">
        Condition on unknown field <span className="font-mono">{params.key}</span>
        {!disabled && (
          <button type="button" onClick={onRemove} aria-label="Remove condition"
            className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer">
            <X size={12} />
          </button>
        )}
      </div>
    );
  }

  const setOp = (op: ConditionOpValue) => {
    if (!needsValues(op)) {
      onChange({ kind: params.kind, key: params.key, op });
      return;
    }
    const values = (params.values ?? []).slice(0, singleValue(op) ? 1 : undefined);
    const display = (params.display ?? []).slice(0, values.length);
    onChange({ ...params, op, values, display });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <SelectField
        label=""
        value={choiceId(params)}
        onChange={(event) => {
          const next = choices.find((entry) => choiceId(entry) === event.target.value);
          if (next) onChange({ kind: next.kind, key: next.key, op: next.ops[0] });
        }}
        disabled={disabled}
      >
        <optgroup label="Fields">
          {choices
            .filter((entry) => entry.kind === "builtin")
            .map((entry) => (
              <option key={choiceId(entry)} value={choiceId(entry)}>
                {entry.label}
              </option>
            ))}
        </optgroup>
        {choices.some((entry) => entry.kind === "custom") && (
          <optgroup label="Custom fields">
            {choices
              .filter((entry) => entry.kind === "custom")
              .map((entry) => (
                <option key={choiceId(entry)} value={choiceId(entry)}>
                  {entry.label}
                </option>
              ))}
          </optgroup>
        )}
      </SelectField>
      <SelectField
        label=""
        value={params.op}
        onChange={(event) => setOp(event.target.value as ConditionOpValue)}
        disabled={disabled}
      >
        {choice.ops.map((op) => (
          <option key={op} value={op}>
            {opLabel(op, choice.source)}
          </option>
        ))}
      </SelectField>
      {needsValues(params.op) && (
        <ConditionValues
          choice={choice}
          project={project}
          single={singleValue(params.op)}
          values={params.values ?? []}
          disabled={disabled}
          onChange={(values, display) => onChange({ ...params, values, display })}
        />
      )}
      {incomplete && <span className="text-[11px] text-amber-400">choose a value</span>}
      {!disabled && (
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove condition"
          className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
        >
          <X size={13} />
        </button>
      )}
    </div>
  );
}

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

/** The typed value control for a condition row. Entity values ride ids with
 * display names alongside (failure strings quote the names). */
function ConditionValues({
  choice,
  project,
  single,
  values,
  disabled,
  onChange,
}: {
  choice: FieldChoice;
  project: Project;
  single: boolean;
  values: string[];
  disabled: boolean;
  onChange: (values: string[], display: string[]) => void;
}) {
  const users = useQuery({ ...usersQuery, enabled: choice.source === "user" });
  const teams = useQuery({ ...teamsQuery(), enabled: choice.source === "team" });
  const labels = useQuery({ ...labelsQuery(), enabled: choice.source === "label" });
  const types = useQuery({
    ...issueTypesQuery(project.id),
    enabled: choice.source === "type",
  });
  const cycles = useQuery({ ...cyclesQuery(), enabled: choice.source === "cycle" });
  const releases = useQuery({
    ...releasesQuery(project.id),
    enabled: choice.source === "release",
  });

  if (choice.source === "date") {
    return (
      <input
        type="date"
        value={values[0] ?? ""}
        onChange={(event) =>
          onChange(event.target.value ? [event.target.value] : [], [event.target.value])
        }
        disabled={disabled}
        className="h-8 rounded-md border border-strong bg-surface px-2 text-xs text-fg"
      />
    );
  }
  if (choice.source === "number" && single) {
    return (
      <input
        type="number"
        value={values[0] ?? ""}
        onChange={(event) =>
          onChange(event.target.value ? [event.target.value] : [], [event.target.value])
        }
        disabled={disabled}
        className="h-8 w-24 rounded-md border border-strong bg-surface px-2 text-xs text-fg"
      />
    );
  }
  if (choice.source === "boolean") {
    return (
      <SelectField
        label=""
        value={values[0] ?? "true"}
        onChange={(event) => onChange([event.target.value], [event.target.value])}
        disabled={disabled}
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </SelectField>
    );
  }

  let options: TokenOption[] = [];
  let allowCreate = false;
  switch (choice.source) {
    case "user":
      options = (users.data ?? [])
        .filter((user) => user.active !== false)
        // No hint: the member-floor directory carries no email (RADD-769), and
        // the address was decoration here rather than the stored value.
        .map((user) => ({ value: user.id, label: user.name }));
      break;
    case "team":
      options = (teams.data ?? []).map((team) => ({ value: team.id, label: team.name }));
      break;
    case "label":
      options = (labels.data ?? []).map((label) => ({ value: label.id, label: label.name }));
      break;
    case "type":
      options = (types.data ?? []).map((type) => ({ value: type.id, label: type.name }));
      break;
    case "cycle":
      options = (cycles.data ?? []).map((cycle) => ({ value: cycle.id, label: cycle.name }));
      break;
    case "release":
      options = (releases.data ?? []).map((release) => ({
        value: release.id,
        label: release.version,
      }));
      break;
    case "priority":
      options = Object.values(Priority).map((value) => ({
        value,
        label: capitalize(value),
      }));
      break;
    case "kind":
      options = Object.values(ItemKind).map((value) => ({
        value,
        label: capitalize(value),
      }));
      break;
    case "select":
      options = (choice.options ?? []).map((value) => ({ value, label: value }));
      break;
    default: // text / number multi — free-typed values
      allowCreate = true;
      break;
  }
  const labelFor = (value: string) =>
    options.find((option) => option.value === value)?.label ?? value;

  return (
    <div className="min-w-52 flex-1">
      <TokenMultiSelect
        value={values}
        onChange={(next) => onChange(next, next.map(labelFor))}
        options={options}
        allowCreate={allowCreate}
        disabled={disabled}
        ariaLabel={`${choice.label} values`}
        placeholder="Choose values…"
      />
    </div>
  );
}

/** Per-entry approver rules (spec 107): every listed person must approve;
 * a team entry needs N approvals from its current members. */
function ApproversEditor({
  entries,
  canManage,
  pending,
  onChange,
}: {
  entries: ApproverEntry[];
  canManage: boolean;
  pending: boolean;
  onChange: (entries: ApproverEntry[]) => void;
}) {
  const users = useQuery(usersQuery);
  const teams = useQuery(teamsQuery());
  const subjects: Subject[] = [
    ...(teams.data ?? []).map((team) => ({
      type: "team" as const,
      id: team.id,
      name: team.name,
    })),
    ...(users.data ?? [])
      .filter((user) => user.active)
      .map((user) => ({ type: "user" as const, id: user.id, name: user.name })),
  ].filter(
    (subject) =>
      !entries.some((entry) => entry.kind === subject.type && entry.id === subject.id),
  );

  const setRequired = (index: number, required: number) => {
    if (!Number.isInteger(required) || required < 1) return;
    onChange(entries.map((entry, i) => (i === index ? { ...entry, required } : entry)));
  };

  return (
    <div className="mt-2 flex flex-col gap-1.5 rounded-md border border-subtle bg-surface/40 px-3 py-2">
      <span className="text-[11px] uppercase tracking-wide text-fg-faint">
        Approvers — every entry must be satisfied
      </span>
      {entries.map((entry, index) => (
        <div
          key={`${entry.kind}:${entry.id}`}
          className="flex flex-wrap items-center gap-2 text-xs text-fg"
        >
          {entry.kind === "team" ? (
            <Users size={13} className="text-fg-muted" aria-hidden />
          ) : (
            <UserIcon size={13} className="text-fg-muted" aria-hidden />
          )}
          <span>{entry.name ?? entry.id}</span>
          {entry.kind === "team" && (
            <label className="flex items-center gap-1.5 text-[11px] text-fg-secondary">
              — requires
              <input
                type="number"
                min={1}
                value={entry.required ?? 1}
                onChange={(event) => setRequired(index, Number(event.target.value))}
                disabled={!canManage || pending}
                className="h-6 w-14 rounded border border-strong bg-surface px-1.5 text-xs text-fg"
              />
              member approval(s)
            </label>
          )}
          {canManage && (
            <button
              type="button"
              onClick={() => onChange(entries.filter((_, i) => i !== index))}
              disabled={pending}
              aria-label={`Remove approver ${entry.name ?? entry.id}`}
              className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
            >
              <X size={12} />
            </button>
          )}
        </div>
      ))}
      {canManage && (
        <div className="max-w-72">
          <SubjectPicker
            subjects={subjects}
            value={null}
            onChange={(subject) => {
              if (!subject) return;
              onChange([
                ...entries,
                {
                  kind: subject.type as "user" | "team",
                  id: subject.id,
                  name: subject.name,
                  ...(subject.type === "team" ? { required: 1 } : {}),
                },
              ]);
            }}
            placeholder="Add a person or team…"
          />
        </div>
      )}
    </div>
  );
}

/** Add a transition edge (POST /transitions); rules are edited on the row. */
function AddTransitionForm({ projectId, states }: { projectId: string; states: State[] }) {
  const queryClient = useQueryClient();
  const [fromId, setFromId] = useState<string>(ANY_STATE);
  const [toId, setToId] = useState<string>("");

  const create = useMutation({
    mutationFn: (body: TransitionCreate) => api.post<Transition>(ApiPath.transitions, body),
    onSuccess: () => setToId(""),
    onSettled: () => invalidateEntities(queryClient, Entity.transition),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!toId) return;
    create.mutate({ project_id: projectId, from_state_id: fromId || null, to_state_id: toId });
  };

  return (
    <form onSubmit={onSubmit} className="mt-3 flex items-end gap-2">
      <SelectField
        label="From"
        value={fromId}
        onChange={(event) => setFromId(event.target.value)}
      >
        <option value={ANY_STATE}>Any state</option>
        {states.map((state) => (
          <option key={state.id} value={state.id}>
            {state.name}
          </option>
        ))}
      </SelectField>
      <ArrowRight size={14} className="mb-2.5 shrink-0 text-fg-faint" aria-hidden />
      <SelectField label="To" value={toId} onChange={(event) => setToId(event.target.value)}>
        <option value="">Choose a state…</option>
        {states.map((state) => (
          <option key={state.id} value={state.id}>
            {state.name}
          </option>
        ))}
      </SelectField>
      <Button type="submit" disabled={create.isPending || !toId}>
        <Plus size={14} aria-hidden />
        {create.isPending ? "Adding…" : "Add transition"}
      </Button>
      {create.isError && (
        <span className="pb-2 text-xs text-red-400">{errorMessage(create.error)}</span>
      )}
    </form>
  );
}
