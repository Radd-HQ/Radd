import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { FIELD_TYPE_LABELS } from "../../lib/meta";
import {
  SLQ_BUILTIN_FIELDS,
  SLQ_EXAMPLES,
  SLQ_OPERATORS,
  SLQ_VALUE_NOTES,
  cfOpsHint,
  cheatSheetFields,
} from "../../lib/slq";
import type { FieldDef } from "../../lib/types";

interface SlqCheatSheetProps {
  /** Registry definitions — custom-field rows come live from here. */
  fields: FieldDef[];
  /** View scope: a project id, or null = all-projects. */
  projectId: string | null;
}

const headingClasses = "pb-1 text-[11px] font-medium uppercase tracking-wide text-fg-faint";
const codeClasses = "font-mono text-[11px] text-accent-text";

/**
 * Collapsible SLQ syntax reference (spec 11), generated from lib/slq.ts
 * (mirror of spec 10's frozen grammar) + the live field registry.
 */
export function SlqCheatSheet({ fields, projectId }: SlqCheatSheetProps) {
  const [open, setOpen] = useState(false);
  const customFields = cheatSheetFields(fields, projectId);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="rounded-lg border border-subtle">
      <button
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-1.5 px-3 py-2 text-xs font-medium text-fg-secondary hover:text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
      >
        <Chevron size={13} aria-hidden />
        Query syntax
      </button>

      {open && (
        <div className="flex max-h-72 flex-col gap-4 overflow-y-auto border-t border-subtle px-3 py-3">
          <section aria-label="Fields">
            <p className={headingClasses}>Fields</p>
            <table className="w-full border-collapse text-left">
              <tbody>
                {SLQ_BUILTIN_FIELDS.map((help) => (
                  <tr key={help.field} className="align-top">
                    <td className={`w-24 py-0.5 pr-2 ${codeClasses}`}>{help.field}</td>
                    <td className="py-0.5 pr-2 text-xs text-fg-secondary">{help.values}</td>
                    <td className="py-0.5 font-mono text-[11px] text-fg-muted">{help.example}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {customFields.length > 0 && (
            <section aria-label="Custom fields">
              <p className={headingClasses}>Custom fields (by registry key)</p>
              <table className="w-full border-collapse text-left">
                <tbody>
                  {customFields.map((field) => (
                    <tr key={field.id} className="align-top">
                      <td className={`w-24 py-0.5 pr-2 ${codeClasses}`}>{field.key}</td>
                      <td className="py-0.5 pr-2 text-xs text-fg-secondary">
                        {field.name} · {FIELD_TYPE_LABELS[field.type]}
                        {field.options ? ` (${field.options.join(" | ")})` : ""}
                      </td>
                      <td className="py-0.5 font-mono text-[11px] text-fg-muted">
                        {cfOpsHint(field.type)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section aria-label="Operators">
            <p className={headingClasses}>Operators</p>
            <table className="w-full border-collapse text-left">
              <tbody>
                {SLQ_OPERATORS.map((help) => (
                  <tr key={help.op} className="align-top">
                    <td className={`w-52 py-0.5 pr-2 ${codeClasses}`}>{help.op}</td>
                    <td className="py-0.5 text-xs text-fg-secondary">{help.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="mt-1.5 flex flex-col gap-0.5">
              {SLQ_VALUE_NOTES.map((note) => (
                <li key={note} className="text-[11px] text-fg-muted">
                  {note}
                </li>
              ))}
            </ul>
          </section>

          <section aria-label="Examples">
            <p className={headingClasses}>Examples</p>
            <ul className="flex flex-col gap-1">
              {SLQ_EXAMPLES.map((example) => (
                <li key={example} className="font-mono text-[11px] text-fg-secondary">
                  {example}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
