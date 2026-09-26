/**
 * The automation editor (specs 20/58/69/116).
 *
 * Name, enabled, and the graph — that is the whole thing. The list-based form
 * that stood here until spec 116 is gone: it could not express a branch, and
 * keeping it beside the canvas meant a bidirectional adapter and two sources of
 * truth for one automation.
 *
 * A new automation opens on a placed, selected "Issue updated" trigger
 * (RADD-1265). It used to open empty on the theory that seeding a node would
 * teach the wrong lesson about where nodes come from; what it taught instead
 * was nothing, because the first thing a person met was a blank canvas. The
 * trigger's inspector is the question the editor should open on: fires on…
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAutomationQuery as useQuery } from "./query-lifetime";
import { useAutomationMutation as useMutation } from "./mutation-lifetime";

import { ArrowLeft, Check } from "lucide-react";
import { api } from "@radd/plugin-sdk";
import { ApiPath, apiAutomationPath } from "./constants";
import { automationCatalogQuery, invalidateAutomations } from "./queries";
import { positionedErrorOf as slqErrorOf } from "@radd/plugin-sdk";
import {
  type AutomationEdge,
  type AutomationNode,
  type Rule,
  type RuleCreate,
  type RuleTestResult,
  type RuleUpdate,
} from "./types";
import { Button } from "@radd/plugin-sdk";
import { ErrorText } from "@radd/plugin-sdk";
import { TextField } from "@radd/plugin-sdk";
import { incompleteActionNodeIds } from "./ActionsBuilder";
import { GraphEditor, type Orientation } from "./GraphEditor";
import { seededTrigger } from "./automation-nodes";
import { RuleTestPanel } from "./RuleTestPanel";
import { RunsPanel } from "./RunsPanel";
import { VersionsPanel } from "./VersionsPanel";
import { Slot, SlotId } from "@radd/plugin-sdk";

interface RuleEditorProps {
  /** The rule to edit, or null to create a new one. */
  rule: Rule | null;
  /** A new automation's starting graph — a template (RADD-1316). Opened
   * DISABLED: nothing runs until someone reads it, edits it and switches it on. */
  draft?: { name: string; nodes: AutomationNode[]; edges: AutomationEdge[] } | null;
  onDone: () => void;
}

export function RuleEditor({ rule, draft = null, onDone }: RuleEditorProps) {
  const queryClient = useQueryClient();
  const canAdopt = useQuery(automationCatalogQuery).data?.can_act_as;
  const [persistedId, setPersistedId] = useState<string | null>(rule?.id ?? null);
  const [name, setName] = useState(rule?.name ?? draft?.name ?? "");
  const [enabled, setEnabled] = useState(rule?.enabled ?? false);
  const [orientation, setOrientation] = useState<Orientation>(
    (rule?.orientation as Orientation) ?? "vertical",
  );
  // The last dry run. Held HERE rather than in the editor because the panel that
  // produces it and the canvas that draws it are siblings, and because it must
  // survive a node being selected — the whole point is to read the numbers while
  // clicking around the graph that produced them.
  const [run, setRun] = useState<RuleTestResult | null>(null);
  const [panel, setPanel] = useState<"dry-run" | "runs" | "versions">("dry-run");
  // "Why I changed this" — rides on the version the next save writes
  // (RADD-1268). Cleared after a save; a note about the last change is not a
  // note about the next one.
  const [note, setNote] = useState("");
  const [current, setCurrent] = useState<number>(rule?.version ?? 1);
  const [graph, setGraph] = useState<{ nodes: AutomationNode[]; edges: AutomationEdge[] }>({
    nodes: rule?.nodes ?? draft?.nodes ?? [seededTrigger()],
    edges: rule?.edges ?? draft?.edges ?? [],
  });

  const [adoptExecution, setAdoptExecution] = useState(false);
  const content = JSON.stringify({ name, enabled, orientation, ...graph });
  const [savedContent, setSavedContent] = useState(rule ? content : "");
  const currentContent = useRef(content);
  currentContent.current = content;
  const dirty = content !== savedContent || adoptExecution;
  useEffect(() => { setRun(null); }, [content]);

  // A graph with no nodes is not worth saving; one with no TRIGGER is, because
  // it is work in progress and the canvas already says it cannot run. A graph
  // with a HALF-CONFIGURED action is not (RADD-1104): saving it would only
  // bounce off the server's 422, and never-edit-then-error is the house rule.
  const incompleteActions = incompleteActionNodeIds(graph.nodes);
  const canSave =
    name.trim() !== "" && graph.nodes.length > 0 && incompleteActions.length === 0;

  const save = useMutation({
    mutationFn: async (_: void, signal) => {
      const payload = {
        name: name.trim(),
        enabled,
        orientation,
        nodes: graph.nodes,
        edges: graph.edges,
        note: note.trim(),
        ...(adoptExecution ? { adopt_execution: true } : {}),
      };
      const saved = await (persistedId
        ? api.patch<Rule>(apiAutomationPath(persistedId), payload satisfies RuleUpdate, {signal})
        : api.post<Rule>(ApiPath.automations, payload satisfies RuleCreate, {signal}));
      return { saved, submitted: content };
    },
    onSuccess: async ({ saved, submitted }) => {
      void invalidateAutomations(queryClient);
      setPersistedId(saved.id);
      if (currentContent.current === submitted) {
        setName(saved.name);
        setGraph({ nodes: saved.nodes, edges: saved.edges });
      }
      setSavedContent(JSON.stringify({ name: saved.name, enabled: saved.enabled, orientation: saved.orientation, nodes: saved.nodes, edges: saved.edges }));
      setAdoptExecution(false);
      setCurrent(saved.version);
      setNote("");
    },
  });

  const saveSlqError = save.isError ? slqErrorOf(save.error) : null;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={onDone}
          className="inline-flex items-center gap-1.5 text-xs text-fg-secondary hover:text-heading cursor-pointer"
        >
          <ArrowLeft size={13} aria-hidden />
          Back to automations
        </button>
        {!dirty && persistedId && !save.isPending && (
          <span className="inline-flex items-center gap-1 text-xs text-status-success-ink">
            <Check size={13} aria-hidden />
            Saved
          </span>
        )}
      </div>

      <div className="flex items-end gap-4">
        <div className="max-w-sm flex-1"><TextField
          label="Automation name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Auto-triage blockers"
          maxLength={200}
          required
          className="w-full"
        /></div>
        <label className="flex h-8 w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            className="size-3.5 cursor-pointer accent-[var(--accent-fill)]"
          />
          Enabled
        </label>
      </div>

      {dirty && <p className="text-xs text-status-warning-ink">Unsaved changes — dry run previews this draft.</p>}
      {persistedId && canAdopt && <label className="text-xs text-fg-muted"><input type="checkbox" checked={adoptExecution} onChange={event => setAdoptExecution(event.target.checked)} /> Use my account for execution on save (requires act-as permission)</label>}
      <GraphEditor
        nodes={graph.nodes}
        edges={graph.edges}
        orientation={orientation}
        onChange={setGraph}
        onOrientationChange={setOrientation}
        run={run}
        initialSelectedId={rule ? null : graph.nodes[0]?.id ?? null}
      />

      {save.isError && !saveSlqError && <ErrorText error={save.error} />}
      {saveSlqError && (
        <p className="text-xs text-status-danger-ink">Rejected on save: {saveSlqError.message}</p>
      )}

      <div className="flex items-end gap-2">
        <Button type="submit" disabled={!canSave || save.isPending}>
          {save.isPending ? "Saving…" : persistedId ? "Save changes" : "Create automation"}
        </Button>
        <div className="max-w-md flex-1"><TextField
          label="Why this change (optional)"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Tightened the filter after Monday's run"
          maxLength={2000}
          className="w-full"
        /></div>
        {persistedId && <span className="pb-2 text-[11px] text-fg-muted">v{current}</span>}
      </div>

      {
        <div className="flex flex-col gap-2">
          {/* One report renderer, two sources (RADD-1266): what it WOULD do
              and what it DID. Tabs rather than two stacked panels because both
              annotate the same canvas, and only one can at a time. */}
          <div role="tablist" aria-label="Automation reports" className="flex gap-1">
            {(["dry-run", "runs", "versions"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                disabled={!persistedId && tab !== "dry-run"}
                aria-selected={panel === tab}
                onClick={() => { setPanel(tab); setRun(null); }}
                className={`rounded-[6px] px-2.5 py-1 text-xs cursor-pointer ${
                  panel === tab ? "bg-elevated text-heading" : "text-fg-secondary hover:text-heading"
                }`}
              >
                {tab === "dry-run" ? "Dry run" : tab === "runs" ? "Runs" : "Versions"}
              </button>
            ))}
          </div>
          {panel === "dry-run" ? (
            <RuleTestPanel
              ruleId={persistedId}
              name={name}
              edges={graph.edges}
              triggers={graph.nodes.filter(node => node.kind === "trigger").map(node => ({ node_id: node.id, event_type: String(node.params.event ?? "manual") }))}
              nodes={graph.nodes}
              onResult={setRun}
            />
          ) : panel === "runs" ? (
            <RunsPanel ruleId={persistedId!} nodes={graph.nodes} onResult={setRun} />
          ) : (
            <VersionsPanel
              ruleId={persistedId!}
              current={current}
              onRestored={(restored) => {
                // The editor takes the restored content as its own working
                // copy: what the canvas shows must be what is now current.
                setName(restored.name);
                setEnabled(restored.enabled);
                setSavedContent(JSON.stringify({ name: restored.name, enabled: restored.enabled, orientation: restored.orientation, nodes: restored.nodes, edges: restored.edges }));
                setOrientation(restored.orientation as Orientation);
                setGraph({ nodes: restored.nodes, edges: restored.edges });
                setCurrent(restored.version);
                setRun(null);
              }}
            />
          )}
        </div>
      }
      {persistedId && <Slot id={SlotId.entityHistory} entityType="automation_rule" entityId={persistedId} />}
    </form>
  );
}
