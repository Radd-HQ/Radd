import { Plus, Trash2 } from "lucide-react";
import {
  ConditionGroupOp,
  ConditionSubject,
  type AutomationCatalog,
  type ConditionGroup,
  type ConditionGroupOpValue,
  type EventCondition,
  type TriggerInfo,
} from "../../lib/types";
import { Select } from "../Select";

/** Node type guard: groups have `op` + `conditions`, leaves have `subject`. */
export function isGroup(node: ConditionGroup | EventCondition): node is ConditionGroup {
  return "conditions" in node;
}

const GROUP_OP_LABELS: Record<ConditionGroupOpValue, string> = {
  [ConditionGroupOp.all]: "ALL of the following",
  [ConditionGroupOp.any]: "ANY of the following",
  [ConditionGroupOp.none]: "NONE of the following",
};

const MAX_DEPTH = 5;

function emptyCondition(): EventCondition {
  return { subject: ConditionSubject.actor, operator: "eq", value: "" };
}

/** A saveable leaf: qualifier present where required, value present where required. */
export function isConditionValid(
  node: ConditionGroup | EventCondition,
  catalog: AutomationCatalog,
): boolean {
  if (isGroup(node)) {
    return node.conditions.length > 0 && node.conditions.every((c) => isConditionValid(c, catalog));
  }
  const subject = catalog.subjects.find((s) => s.key === node.subject);
  const operator = catalog.operators.find((o) => o.key === node.operator);
  if (!subject || !operator) return false;
  if (subject.needs_qualifier && !(node.qualifier ?? "").trim()) return false;
  if (operator.needs_value) {
    const value = node.value;
    if (value === null || value === undefined) return false;
    if (typeof value === "string" && value.trim() === "") return false;
    if (Array.isArray(value) && value.length === 0) return false;
  }
  return true;
}

interface ConditionsBuilderProps {
  catalog: AutomationCatalog;
  trigger: TriggerInfo | undefined; // undefined = manual (no event to condition on)
  value: ConditionGroup | null;
  onChange: (value: ConditionGroup | null) => void;
}

/**
 * The event-condition builder (spec 58): a nestable ALL/ANY/NONE tree of
 * subject–operator–value rows evaluated against the triggering event —
 * who acted, which fields changed, old/new values, raw payload paths.
 * Complements the SLQ condition below it (which matches the item's state).
 */
export function ConditionsBuilder({ catalog, trigger, value, onChange }: ConditionsBuilderProps) {
  if (!trigger) return null;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px] font-medium text-fg">
        Event conditions{" "}
        <span className="font-normal text-fg-muted">— empty matches every event</span>
      </p>
      {value ? (
        <GroupEditor
          catalog={catalog}
          trigger={trigger}
          group={value}
          depth={1}
          onChange={onChange}
          onRemove={() => onChange(null)}
        />
      ) : (
        <button
          type="button"
          onClick={() => onChange({ op: ConditionGroupOp.all, conditions: [emptyCondition()] })}
          className="w-fit rounded-md border border-dashed border-strong px-3 py-1.5 text-xs text-fg-secondary hover:border-emphasis hover:text-fg cursor-pointer"
        >
          <Plus size={12} className="mr-1 inline" aria-hidden />
          Add event conditions
        </button>
      )}
    </div>
  );
}

function GroupEditor({
  catalog,
  trigger,
  group,
  depth,
  onChange,
  onRemove,
}: {
  catalog: AutomationCatalog;
  trigger: TriggerInfo;
  group: ConditionGroup;
  depth: number;
  onChange: (group: ConditionGroup) => void;
  onRemove: () => void;
}) {
  const replaceChild = (index: number, child: ConditionGroup | EventCondition) =>
    onChange({
      ...group,
      conditions: group.conditions.map((c, i) => (i === index ? child : c)),
    });
  const removeChild = (index: number) => {
    const rest = group.conditions.filter((_, i) => i !== index);
    if (rest.length === 0) onRemove();
    else onChange({ ...group, conditions: rest });
  };

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-subtle bg-surface/30 p-3">
      <div className="flex items-center gap-2">
        <Select
          aria-label="Group combinator"
          value={group.op}
          onChange={(op) => onChange({ ...group, op: op as ConditionGroupOpValue })}
          size="sm"
          options={Object.entries(GROUP_OP_LABELS).map(([op, label]) => ({ value: op, label }))}
        />
        <span className="text-[11px] text-fg-faint">must hold</span>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove group"
          className="ml-auto rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
        >
          <Trash2 size={13} aria-hidden />
        </button>
      </div>

      {group.conditions.map((child, index) =>
        isGroup(child) ? (
          <GroupEditor
            key={index}
            catalog={catalog}
            trigger={trigger}
            group={child}
            depth={depth + 1}
            onChange={(next) => replaceChild(index, next)}
            onRemove={() => removeChild(index)}
          />
        ) : (
          <ConditionRow
            key={index}
            catalog={catalog}
            trigger={trigger}
            condition={child}
            onChange={(next) => replaceChild(index, next)}
            onRemove={() => removeChild(index)}
          />
        ),
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange({ ...group, conditions: [...group.conditions, emptyCondition()] })}
          className="rounded-md border border-subtle px-2 py-1 text-[11px] text-fg-secondary hover:border-strong hover:text-fg cursor-pointer"
        >
          <Plus size={11} className="mr-1 inline" aria-hidden />
          Condition
        </button>
        {depth < MAX_DEPTH && (
          <button
            type="button"
            onClick={() =>
              onChange({
                ...group,
                conditions: [
                  ...group.conditions,
                  { op: ConditionGroupOp.any, conditions: [emptyCondition()] },
                ],
              })
            }
            className="rounded-md border border-subtle px-2 py-1 text-[11px] text-fg-secondary hover:border-strong hover:text-fg cursor-pointer"
          >
            <Plus size={11} className="mr-1 inline" aria-hidden />
            Nested group
          </button>
        )}
      </div>
    </div>
  );
}

function ConditionRow({
  catalog,
  trigger,
  condition,
  onChange,
  onRemove,
}: {
  catalog: AutomationCatalog;
  trigger: TriggerInfo;
  condition: EventCondition;
  onChange: (condition: EventCondition) => void;
  onRemove: () => void;
}) {
  // Diff-based subjects only make sense on triggers that carry a change diff.
  const subjects = catalog.subjects.filter(
    (subject) => !subject.requires_changes || trigger.has_changes,
  );
  const subject = catalog.subjects.find((s) => s.key === condition.subject);
  const operator = catalog.operators.find((o) => o.key === condition.operator);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Select
        aria-label="Condition subject"
        value={condition.subject}
        onChange={(key) => {
          const next = catalog.subjects.find((s) => s.key === key);
          onChange({
            ...condition,
            subject: key as EventCondition["subject"],
            qualifier: next?.needs_qualifier ? (condition.qualifier ?? "") : null,
          });
        }}
        size="sm"
        options={subjects.map((s) => ({ value: s.key, label: s.label }))}
      />

      {subject?.needs_qualifier && (
        <input
          aria-label="Condition qualifier"
          value={condition.qualifier ?? ""}
          onChange={(event) => onChange({ ...condition, qualifier: event.target.value })}
          placeholder={subject.qualifier_hint}
          className="h-7 w-44 rounded-md border border-strong bg-surface px-2 text-xs text-fg placeholder:text-fg-faint"
        />
      )}

      <Select
        aria-label="Condition operator"
        value={condition.operator}
        onChange={(operator) => onChange({ ...condition, operator })}
        size="sm"
        options={catalog.operators.map((o) => ({ value: o.key, label: o.label }))}
      />

      {operator?.needs_value && (
        <input
          aria-label="Condition value"
          value={
            Array.isArray(condition.value)
              ? condition.value.join(", ")
              : String(condition.value ?? "")
          }
          onChange={(event) =>
            onChange({
              ...condition,
              value: operator.list_value
                ? event.target.value.split(",").map((part) => part.trim())
                : event.target.value,
            })
          }
          placeholder={operator.list_value ? "value, value, …" : "value"}
          className="h-7 w-48 rounded-md border border-strong bg-surface px-2 text-xs text-fg placeholder:text-fg-faint"
        />
      )}

      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove condition"
        className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
      >
        <Trash2 size={13} aria-hidden />
      </button>
    </div>
  );
}
