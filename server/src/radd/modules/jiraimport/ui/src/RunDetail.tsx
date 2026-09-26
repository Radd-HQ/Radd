import { useState } from "react";
import { CollapsibleCard } from "@radd/plugin-sdk";
import { DryRunAction, type JiraRun } from "./types";

const ACTION_CLASS: Record<string, string> = {
  [DryRunAction.skip]: "text-status-danger-ink",
  [DryRunAction.update]: "text-status-warning-ink",
};

/** What the import would do, issue by issue. */
export function DryRunPreview({ run }: { run: JiraRun }) {
  const rows = run.report.rows ?? [];
  const problems = rows.filter((r) => r.action === DryRunAction.skip);
  const [onlyProblems, setOnlyProblems] = useState(problems.length > 0);
  const shown = (onlyProblems ? problems : rows).slice(0, 100);
  return (
    <div className="rounded-md border border-subtle">
      <div className="flex items-center gap-2 border-b border-subtle px-2.5 py-1.5">
        <span className="text-xs text-fg-secondary">
          {rows.length} issue(s) previewed
          {run.report.truncated && " (first 500)"}
          {problems.length > 0 && ` · ${problems.length} would be skipped`}
        </span>
        {problems.length > 0 && (
          <label className="ml-auto flex items-center gap-1.5 text-xs text-fg-secondary">
            <input
              type="checkbox"
              checked={onlyProblems}
              onChange={(e) => setOnlyProblems(e.target.checked)}
            />
            Problems only
          </label>
        )}
      </div>
      <ul className="max-h-64 overflow-y-auto divide-y divide-subtle/60">
        {shown.map((row) => (
          <li key={row.jira_key} className="flex items-baseline gap-2 px-2.5 py-1 text-xs">
            <span className="w-16 shrink-0 font-mono text-fg-faint">{row.jira_key}</span>
            <span className={"w-14 shrink-0 " + (ACTION_CLASS[row.action] ?? "text-status-success-ink")}>
              {row.action}
            </span>
            <span className="w-20 shrink-0 font-mono text-fg-secondary">{row.radd_key}</span>
            <span className="truncate text-fg-secondary">{row.reason || row.title}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The mapping this run executed — read-only, collapsed; survives the plan being edited for a
 * redo (RADD-1105). */
export function PlanSnapshot({ run }: { run: JiraRun }) {
  const mappings = run.plan_snapshot?.mappings ?? {};
  const sections = Object.entries(mappings).filter(
    ([, table]) => Object.keys(table ?? {}).length > 0,
  );
  if (sections.length === 0) return null;
  const total = sections.reduce((n, [, table]) => n + Object.keys(table).length, 0);
  return (
    <CollapsibleCard title="Plan as executed" count={total}>
      <div className="flex flex-col gap-3">
        {sections.map(([section, table]) => (
          <div key={section}>
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
              {section}
            </p>
            <ul className="flex flex-col gap-0.5 text-xs text-fg-secondary">
              {Object.entries(table).map(([key, entry]) => (
                <li key={key} className="flex flex-wrap items-baseline gap-1.5">
                  <span className="font-mono text-[11px] text-fg">{key}</span>
                  <span className="text-fg-faint">→</span>
                  <span>
                    {entry?.action ?? "map"}
                    {entry?.target ? `: ${entry.target}` : ""}
                    {entry?.create_name ? ` (create "${entry.create_name}")` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </CollapsibleCard>
  );
}
