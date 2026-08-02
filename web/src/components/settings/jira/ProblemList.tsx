import { useState } from "react";
import { ChevronRight, Copy, Wrench } from "lucide-react";
import type { JiraProblem } from "../../../lib/types";
import { Button } from "../../Button";

/** Tab labels, so a problem can name where to go and fix it. */
const SECTION_LABELS: Record<string, string> = {
  fields: "Fields",
  issue_types: "Issue types",
  statuses: "Statuses",
  priorities: "Priorities",
  link_types: "Link types",
  users: "People",
  sprints: "Sprints",
  versions: "Versions",
  components: "Components",
};

/**
 * Structured failures, GROUPED BY CAUSE with the affected issues listed under
 * each — and, where a mapping decision caused it, a jump straight to that row.
 *
 * Spec 90 rendered `errors: string[]`, sliced to 20, capped at 50 server-side,
 * every entry labelled "issue(s) skipped". The question an admin actually has is
 * "what do I CHANGE" — so the reason is the heading, the affected issues are the
 * list, and "Fix in Statuses → Needs Discussion" is a button.
 */
export function ProblemList({
  problems,
  label = "issue",
  onFix,
}: {
  problems: JiraProblem[];
  label?: string;
  /** Jump to the mapping tab (and row) that would fix this. */
  onFix?: (section: string, mappingKey: string) => void;
}) {
  if (problems.length === 0) return null;

  // Group by the REASON, so one broken field does not read as 400 unrelated errors.
  const groups = new Map<
    string,
    { message: string; kind: string; subjects: string[]; detail: string; section: string; mappingKey: string }
  >();
  for (const problem of problems) {
    const key = `${problem.kind}::${problem.message}`;
    const group = groups.get(key) ?? {
      message: problem.message,
      kind: problem.kind,
      subjects: [],
      detail: problem.detail,
      section: problem.section,
      mappingKey: problem.mapping_key,
    };
    if (problem.subject) group.subjects.push(problem.subject);
    groups.set(key, group);
  }

  return (
    <div className="flex flex-col gap-1.5">
      {[...groups.values()].map((group) => (
        <ProblemGroup
          key={`${group.kind}${group.message}`}
          group={group}
          label={label}
          onFix={onFix}
        />
      ))}
    </div>
  );
}

function ProblemGroup({
  group,
  label,
  onFix,
}: {
  group: {
    message: string;
    kind: string;
    subjects: string[];
    detail: string;
    section: string;
    mappingKey: string;
  };
  label: string;
  onFix?: (section: string, mappingKey: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const count = group.subjects.length;
  const sectionLabel = SECTION_LABELS[group.section];
  return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2.5 py-2">
      <div className="flex items-start gap-1.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex flex-1 items-start gap-1.5 text-left text-xs text-amber-200 cursor-pointer"
        >
          <ChevronRight
            size={13}
            className={"mt-0.5 shrink-0 transition-transform " + (open ? "rotate-90" : "")}
          />
          <span className="flex-1">
            {group.message}
            {count > 0 && (
              <span className="ml-1.5 text-fg-secondary">
                — {count} {label}
                {count === 1 ? "" : "s"} affected
              </span>
            )}
          </span>
        </button>
        {/* The whole point: go straight to the decision that caused it. */}
        {sectionLabel && onFix && (
          <Button
            size="sm"
            variant="secondary"
            className="shrink-0 whitespace-nowrap"
            onClick={() => onFix(group.section, group.mappingKey)}
          >
            <Wrench size={12} /> Fix in {sectionLabel}
            {group.mappingKey && ` → ${group.mappingKey}`}
          </Button>
        )}
      </div>
      {open && (
        <div className="mt-2 pl-5">
          {count > 0 && (
            <>
              {/* Every affected subject, not a truncated sample — copyable, so it
                  can go straight into a JQL filter or a ticket. */}
              <ul className="max-h-48 overflow-y-auto font-mono text-[11px] text-fg-secondary">
                {group.subjects.map((subject) => (
                  <li key={subject}>{subject}</li>
                ))}
              </ul>
              <Button
                size="sm"
                variant="ghost"
                className="mt-1.5"
                onClick={() => void navigator.clipboard?.writeText(group.subjects.join("\n"))}
              >
                <Copy size={12} /> Copy all {count}
              </Button>
            </>
          )}
          {group.detail && (
            <p className="mt-1.5 font-mono text-[11px] text-fg-faint">{group.detail}</p>
          )}
        </div>
      )}
    </div>
  );
}
