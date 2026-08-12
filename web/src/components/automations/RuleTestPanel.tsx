import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleSlash, FlaskConical } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiAutomationTestPath } from "../../lib/constants";
import { ACTION_TYPE_LABELS } from "../../lib/meta";
import { itemsQuery, projectsQuery } from "../../lib/queries";
import type {
  ActionPreview,
  AutomationNode,
  NodeResult,
  RuleTestResult,
  RuleTrigger,
} from "../../lib/types";
import { Button, ButtonVariant } from "../Button";
import { SelectField } from "../SelectField";
import { PORT_TONE } from "./node-visuals";

interface RuleTestPanelProps {
  ruleId: string;
  /** The saved graph's triggers — a run starts at ONE of them. */
  triggers?: RuleTrigger[];
  /** The saved graph's nodes, for labelling results by type. */
  nodes?: AutomationNode[];
  /** Hand the result up so the canvas can label its ports with it. */
  onResult?: (result: RuleTestResult | null) => void;
}

/**
 * Dry run: what the graph WOULD do, per node (spec 20, rebuilt by RADD-921).
 *
 * It used to report one boolean and a flat list of actions — the shape of a
 * linear rule. A graph branches, so the questions people actually have are
 * "which items came out of my filter" and "why is this branch empty", and
 * neither was answerable: you could see that six actions would apply and not
 * which node produced them, or against which item.
 *
 * Two changes make it usable on a real graph. The seed item is OPTIONAL, since a
 * graph fed by a search node or a schedule has no triggering issue and demanding
 * one made exactly those the graphs that could not be checked. And every node
 * reports what ARRIVED and what LEFT by each port, with sample keys — a count
 * answers "did my filter narrow anything", a sample answers "did it keep the
 * right ones".
 */
export function RuleTestPanel({ ruleId, triggers = [], nodes = [], onResult }: RuleTestPanelProps) {
  const projects = useQuery(projectsQuery());
  const [projectId, setProjectId] = useState("");
  const [itemId, setItemId] = useState("");
  const [triggerId, setTriggerId] = useState("");
  const effectiveProjectId = projectId || projects.data?.[0]?.id || "";
  const items = useQuery({
    ...itemsQuery(effectiveProjectId),
    enabled: Boolean(effectiveProjectId),
  });

  const test = useMutation({
    mutationFn: () =>
      api.post<RuleTestResult>(apiAutomationTestPath(ruleId), {
        item_id: itemId || null,
        trigger_node_id: triggerId || null,
      }),
    onSuccess: (result) => onResult?.(result),
  });

  const result = test.data;
  const byId = new Map(nodes.map((node) => [node.id, node]));

  return (
    <div className="flex flex-col gap-3 rounded-md border border-subtle bg-surface/40 p-3">
      <div className="flex items-center gap-2">
        <FlaskConical size={14} className="text-accent-text" aria-hidden />
        <span className="text-xs font-medium text-fg">Dry run</span>
        <span className="text-[11px] text-fg-muted">
          Runs every node with the appliers off — nothing is written.
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2.5">
        <SelectField
          label="Start at"
          value={triggerId}
          onChange={(event) => setTriggerId(event.target.value)}
          hint={triggers.length > 1 ? "This graph has several entry points." : undefined}
        >
          <option value="">First trigger</option>
          {triggers.map((trigger) => (
            <option key={trigger.node_id} value={trigger.node_id}>
              {trigger.node_id} — {trigger.event_type}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Project"
          value={effectiveProjectId}
          onChange={(event) => {
            setProjectId(event.target.value);
            setItemId("");
          }}
        >
          {(projects.data ?? []).map((project) => (
            <option key={project.id} value={project.id}>
              {project.key} — {project.name}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="As if it fired for"
          value={itemId}
          onChange={(event) => setItemId(event.target.value)}
          // A search- or schedule-fed graph produces its OWN items, so no seed
          // is the correct input rather than a missing one.
          hint="Optional — leave empty for a graph that finds its own items"
        >
          <option value="">No item</option>
          {(items.data ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.key} — {item.title}
            </option>
          ))}
        </SelectField>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={() => test.mutate()} disabled={test.isPending}>
          {test.isPending ? "Running…" : "Run"}
        </Button>
        {result && (
          <Button
            variant={ButtonVariant.ghost}
            size="sm"
            onClick={() => {
              test.reset();
              onResult?.(null);
            }}
          >
            Clear
          </Button>
        )}
        {test.isError && <span className="text-xs text-red-400">{errorMessage(test.error)}</span>}
      </div>

      {result && (
        <div className="flex flex-col gap-2">
          {result.dropped.length > 0 && (
            // Surfaced, never buried: a run that did less and a run that had
            // less to do are indistinguishable otherwise.
            <ul className="flex flex-col gap-0.5 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1.5">
              {result.dropped.map((line, index) => (
                <li key={index} className="text-[11px] text-amber-300">
                  {line}
                </li>
              ))}
            </ul>
          )}

          {result.findings.length > 0 && (
            // A VALIDATION graph's whole output (spec 119). Without this a dry
            // run of one shows port counts and no actions — accurate, and
            // useless, since findings are the only thing it produces.
            <ul
              data-test-findings
              className="flex flex-col gap-0.5 rounded border border-status-danger/30 bg-status-danger/5 px-2 py-1.5"
            >
              {result.findings.map((finding, index) => (
                <li key={index} className="text-[11px] text-fg">
                  <span className="font-mono text-fg-muted">{finding.node_id}</span>
                  {finding.field && <span className="text-fg-muted"> · {finding.field}</span>}{" "}
                  {finding.message}
                </li>
              ))}
            </ul>
          )}

          <ul className="flex flex-col gap-1">
            {result.nodes.map((node) => (
              <NodeRow key={node.node_id} node={node} type={byId.get(node.node_id)?.type} />
            ))}
          </ul>

          {result.would_apply.length > 0 ? (
            <>
              <p className="text-[11px] uppercase tracking-wide text-fg-muted">Would apply</p>
              <ul className="flex flex-col gap-1">
                {result.would_apply.map((preview, index) => (
                  <ActionPreviewRow key={index} preview={preview} />
                ))}
              </ul>
            </>
          ) : (
            <p className="flex items-center gap-1.5 text-[13px]">
              <CircleSlash size={14} className="text-fg-muted" aria-hidden />
              <span className="text-fg-secondary">Nothing would apply on this run</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function NodeRow({ node, type }: { node: NodeResult; type?: string }) {
  return (
    <li
      data-node-result={node.node_id}
      className={`flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded border border-subtle/80 bg-base/40 px-2.5 py-1.5 text-xs ${
        node.ran ? "" : "opacity-60"
      }`}
    >
      <span className="font-medium text-fg">{node.node_id}</span>
      <span className="text-[11px] text-fg-muted">{type ?? node.type}</span>
      {!node.ran ? (
        // Never reached — detached from the trigger, or out of budget. Distinct
        // from a node that ran and produced nothing.
        <span className="text-[11px] text-fg-faint">did not run</span>
      ) : (
        <>
          <span className="text-[11px] text-fg-secondary" title={node.incoming_sample.join(", ")}>
            in {node.incoming}
            {node.incoming_sample.length > 0 && ` (${node.incoming_sample.slice(0, 4).join(", ")})`}
          </span>
          {node.ports.map((port) => (
            <span
              key={port.port}
              data-port-result={port.port}
              title={port.sample.join(", ")}
              className={`text-[11px] ${port.taken ? "" : "line-through opacity-60"}`}
              style={{ color: port.taken ? PORT_TONE[port.port] : undefined }}
            >
              {port.port} {port.taken ? port.count : "not taken"}
              {port.taken && port.sample.length > 0 && ` · ${port.sample.slice(0, 4).join(", ")}`}
            </span>
          ))}
        </>
      )}
    </li>
  );
}

function ActionPreviewRow({ preview }: { preview: ActionPreview }) {
  return (
    <li className="flex items-center gap-2 rounded border border-subtle/80 bg-base/40 px-2.5 py-1.5 text-xs">
      <span
        className={
          "rounded px-1.5 py-px text-[10px] uppercase tracking-wide " +
          (preview.resolves
            ? "bg-emerald-500/15 text-emerald-300"
            : "bg-amber-500/15 text-amber-300")
        }
      >
        {preview.resolves ? "Would apply" : "Skipped"}
      </span>
      <span className="font-medium text-fg">{ACTION_TYPE_LABELS[preview.type]}</span>
      {/* Which node, against which item — a graph runs the same action type from
          several nodes and, per item, once each. */}
      {preview.node_id && <span className="text-[11px] text-fg-faint">{preview.node_id}</span>}
      {preview.item_key && <span className="text-[11px] text-fg-secondary">{preview.item_key}</span>}
      <span className="truncate text-fg-muted">{preview.detail}</span>
    </li>
  );
}
