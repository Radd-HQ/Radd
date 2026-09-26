import { useState } from "react";
import { ChevronRight, Copy, Wrench } from "lucide-react";
import { Button, copyText } from "@radd/plugin-sdk";
import { PLAN_SECTIONS } from "./plan-types";
import type { JiraProblem } from "./types";

/** Tab labels, so a problem can name where to go and fix it. */
const SECTION_LABELS: Record<string, string> = Object.fromEntries(PLAN_SECTIONS);

interface Group {
  message: string;
  kind: string;
  subjects: string[];
  detail: string;
  section: string;
  mappingKey: string;
}

/** Structured failures grouped by CAUSE, the affected issues listed under each, and — where a
 * mapping caused it — a "Fix in <tab> → <row>" jump. */
export function ProblemList({
  problems,
  onFix,
}: {
  problems: JiraProblem[];
  /** Jump to the mapping tab (and row) that would fix this. */
  onFix?: (section: string, mappingKey: string) => void;
}) {
  if (problems.length === 0) return null;

  const groups = new Map<string, Group>();
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
        <ProblemGroup key={`${group.kind}${group.message}`} group={group} onFix={onFix} />
      ))}
    </div>
  );
}

function ProblemGroup({
  group,
  onFix,
}: {
  group: Group;
  onFix?: (section: string, mappingKey: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const count = group.subjects.length;
  const sectionLabel = SECTION_LABELS[group.section];
  return (
    <div className="rounded-md border border-callout-warning-border/60 bg-callout-warning-fill px-2.5 py-2">
      <div className="flex items-start gap-1.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex flex-1 items-start gap-1.5 text-left text-xs text-callout-warning-ink cursor-pointer"
        >
          <ChevronRight
            size={13}
            className={"mt-0.5 shrink-0 transition-transform " + (open ? "rotate-90" : "")}
          />
          <span className="flex-1">
            {group.message}
            {count > 0 && (
              <span className="ml-1.5 text-fg-secondary">
                — {count} issue{count === 1 ? "" : "s"} affected
              </span>
            )}
          </span>
        </button>
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
                onClick={() => void copyText(group.subjects.join("\n"))}
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
