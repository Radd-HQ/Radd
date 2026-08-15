/**
 * The automation editor (specs 20/58/69/116).
 *
 * Name, enabled, and the graph — that is the whole thing. The list-based form
 * that stood here until spec 116 is gone: it could not express a branch, and
 * keeping it beside the canvas meant a bidirectional adapter and two sources of
 * truth for one automation.
 *
 * A new automation starts EMPTY rather than with a pre-made trigger. Everything
 * is a node, including the trigger, and the panel is where nodes come from —
 * seeding one would teach the opposite.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath, apiAutomationPath } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import { slqErrorOf } from "../../lib/slq";
import {
  type AutomationEdge,
  type AutomationNode,
  type Rule,
  type RuleCreate,
  type RuleTestResult,
  type RuleUpdate,
} from "../../lib/types";
import { Button } from "../Button";
import { ErrorText } from "../ErrorText";
import { TextField } from "../TextField";
import { incompleteActionNodeIds } from "./ActionsBuilder";
import { GraphEditor, type Orientation } from "./GraphEditor";
import { RuleTestPanel } from "./RuleTestPanel";

interface RuleEditorProps {
  /** The rule to edit, or null to create a new one. */
  rule: Rule | null;
  onDone: () => void;
}

export function RuleEditor({ rule, onDone }: RuleEditorProps) {
  const queryClient = useQueryClient();
  const [persistedId, setPersistedId] = useState<string | null>(rule?.id ?? null);
  const [name, setName] = useState(rule?.name ?? "");
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [orientation, setOrientation] = useState<Orientation>(
    (rule?.orientation as Orientation) ?? "vertical",
  );
  // The last dry run. Held HERE rather than in the editor because the panel that
  // produces it and the canvas that draws it are siblings, and because it must
  // survive a node being selected — the whole point is to read the numbers while
  // clicking around the graph that produced them.
  const [run, setRun] = useState<RuleTestResult | null>(null);
  const [graph, setGraph] = useState<{ nodes: AutomationNode[]; edges: AutomationEdge[] }>({
    nodes: rule?.nodes ?? [],
    edges: rule?.edges ?? [],
  });

  // A graph with no nodes is not worth saving; one with no TRIGGER is, because
  // it is work in progress and the canvas already says it cannot run. A graph
  // with a HALF-CONFIGURED action is not (RADD-1104): saving it would only
  // bounce off the server's 422, and never-edit-then-error is the house rule.
  const incompleteActions = incompleteActionNodeIds(graph.nodes);
  const canSave =
    name.trim() !== "" && graph.nodes.length > 0 && incompleteActions.length === 0;

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        enabled,
        orientation,
        nodes: graph.nodes,
        edges: graph.edges,
      };
      return persistedId
        ? api.patch<Rule>(apiAutomationPath(persistedId), payload satisfies RuleUpdate)
        : api.post<Rule>(ApiPath.automations, payload satisfies RuleCreate);
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.automations });
      setPersistedId(saved.id);
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
        {save.isSuccess && !save.isPending && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <Check size={13} aria-hidden />
            Saved
          </span>
        )}
      </div>

      <div className="flex items-end gap-4">
        <TextField
          label="Automation name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Auto-triage blockers"
          maxLength={200}
          required
          className="max-w-sm flex-1"
        />
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

      <GraphEditor
        nodes={graph.nodes}
        edges={graph.edges}
        orientation={orientation}
        onChange={setGraph}
        onOrientationChange={setOrientation}
        run={run}
      />

      {save.isError && !saveSlqError && <ErrorText error={save.error} />}
      {saveSlqError && (
        <p className="text-xs text-red-400">Rejected on save: {saveSlqError.message}</p>
      )}

      <div className="flex items-center gap-2">
        <Button type="submit" disabled={!canSave || save.isPending}>
          {save.isPending ? "Saving…" : persistedId ? "Save changes" : "Create automation"}
        </Button>
      </div>

      {persistedId ? (
        <RuleTestPanel
          ruleId={persistedId}
          triggers={rule?.triggers ?? []}
          nodes={graph.nodes}
          onResult={setRun}
        />
      ) : (
        <p className="text-xs text-fg-muted">Save the automation to dry-run it.</p>
      )}
    </form>
  );
}
