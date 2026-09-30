/** The selected node's parameter form, beside the canvas. */
import { useMemo } from "react";
import { useAutomationQuery as useQuery } from "./query-lifetime";

import { Trash2 } from "lucide-react";
import { eventSampleQuery } from "./queries";
import type { ActionParamValue as CustomFieldValue } from "./types";
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
} from "./types";
import { arityForcedReason, groupBy, normalizeActionParams } from "./automation-nodes";
import { reachable } from "./automation-layout";
import { arityOf, effectiveArity, isProducer, nodeNameError, outputsOfNode } from "./automation-outputs";
import { CheckField } from "./controls";
import { ActionParams } from "./ActionParams";
import { ArityField } from "./ArityField";
import { CreateItemFields } from "./CreateItemFields";
import { SchemaForm } from "@radd/plugin-sdk";
import { ACTION_TYPE_PREFIX, hasCoreEditor, isBuiltinAction } from "./builtin-actions";
import { ContributedNodeFields } from "./ContributedNodeFields";
import { useTokenTarget } from "./useTokenTarget";
import { EventSamples } from "./EventSamples";
import { SearchFields } from "./SearchFields";
import { ValidateTriggerFields, VerdictFields } from "./ValidationFields";
import { TokenReference } from "./TokenReference";
import { ChangedByFields, FieldChangedFields, StateCategoryFields, CommentGateFields, PageSpaceFields, PayloadGateFields, ProjectGateFields, PersonInTeamFields } from "./GateFields";
import type { PickerData } from "./ActionsBuilder";
import { Button, ButtonVariant } from "@radd/plugin-sdk";
import { TextField } from "@radd/plugin-sdk";
import { SelectField } from "@radd/plugin-sdk";
import ScheduleEditor from "./ScheduleEditor";
import { defaultSchedule } from "@radd/plugin-sdk";

import type { NodeShapes } from "./shape-contract";

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
  const groupedTriggers = useMemo(() => groupBy(catalog?.triggers ?? [], (trigger) => trigger.group), [catalog]);
  // Trigger KINDS (RADD-1323), grouped the same way — served, so a plugin's
  // kind appears here with no SPA change.
  const groupedKinds = useMemo(() => groupBy(catalog?.trigger_kinds ?? [], (kind) => kind.group), [catalog]);
  const firedKind =
    node?.kind === NodeKind.trigger
      ? catalog?.trigger_kinds.find((kind) => kind.key === String(node.params.event ?? ""))
      : undefined;

  // Both hooks sit ABOVE the early return (React forbids conditional hooks). What the upstream
  // trigger's real events carry, which the field-changed picker offers first:
  const upstreamSample = useQuery(eventSampleQuery(trigger?.event_type ?? ""));
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
  // Every node is a catalog entry (RADD-1322); core types carry their own forms, the rest a plugin's.
  const contributed = catalog?.nodes?.find((entry) => entry.key === node.type);
  const coreEdited = hasCoreEditor(node.type);
  // `action.*` nodes carry the action chrome (Act as, Run, insertable tokens) whoever draws their
  // params: the built-ins here, a moved one (`action.send_email`, RADD-1387) in its plugin.
  const actionNode = node.kind === NodeKind.action && node.type.startsWith(ACTION_TYPE_PREFIX);
  const forcedReason = arityForcedReason(node);
  // Asked of type AND params — `ai.generate` produces `text` before any field exists.
  const produces = isProducer(node, catalog, shapes);
  const nameError = nodeNameError(String(node.name ?? ""), node, nodes, catalog);
  // Upstream checks that publish findings — what a verdict node may relay.
  const relayableChecks = (() => {
    const upstream = reachable(edges, [node.id], "upstream");
    const publishing = new Set((catalog?.nodes ?? []).filter((entry) => entry.produces_findings).map((entry) => entry.key));
    return nodes
      .filter((candidate) => candidate.id !== node.id && upstream.has(candidate.id) && publishing.has(candidate.type))
      .map((candidate) => ({
        id: candidate.id,
        label: `${catalog?.nodes.find((entry) => entry.key === candidate.type)?.label ?? candidate.type}${candidate.name ? ` (${candidate.name})` : ""} · ${candidate.id}`,
      }));
  })();
  // Tokens render only in ACTION params (see TokenReference) — elsewhere the list is reference only.
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

      {/* Only on producers: naming is what makes their outputs addressable (spec 120). */}
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
              // A kind change changes which params are legal: rebuild from its defaults, keeping known keys.
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
            {node.params.event && !catalog?.triggers.some(trigger => trigger.event_type === node.params.event)
              && !catalog?.trigger_kinds.some(kind => kind.key === node.params.event)
              ? <option value={String(node.params.event)}>{String(node.params.event)} (unavailable trigger)</option> : null}
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

          {/* Sampled from real events — the one thing here that cannot be wrong about the payload. */}
          <EventSamples eventType={String(node.params.event ?? "")} />

          {/* A plugin's trigger kind renders its own params from its schema. */}
          {firedKind && ![SCHEDULE_TRIGGER, VALIDATE_TRIGGER, MANUAL_TRIGGER].includes(firedKind.key) &&
            Object.keys(firedKind.params_schema ?? {}).length > 0 && (
              <SchemaForm
                schema={firedKind.params_schema}
                params={node.params}
                onChange={(params) => setParams({ ...params, event: firedKind.key })}
              />
            )}

          {/* Chaining is opt-in, and only an event trigger offers it (RADD-1315). */}
          {(!firedKind || firedKind.has_event) && (
            <CheckField
              data-trigger-include-automated
              label="Also run on changes made by other automations"
              hint={<>
                Off: only people and integrations start this automation. On: another automation's change
                starts it too — never this automation's own, and at most {catalog?.max_chain_depth ?? 3} automations deep.
              </>}
              checked={Boolean(node.params.include_automated)}
              onChange={(checked) => {
                const params: Record<string, unknown> = { ...node.params };
                if (checked) params.include_automated = true;
                else delete params.include_automated;
                setParams(params);
              }}
            />
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
      {node.type === "gate.person_in_team" && (
        <PersonInTeamFields params={node.params} canChoosePeople={pickers.canChoosePeople} onChange={setParams} />
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

      {/* A plugin node renders its own `automation.node.inspector`; else the served schema form. */}
      {contributed && !coreEdited && !actionNode && (
        <div className="flex flex-col gap-2">
          <ContributedNodeFields node={node} entry={contributed} onChange={setParams} />
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

      {actionNode && (
        <div className="flex flex-col gap-2">
          {/* Only with automation.act_as — a field refused on save is worse than an absent one. */}
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
            {contributed?.label ?? node.type}
          </div>
          {node.type === "action.create_item" ? (
            <CreateItemFields params={node.params} pickers={pickers} onChange={setActionParams} />
          ) : !isBuiltinAction(node.type) ? (
            // Never blocks the save: the plugin's own inspector, or a line naming who provides it.
            <ContributedNodeFields node={node} entry={contributed} onChange={setParams} showProvider />
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
