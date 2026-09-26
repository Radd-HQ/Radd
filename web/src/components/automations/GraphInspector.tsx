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
  VERDICT_BLOCK_TYPE,
  VERDICT_WARN_TYPE,
  type AutomationCatalog,
  type AutomationEdge,
  type AutomationNode,
  type RuleAction,
  type RuleSchedule,
  type TriggerInfo,
  type TriggerKindInfo,
} from "../../lib/types";
import {
  arityForcedReason,
  arityOf,
  effectiveArity,
  normalizeActionParams,
} from "../../lib/automation-nodes";
import { isProducer, nodeNameError, outputsOfNode } from "../../lib/automation-outputs";
import { ActionParams } from "./ActionParams";
import { ArityField } from "./ArityField";
import { CreateItemFields } from "./CreateItemFields";
import { SchemaForm } from "@radd/plugin-sdk";
import { Slot, SlotId } from "@radd/plugin-sdk";
import { useTokenTarget } from "./useTokenTarget";
import { EventSamples } from "./EventSamples";
import { SearchFields } from "./SearchFields";
import { ValidateTriggerFields, VerdictFields } from "./ValidationFields";
import { TokenReference } from "./TokenReference";
import {
  ChangedByFields,
  FieldChangedFields,
  StateCategoryFields,
  CommentGateFields,
  PageSpaceFields,
  PayloadGateFields,
  ProjectGateFields,
} from "./GateFields";
import type { PickerData } from "./ActionsBuilder";
const ACTION_TYPE_PREFIX = "action.";
import { Button, ButtonVariant } from "../Button";
import { TextField } from "../TextField";
import { SelectField } from "../SelectField";
import { ScheduleEditor, defaultSchedule } from "./ScheduleEditor";

import type { NodeShapes } from "../../lib/node-shapes";

interface GraphInspectorProps {
  shapes?: NodeShapes;
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
  onChange: (node: AutomationNode) => void;
  onDelete: (nodeId: string) => void;
}

/** Node types whose form lives in core — the built-in actions (`ActionParams`),
 * the named gates, the SLQ filter and source, the verdict nodes and the trigger.
 * Everything else renders from its served `params_schema`. */
const CORE_EDITED_TYPES = new Set([
  "trigger.event",
  "filter.slq",
  "search.slq",
  "gate.payload",
  "gate.project",
  "gate.field_changed",
  "gate.changed_by",
  "gate.state_category",
  "gate.comment",
  "gate.page_space",
  VERDICT_BLOCK_TYPE,
  VERDICT_WARN_TYPE,
]);

function hasCoreEditor(type: string): boolean {
  return CORE_EDITED_TYPES.has(type) || type.startsWith(ACTION_TYPE_PREFIX);
}

export function GraphInspector({
  shapes,
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
  // Trigger KINDS (RADD-1323), grouped the same way — served, so a plugin's
  // kind appears here with no SPA change.
  const groupedKinds = useMemo(() => {
    const grouped = new Map<string, TriggerKindInfo[]>();
    for (const kind of catalog?.trigger_kinds ?? []) {
      grouped.set(kind.group, [...(grouped.get(kind.group) ?? []), kind]);
    }
    return [...grouped.entries()];
  }, [catalog]);
  const firedKind =
    node?.kind === NodeKind.trigger
      ? catalog?.trigger_kinds.find((kind) => kind.key === String(node.params.event ?? ""))
      : undefined;

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
  const contributed = catalog?.nodes?.find((entry) => entry.key === node.type);
  //: RADD-1322 made EVERY node a catalog entry, so "is it in the catalog" no
  //: longer means "has no editor of its own". The core types below carry their
  //: own forms; anything else gets the one generated from its schema.
  const coreEdited = hasCoreEditor(node.type);
  const forcedReason = arityForcedReason(node);
  //: Whether naming this node would make anything addressable (spec 120). Asked
  //: of the type AND its params, because `ai.generate` produces `text` before a
  //: single field has been added.
  const produces = isProducer(node, catalog, shapes);
  const nameError = nodeNameError(String(node.name ?? ""), node, nodes, catalog);
  //: Checks upstream that publish findings (RADD-1329) — what a verdict node
  //: may relay. Walked BACKWARDS from this node, so only a check that can
  //: actually feed it is offered.
  const relayableChecks = (() => {
    const upstream = new Set<string>([node.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const edge of edges) {
        if (upstream.has(edge.target) && !upstream.has(edge.source)) {
          upstream.add(edge.source);
          grew = true;
        }
      }
    }
    const publishing = new Set((catalog?.nodes ?? []).filter((entry) => entry.produces_findings).map((entry) => entry.key));
    return nodes
      .filter((candidate) => candidate.id !== node.id && upstream.has(candidate.id) && publishing.has(candidate.type))
      .map((candidate) => ({
        id: candidate.id,
        label: `${catalog?.nodes.find((entry) => entry.key === candidate.type)?.label ?? candidate.type}${candidate.name ? ` (${candidate.name})` : ""} · ${candidate.id}`,
      }));
  })();
  //: Two panels, and the difference is load-bearing. `planning._plan` is the
  //: ONLY place tokens are rendered, and it renders an ACTION's params — so a
  //: token inserted into a contributed node's own prompt reaches the model as
  //: literal braces, and one inserted into a filter's SLQ compiles to nothing.
  //: The list is still worth SHOWING there (it is what the node above produces);
  //: offering to insert into it is not.
  const tokenPanel = (insertable: boolean) => (
    <TokenReference
      shapes={shapes}
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
              : `Read downstream as ${outputsOfNode(node, catalog, shapes)
                  .slice(0, 2)
                  .map((output) => `{{${node.name || "name"}.${output.name}}}`)
                  .join(", ")}`
          }
          onChange={(event) => onChange({ ...node, name: event.target.value })}
        />
      )}

      {node.kind === NodeKind.filter && (
        <TextField
          label="Match issues where"
          value={String(node.params.slq ?? "")}
          onChange={(event) => setParams({ ...node.params, slq: event.target.value })}
          placeholder="priority = high AND state != Done"
          hint="SLQ. Issues that match leave on the green port; the rest leave on the grey one."
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
              // Switching kind changes which params are legal — the server
              // rejects a schedule on an event trigger and vice versa — so the
              // shape is rebuilt from the kind's own defaults (RADD-1323),
              // keeping whatever this node already had for those keys.
              const params: Record<string, unknown> = { event: next };
              const nextKind = catalog?.trigger_kinds.find((entry) => entry.key === next);
              for (const [key, fallback] of Object.entries(nextKind?.default_params ?? {})) {
                params[key] = node.params[key] ?? fallback;
              }
              if (next === SCHEDULE_TRIGGER && !params.schedule) params.schedule = defaultSchedule("interval");
              onChange({ ...node, params });
            }}
            hint={
              node.params.event === SCHEDULE_TRIGGER
                ? "Runs on a clock, with no issues of its own — wire a Find issues node after it to select what each run acts on."
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
            {groupedKinds.map(([group, entries]) => (
              <optgroup key={`kind:${group}`} label={group}>
                {entries.map((entry) => (
                  <option key={entry.key} value={entry.key}>
                    {entry.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </SelectField>

          {/* What this event actually carries. Sampled from real events, so it
              is the only thing on this page that cannot be wrong about the
              payload someone is about to write a condition against. A validate
              trigger has no event, so there is nothing to sample. */}
          {node.params.event !== VALIDATE_TRIGGER && (
            <EventSamples eventType={String(node.params.event ?? "")} />
          )}

          {/* RADD-1315: automation chaining is opt-in, per trigger. Only an EVENT
              trigger reacts to changes, so the sentinels do not offer it (and the
              server refuses it on them). */}
          {/* A plugin's trigger kind renders its own params from its schema. */}
          {firedKind && ![SCHEDULE_TRIGGER, VALIDATE_TRIGGER, MANUAL_TRIGGER].includes(firedKind.key) &&
            Object.keys(firedKind.params_schema ?? {}).length > 0 && (
              <SchemaForm
                schema={firedKind.params_schema}
                params={node.params}
                onChange={(params) => setParams({ ...params, event: firedKind.key })}
              />
            )}

          {(!firedKind || firedKind.has_event) && (
            <label className="flex cursor-pointer items-start gap-2 text-[13px] text-fg">
              <input
                type="checkbox"
                data-trigger-include-automated
                checked={Boolean(node.params.include_automated)}
                onChange={(event) => {
                  const params: Record<string, unknown> = { ...node.params };
                  if (event.target.checked) params.include_automated = true;
                  else delete params.include_automated;
                  setParams(params);
                }}
                className="mt-0.5 size-3.5 cursor-pointer accent-[var(--accent-fill)]"
              />
              <span>
                Also run on changes made by other automations
                <span className="block text-xs text-fg-secondary">
                  Off: only people and integrations start this automation. On: another automation's change
                  starts it too — never this automation's own, and at most {catalog?.max_chain_depth ?? 3} automations deep.
                </span>
              </span>
            </label>
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

      {node.type === "gate.project" && (
        <ProjectGateFields params={node.params} onChange={setParams} />
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

      {/* A plugin's node renders the inspector its OWN UI bundle registered
          for its type (RADD-1325: `automation.node.inspector`) — the AI and
          scripts editors live in those plugins now, and core knows no plugin
          node type. With none registered, the form generated from the node's
          served params_schema (RADD-923). */}
      {contributed && !coreEdited && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-fg-secondary">{contributed.description}</p>
          <Slot
            id={SlotId.automationNodeInspector}
            match={node.type}
            node={node}
            params={node.params}
            schema={contributed.params_schema}
            onChange={setParams}
            fallback={
              <SchemaForm schema={contributed.params_schema} params={node.params} onChange={setParams} />
            }
          />
          {tokenPanel(false)}
        </div>
      )}

      {(node.type === VERDICT_BLOCK_TYPE || node.type === VERDICT_WARN_TYPE) && (
        <VerdictFields
          params={node.params}
          fields={pickers.fields}
          blocks={node.type === VERDICT_BLOCK_TYPE}
          checks={relayableChecks}
          onChange={setParams}
        />
      )}

      {node.kind === NodeKind.action && node.type.startsWith(ACTION_TYPE_PREFIX) && (
        <div className="flex flex-col gap-2">
          {/* Act as (spec 116). Rendered ONLY when the caller holds
              automation.act_as — a field that is refused on save is worse than
              one that is absent, and the server enforces the same atom. */}
          {canActAs && (
            <TextField
              label="Act as"
              value={String(node.params.act_as ?? "")}
              onChange={(event) => setParams({ ...node.params, act_as: event.target.value, act_as_id: undefined })}
              placeholder="Defaults to you (the automation's author)"
              hint="Email of the person this action runs as. Their permissions apply, and the change is attributed to them."
            />
          )}
          <div className="text-xs text-fg-secondary">
            {catalog?.nodes.find((entry) => entry.key === node.type)?.label ?? node.type}
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
