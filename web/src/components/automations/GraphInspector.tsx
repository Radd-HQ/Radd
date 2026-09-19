/**
 * Editing the selected node's parameters, beside the canvas (spec 116, RADD-916).
 *
 * Action params reuse `ActionParams` — the same component the list editor uses —
 * so an action configured on the canvas and one configured in the form are
 * literally the same inputs with the same validation. A second set of param
 * widgets would be two things to keep in step, and they would drift.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { eventSampleQuery } from "../../lib/queries";
import type { CustomFieldValue } from "../../lib/types";
import {
  MANUAL_TRIGGER,
  NodeArity,
  NodeKind,
  SCHEDULE_TRIGGER,
  VALIDATE_TRIGGER,
  VALIDATION_FAIL_TYPE,
  type ActionTypeValue,
  type AutomationCatalog,
  type AutomationEdge,
  type AutomationNode,
  type RuleAction,
  type RuleSchedule,
  type TriggerInfo,
} from "../../lib/types";
import { ACTION_TYPE_LABELS } from "../../lib/meta";
import {
  arityForcedReason,
  arityOf,
  effectiveArity,
  normalizeActionParams,
} from "../../lib/automation-nodes";
import { isProducer, nodeNameError, outputsOfNode } from "../../lib/automation-outputs";
import { feedbackPortsOf } from "./node-visuals";
import { ActionParams } from "./ActionParams";
import { ArityField } from "./ArityField";
import { CreateItemFields } from "./CreateItemFields";
import { SchemaFields } from "./SchemaFields";
import { GenerateFields } from "./GenerateFields";
import { useTokenTarget } from "./useTokenTarget";
import { EventSamples } from "./EventSamples";
import { SearchFields } from "./SearchFields";
import { ValidateTriggerFields, ValidationFailFields } from "./ValidationFields";
import { TokenReference } from "./TokenReference";
import {
  AiClassifyFields,
  ChangedByFields,
  FieldChangedFields,
  StateCategoryFields,
  CommentGateFields,
  PageSpaceFields,
  PayloadGateFields,
} from "./GateFields";
import type { PickerData } from "./ActionsBuilder";
const ACTION_TYPE_PREFIX = "action.";
import { Button, ButtonVariant } from "../Button";
import { TextField } from "../TextField";
import { SelectField } from "../SelectField";
import { ScheduleEditor, defaultSchedule } from "../ScheduleEditor";

interface GraphInspectorProps {
  node: AutomationNode | null;
  /** The whole graph, so the token picker can list only the producers this node
   * can be reached FROM and the name field can refuse a duplicate (spec 120). */
  nodes?: AutomationNode[];
  edges?: AutomationEdge[];
  pickers: PickerData;
  /** For the trigger picker and the gate's condition subjects/operators. */
  catalog?: AutomationCatalog;
  /** The trigger(s) upstream of the selected node, merged — decides which
   * condition subjects a gate may use. */
  trigger?: TriggerInfo;
  /** Field names the "field changed" picker offers. */
  fieldNames?: string[];
  /** Value suggestions for that field (state names, priorities). */
  valueSuggestions?: string[];
  /** Whether the caller may set Act as at all. */
  canActAs?: boolean;
  /** Whether this graph's triggers resolve a target item — decides whether the
   * token reference marks the item tokens as blank. */
  hasItem?: boolean;
  /** Whether any trigger runs at INTAKE (RADD-1074) — decides whether a check's
   * findings are delivered to a submitter or are merely a routing decision. */
  validation?: boolean;
  onChange: (node: AutomationNode) => void;
  onDelete: (nodeId: string) => void;
}

export function GraphInspector({
  node,
  nodes = [],
  edges = [],
  pickers,
  catalog,
  trigger,
  fieldNames = [],
  valueSuggestions = [],
  canActAs = false,
  hasItem = true,
  validation = false,
  onChange,
  onDelete,
}: GraphInspectorProps) {
  const groupedTriggers = useMemo(() => {
    const grouped = new Map<string, TriggerInfo[]>();
    for (const trigger of catalog?.triggers ?? []) {
      grouped.set(trigger.group, [...(grouped.get(trigger.group) ?? []), trigger]);
    }
    return [...grouped.entries()];
  }, [catalog]);

  // What the UPSTREAM trigger's real events carry — the field-changed picker
  // offers those first. ABOVE the early return: a hook after one runs
  // conditionally, which React forbids. Keyed by event type, so selecting a
  // different node in the same graph reuses the cached answer.
  const upstreamSample = useQuery(eventSampleQuery(trigger?.event_type ?? ""));
  // Where a clicked token lands. ABOVE the early return, like the query above:
  // a hook after one runs conditionally, which React forbids.
  const tokenTarget = useTokenTarget();

  if (!node) {
    return (
      <div className="rounded-[8px] border border-dashed border-subtle px-3 py-6 text-center text-xs text-fg-muted">
        Select a node to edit it
      </div>
    );
  }

  const setParams = (params: Record<string, unknown>) => onChange({ ...node, params });
  // Choosing a role recipient implies per-item, so the params are corrected on
  // the edit that causes it rather than by a control that argues with itself.
  const setActionParams = (params: Record<string, unknown>) =>
    setParams(normalizeActionParams(node, params));
  const arityRule = arityOf(catalog, node.type);
  //: The registered spec, when this node came from a plugin rather than the
  //: built-in palette. Its params are its own business — never the action union.
  const contributed = catalog?.contributed_nodes?.find((entry) => entry.key === node.type);
  const forcedReason = arityForcedReason(node);
  //: Whether naming this node would make anything addressable (spec 120). Asked
  //: of the type AND its params, because `ai.generate` produces `text` before a
  //: single field has been added.
  const produces = isProducer(node, catalog);
  const nameError = nodeNameError(String(node.name ?? ""), node, nodes, catalog);
  //: The one line this node's own form cannot say for itself (RADD-1074): a
  //: finding is DELIVERED, so the empty port under it is a choice, not a gap.
  const feedbackPorts = feedbackPortsOf(node.type, validation);
  const feedbackNote = feedbackPorts.length > 0 && (
    <p data-feedback-note className="text-xs text-fg-secondary">
      Findings from this check are shown to whoever submitted the draft
      automatically — they are the intake verdict. Wiring anything after{" "}
      <code className="text-accent-text">{feedbackPorts.join(" / ")}</code> is optional, for
      when a failed check should also do something else.
    </p>
  );
  //: Two panels, and the difference is load-bearing. `planning._plan` is the
  //: ONLY place tokens are rendered, and it renders an ACTION's params — so a
  //: token inserted into a contributed node's own prompt reaches the model as
  //: literal braces, and one inserted into a filter's SLQ compiles to nothing.
  //: The list is still worth SHOWING there (it is what the node above produces);
  //: offering to insert into it is not.
  const tokenPanel = (insertable: boolean) => (
    <TokenReference
      catalog={catalog}
      hasItem={hasItem}
      node={node}
      nodes={nodes}
      edges={edges}
      onInsert={insertable ? tokenTarget.insert : undefined}
    />
  );

  return (
    <div
      className="flex flex-col gap-3 rounded-[8px] border border-subtle bg-surface p-3"
      onFocusCapture={tokenTarget.onFocusCapture}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wide text-fg-muted">{node.kind}</div>
          <div className="truncate text-[13px] font-medium text-heading">{node.type}</div>
        </div>
        {/* A trigger cannot be removed: every graph starts at exactly one, and
            deleting it would make the automation unsaveable rather than empty. */}
        {node.kind !== NodeKind.trigger && (
          <Button type="button" variant={ButtonVariant.dangerGhost} size="sm" onClick={() => onDelete(node.id)}>
            <Trash2 size={12} aria-hidden /> Delete
          </Button>
        )}
      </div>

      {/* A PRODUCER is named so downstream nodes can read it (spec 120). Only
          shown where naming buys something: on the fourteen node types that
          produce nothing, a name field would be a control with no effect. */}
      {produces && (
        <TextField
          label="Name (for tokens)"
          value={String(node.name ?? "")}
          placeholder="triage"
          error={nameError || undefined}
          hint={
            nameError
              ? undefined
              : `Read downstream as ${outputsOfNode(node, catalog)
                  .slice(0, 2)
                  .map((output) => `{{${node.name || "name"}.${output.name}}}`)
                  .join(", ")}`
          }
          onChange={(event) => onChange({ ...node, name: event.target.value })}
        />
      )}

      {node.kind === NodeKind.filter && (
        <TextField
          label="Match items where"
          value={String(node.params.slq ?? "")}
          onChange={(event) => setParams({ ...node.params, slq: event.target.value })}
          placeholder="priority = high AND state != Done"
          hint="SLQ. Items that match leave on the green port; the rest leave on the grey one."
        />
      )}

      {node.kind === NodeKind.source && (
        <SearchFields params={node.params} onChange={setParams} />
      )}

      {node.kind === NodeKind.trigger && (
        <div className="flex flex-col gap-2">
          <SelectField
            label="Fires on"
            value={String(node.params.event ?? "")}
            onChange={(event) => {
              const next = event.target.value;
              // Switching to/from the schedule sentinel changes which params are
              // legal — the server rejects a schedule on an event trigger and
              // vice versa, so the shape is corrected here rather than 422ing.
              const params: Record<string, unknown> = { event: next };
              if (next === SCHEDULE_TRIGGER) {
                params.schedule = node.params.schedule ?? defaultSchedule("interval");
              }
              // The validate sentinel carries its BINDING, and the server
              // refuses a schedule on it — corrected here rather than 422ing.
              if (next === VALIDATE_TRIGGER) {
                params.targets = node.params.targets ?? [];
                params.mode = node.params.mode ?? "advisory";
              }
              onChange({ ...node, params });
            }}
            hint={
              node.params.event === SCHEDULE_TRIGGER
                ? "Runs on a clock, with no items of its own — wire a Find issues node after it to select what each run acts on."
                : "The event that starts this automation."
            }
          >
            {groupedTriggers.map(([group, entries]) => (
              <optgroup key={group} label={group}>
                {entries.map((entry) => (
                  <option key={entry.event_type} value={entry.event_type}>
                    {entry.label}
                  </option>
                ))}
              </optgroup>
            ))}
            <optgroup label="Scheduled">
              <option value={SCHEDULE_TRIGGER}>On a schedule</option>
            </optgroup>
            <optgroup label="Intake">
              <option value={VALIDATE_TRIGGER}>When someone submits (validate it)</option>
            </optgroup>
            <optgroup label="On demand">
              <option value={MANUAL_TRIGGER}>Manual (editor / menu)</option>
            </optgroup>
          </SelectField>

          {/* What this event actually carries. Sampled from real events, so it
              is the only thing on this page that cannot be wrong about the
              payload someone is about to write a condition against. A validate
              trigger has no event, so there is nothing to sample. */}
          {node.params.event !== VALIDATE_TRIGGER && (
            <EventSamples eventType={String(node.params.event ?? "")} />
          )}

          {node.params.event === VALIDATE_TRIGGER && (
            <ValidateTriggerFields params={node.params} onChange={setParams} />
          )}

          {node.params.event === SCHEDULE_TRIGGER && (
            <ScheduleEditor
              value={(node.params.schedule as RuleSchedule) ?? defaultSchedule("interval")}
              onChange={(schedule) => setParams({ ...node.params, schedule })}
            />
          )}
        </div>
      )}

      {node.type === "gate.payload" && (
        <PayloadGateFields
          params={node.params}
          operators={catalog?.operators ?? []}
          paths={upstreamSample.data?.paths.map((entry) => entry.path) ?? []}
          onChange={setParams}
        />
      )}
      {node.type === "gate.field_changed" && (
        <FieldChangedFields
          params={node.params}
          fieldNames={fieldNames}
          observedFields={upstreamSample.data?.changed_fields ?? []}
          valueSuggestions={valueSuggestions}
          onChange={setParams}
        />
      )}
      {node.type === "gate.changed_by" && (
        <ChangedByFields params={node.params} canChoosePeople={pickers.canChoosePeople} onChange={setParams} />
      )}
      {node.type === "gate.state_category" && (
        <StateCategoryFields params={node.params} onChange={setParams} />
      )}
      {node.type === "gate.comment" && (
        <CommentGateFields params={node.params} onChange={setParams} />
      )}
      {node.type === "gate.page_space" && (
        <PageSpaceFields params={node.params} onChange={setParams} />
      )}
      {node.type === "ai.classify" && (
        <AiClassifyFields params={node.params} onChange={setParams} />
      )}

      {/* Routers that can read either way. Per item turns a gate into a
          PARTITION — each issue leaves by its own answer's port — which is what
          people mean by "classify them one at a time". */}
      {(node.kind === NodeKind.gate || node.kind === NodeKind.filter) && (
        <ArityField
          rule={arityRule}
          value={effectiveArity(catalog, node)}
          onChange={(arity) => setParams({ ...node.params, arity })}
        />
      )}

      {/* A CONTRIBUTED node with no hardcoded editor gets a form generated from
          its own params_schema (RADD-923) — the promise AutomationNodeSpec made
          and nothing kept. `ai.classify` keeps its bespoke one above. */}
      {contributed && node.type !== "ai.classify" && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-fg-secondary">{contributed.description}</p>
          {/* `ai.generate` earns a bespoke form: its central param is an array
              of objects whose shape varies per row, which is exactly the case
              SchemaFields' docstring names as "ship your own component". */}
          {node.type === "ai.generate" ? (
            <GenerateFields
              schema={contributed.params_schema}
              params={node.params}
              onChange={setParams}
            />
          ) : (
            <SchemaFields
              schema={contributed.params_schema}
              params={node.params}
              onChange={setParams}
            />
          )}
          {tokenPanel(false)}
        </div>
      )}

      {node.type === VALIDATION_FAIL_TYPE && (
        <ValidationFailFields params={node.params} fields={pickers.fields} onChange={setParams} />
      )}

      {feedbackNote}

      {node.kind === NodeKind.action && !contributed && node.type !== VALIDATION_FAIL_TYPE && (
        <div className="flex flex-col gap-2">
          {/* Act as (spec 116). Rendered ONLY when the caller holds
              automation.act_as — a field that is refused on save is worse than
              one that is absent, and the server enforces the same atom. */}
          {canActAs && (
            <TextField
              label="Act as"
              value={String(node.params.act_as ?? "")}
              onChange={(event) => setParams({ ...node.params, act_as: event.target.value })}
              placeholder="Defaults to you (the automation's author)"
              hint="Email of the person this action runs as. Their permissions apply, and the change is attributed to them."
            />
          )}
          <div className="text-xs text-fg-secondary">
            {ACTION_TYPE_LABELS[node.type.slice(ACTION_TYPE_PREFIX.length) as ActionTypeValue] ?? node.type}
          </div>
          {node.type === "action.create_item" ? (
            <CreateItemFields params={node.params} pickers={pickers} onChange={setActionParams} />
          ) : (
          <ActionParams
            action={
              {
                type: node.type.slice(ACTION_TYPE_PREFIX.length),
                params: node.params as Record<string, CustomFieldValue>,
              } as RuleAction
            }
            pickers={pickers}
            listId={`node-${node.id}`}
            onParams={(params) => setActionParams(params)}
          />
          )}
          <ArityField
            rule={arityRule}
            value={effectiveArity(catalog, node)}
            forced={forcedReason ? { value: NodeArity.item, reason: forcedReason } : undefined}
            onChange={(arity) => setParams({ ...node.params, arity })}
          />
          {tokenPanel(true)}
        </div>
      )}
    </div>
  );
}
