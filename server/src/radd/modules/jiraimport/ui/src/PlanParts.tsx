import { CheckCircle2 } from "lucide-react";
import { Callout, CalloutKind } from "@radd/plugin-sdk";
import { PLAN_SECTIONS, type PlanOptions, type PlanSection, type PlanValidation } from "./plan-types";

/** The nine tabs, each badged with how many rows actually matter and how many problems it has. */
export function PlanTabs({
  active,
  onSelect,
  counted,
  problems,
}: {
  active: PlanSection;
  onSelect: (section: PlanSection) => void;
  counted: (section: PlanSection) => number;
  problems: (section: PlanSection) => number;
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Mapping tables">
      {PLAN_SECTIONS.map(([key, label]) => {
        const count = problems(key);
        const selected = active === key;
        return (
          <button
            key={key}
            type="button"
            aria-pressed={selected}
            onClick={() => onSelect(key)}
            className={
              "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors cursor-pointer " +
              (selected
                ? "bg-accent text-white"
                : "border border-subtle bg-elevated text-fg-secondary hover:border-strong")
            }
          >
            {label}
            <span className={selected ? "text-white/70" : "text-fg-faint"}>{counted(key)}</span>
            {count > 0 && (
              <span className="rounded bg-status-danger/20 px-1 text-[10px] text-status-danger-ink">
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** The run options a plan carries next to its mappings. */
export function ImportOptions({
  options,
  onChange,
}: {
  options: PlanOptions;
  onChange: (next: PlanOptions) => void;
}) {
  const toggle = (key: keyof PlanOptions, label: string, hint?: string) => (
    <label className="flex items-start gap-2 text-xs text-fg-secondary">
      <input
        type="checkbox"
        className="mt-0.5"
        checked={Boolean(options[key])}
        onChange={(e) => onChange({ ...options, [key]: e.target.checked })}
      />
      <span>
        {label}
        {hint && <span className="block text-fg-faint">{hint}</span>}
      </span>
    </label>
  );
  return (
    <fieldset className="rounded-lg border border-subtle p-3">
      <legend className="px-1 text-xs font-medium text-fg-secondary">How to import</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {toggle(
          "quiet",
          "Import quietly",
          "Nobody is notified and no automation rule fires — imported work is years old.",
        )}
        {toggle("import_comments", "Comments")}
        {toggle("import_worklogs", "Worklogs")}
        {toggle("import_attachments", "Attachments")}
        {toggle("import_history", "Change history")}
      </div>
    </fieldset>
  );
}

/** What "Check" found: the first dozen problems, or that the plan is ready. */
export function ValidationSummary({ validation }: { validation: PlanValidation | null }) {
  if (!validation) return null;
  if (validation.ok) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-status-success-ink">
        <CheckCircle2 size={13} /> The plan is ready to import.
      </p>
    );
  }
  return (
    <Callout kind={CalloutKind.danger} className="p-3">
      <p className="text-[13px]">{validation.problems.length} thing(s) to fix before importing</p>
      <ul className="mt-1.5 flex flex-col gap-0.5 text-xs text-fg-secondary">
        {validation.problems.slice(0, 12).map((problem, i) => (
          <li key={i}>
            <span className="text-fg-faint">{problem.section}</span>
            {problem.subject && <span className="text-fg"> · {problem.subject}</span>} —{" "}
            {problem.message}
          </li>
        ))}
      </ul>
    </Callout>
  );
}
