import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleCheck, CircleSlash, FlaskConical } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiAutomationTestPath } from "../../lib/constants";
import { ACTION_TYPE_LABELS } from "../../lib/meta";
import { itemsQuery, projectsQuery } from "../../lib/queries";
import type { ActionPreview, RuleTestResult } from "../../lib/types";
import { Button } from "../Button";
import { SelectField } from "../SelectField";

interface RuleTestPanelProps {
  ruleId: string;
}

/**
 * "Test on an item" affordance (spec 20): pick a project + item, POST
 * `/automations/{id}/test`, and show whether the item matched and which actions
 * would apply (with the engine's per-action resolve/skip detail).
 */
export function RuleTestPanel({ ruleId }: RuleTestPanelProps) {
  const projects = useQuery(projectsQuery());
  const [projectId, setProjectId] = useState("");
  const [itemId, setItemId] = useState("");
  const effectiveProjectId = projectId || projects.data?.[0]?.id || "";
  const items = useQuery({
    ...itemsQuery(effectiveProjectId),
    enabled: Boolean(effectiveProjectId),
  });

  const test = useMutation({
    mutationFn: (id: string) =>
      api.post<RuleTestResult>(apiAutomationTestPath(ruleId), { item_id: id }),
  });

  const result = test.data;

  return (
    <div className="flex flex-col gap-3 rounded-md border border-subtle bg-surface/40 p-3">
      <div className="flex items-center gap-2">
        <FlaskConical size={14} className="text-accent-text" aria-hidden />
        <span className="text-xs font-medium text-fg">Test on an item</span>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
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
          label="Item"
          value={itemId}
          onChange={(event) => setItemId(event.target.value)}
          hint={items.data && items.data.length === 0 ? "No items in this project" : undefined}
        >
          <option value="">Select an item…</option>
          {(items.data ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.key} — {item.title}
            </option>
          ))}
        </SelectField>
      </div>
      <div className="flex items-center gap-3">
        <Button
          onClick={() => itemId && test.mutate(itemId)}
          disabled={!itemId || test.isPending}
        >
          {test.isPending ? "Running…" : "Run preview"}
        </Button>
        {test.isError && <span className="text-xs text-red-400">{errorMessage(test.error)}</span>}
      </div>

      {result && (
        <div className="flex flex-col gap-2">
          <p className="flex items-center gap-1.5 text-[13px]">
            {result.matched ? (
              <>
                <CircleCheck size={14} className="text-emerald-400" aria-hidden />
                <span className="text-emerald-300">Condition matched</span>
              </>
            ) : (
              <>
                <CircleSlash size={14} className="text-fg-muted" aria-hidden />
                <span className="text-fg-secondary">Condition did not match — no actions would apply</span>
              </>
            )}
          </p>
          {result.matched && result.would_apply.length > 0 && (
            <ul className="flex flex-col gap-1">
              {result.would_apply.map((preview, index) => (
                <ActionPreviewRow key={index} preview={preview} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
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
      <span className="truncate text-fg-muted">{preview.detail}</span>
    </li>
  );
}
