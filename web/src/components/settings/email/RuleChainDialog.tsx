import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2, Wand2 } from "lucide-react";
import { api } from "../../../lib/api";
import { apiMailRulePath, apiMailSourceRulesOrderPath } from "../../../lib/constants";
import { mailRulesQuery, projectsQuery, queryKeys } from "../../../lib/queries";
import type { MailRule, MailSource } from "../../../lib/types";
import { Button } from "../../Button";
import { EmptyState } from "../../EmptyState";
import { IconButton } from "../../IconButton";
import { Modal } from "../../Modal";
import { TableSkeleton } from "../../TableSkeleton";
import { PreviewDialog } from "./PreviewDialog";
import { RULE_LABELS, RuleDialog } from "./RuleDialog";
import { Chip } from "./shared";

/**
 * One source's ordered routing chain (RADD-958/961): first enabled match wins,
 * anything unmatched falls to the source's default project.
 */
export function RuleChainDialog({
  source,
  onClose,
}: {
  source: MailSource;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const rules = useQuery(mailRulesQuery(source.id));
  const projects = useQuery(projectsQuery());
  const [editing, setEditing] = useState<MailRule | "new" | null>(null);
  const [preview, setPreview] = useState(false);

  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.mailRules(source.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.mailSources }),
    ]);

  const reorder = useMutation({
    mutationFn: (ids: string[]) =>
      api.put(apiMailSourceRulesOrderPath(source.id), { rule_ids: ids }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(apiMailRulePath(id)),
    onSuccess: invalidate,
  });

  const list = rules.data ?? [];
  const move = (index: number, delta: number) => {
    const next = [...list];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next.map((r) => r.id));
  };

  return (
    <Modal title={`Routing — ${source.name}`} onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        <p className="text-[11px] text-fg-muted">
          Checked top to bottom; the first match decides the project and stops the chain. Anything
          unmatched falls to this source's default. Keep the AI rule last — the rules above it cost
          nothing, and only mail none of them claimed pays for an inference.
        </p>

        {rules.isPending ? (
          <TableSkeleton rows={3} />
        ) : list.length === 0 ? (
          <EmptyState icon={Wand2} message="No rules — everything opens in the default project." />
        ) : (
          <ol className="flex flex-col gap-1">
            {list.map((rule, index) => (
              <li
                key={rule.id}
                className="flex items-center gap-2 rounded-md border border-subtle bg-surface/60 px-3 py-2"
              >
                <span className="w-5 shrink-0 text-center font-mono text-[11px] text-fg-faint">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-fg">{rule.name}</span>
                  <span className="block truncate text-[11px] text-fg-faint">
                    {RULE_LABELS[rule.rule_type]} →{" "}
                    {(projects.data ?? []).find((p) => p.id === rule.project_id)?.key ?? "—"}
                  </span>
                </span>
                {!rule.enabled && <Chip tone="muted">off</Chip>}
                <IconButton
                  onClick={() => move(index, -1)}
                  aria-label="Move up"
                  disabled={index === 0}
                >
                  <ArrowUp size={13} />
                </IconButton>
                <IconButton
                  onClick={() => move(index, 1)}
                  aria-label="Move down"
                  disabled={index === list.length - 1}
                >
                  <ArrowDown size={13} />
                </IconButton>
                <Button size="sm" variant="ghost" onClick={() => setEditing(rule)}>
                  Edit
                </Button>
                <IconButton danger onClick={() => remove.mutate(rule.id)} aria-label="Delete rule">
                  <Trash2 size={13} />
                </IconButton>
              </li>
            ))}
          </ol>
        )}

        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setEditing("new")}>
            <Plus size={13} aria-hidden />
            Add rule
          </Button>
          <Button variant="ghost" onClick={() => setPreview(true)}>
            <Wand2 size={13} aria-hidden />
            Test where a message lands
          </Button>
        </div>
      </div>

      {editing && (
        <RuleDialog
          source={source}
          rule={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
            void invalidate();
          }}
        />
      )}
      {preview && <PreviewDialog source={source} onClose={() => setPreview(false)} />}
    </Modal>
  );
}
