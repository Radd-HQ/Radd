/**
 * What the intake checks said about a draft, shared by the New Item modal and both form pages. Every
 * finding is listed, including those already shown against a control (it may be off-screen); field
 * findings carry the field's name.
 */
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Info } from "lucide-react";
import type { Finding } from "@radd-plugin-ui/automations/types";
import { validationBlocking, validationFindings } from "../../lib/api";

interface IntakeVerdict {
  findings: Finding[];
  blocking: boolean;
}

/**
 * The last verdict a surface saw: the findings and whether they REFUSE the draft, in one piece of
 * state off the same answer. `blocking` is the server's `verdict.blocking` (what it decides a
 * `commit: always` 409 by), never `mode === "required"` from the context read: that read predates
 * the submission, and a required graph merely watching a draft that tripped only an advisory one is
 * advice. An error carrying no findings of its own (a 409 refusing "anyway", a 503 while the checks
 * are down, a field-registry 422) leaves the list alone — blanking it hid the panel at the moment it
 * was being argued with.
 */
export function useIntakeVerdict() {
  const [verdict, setVerdict] = useState<IntakeVerdict>({ findings: [], blocking: false });
  return {
    findings: verdict.findings,
    blocking: verdict.blocking,
    absorb: ({ findings, blocking }: IntakeVerdict) => setVerdict({ findings, blocking }),
    clear: () => setVerdict({ findings: [], blocking: false }),
    absorbError: (error: unknown) => {
      const refused = validationFindings(error);
      const answered = validationBlocking(error);
      if (refused.length > 0 || answered !== null) {
        setVerdict((previous) => ({
          findings: refused.length > 0 ? refused : previous.findings,
          blocking: answered ?? previous.blocking,
        }));
      }
    },
  };
}

interface FindingsPanelProps {
  findings: Finding[];
  /** The SERVER's `verdict.blocking`, never `mode === "required"`: a required graph merely watching a
   *  draft that tripped only an advisory one is advice, not a refusal. */
  blocking: boolean;
  /** Human label for a field key — the form knows its own controls' names. */
  labelFor?: (field: string) => string | undefined;
}

export function FindingsPanel({ findings, blocking, labelFor }: FindingsPanelProps) {
  const ref = useRef<HTMLDivElement>(null);
  // Scroll into view on appear: below the fold of a long modal, "Validate" otherwise looks like it did nothing.
  useEffect(() => {
    if (findings.length > 0) ref.current?.scrollIntoView({ block: "nearest" });
  }, [findings]);

  if (findings.length === 0) return null;
  const Icon = blocking ? AlertTriangle : Info;

  return (
    <div
      ref={ref}
      // A live region: the panel appears in response to pressing Validate, and
      // a screen reader that never announces it makes the button look broken.
      role="status"
      aria-live="polite"
      data-findings-panel
      data-blocking={String(blocking)}
      className={
        blocking
          ? "flex flex-col gap-2 rounded-[8px] border border-status-danger/30 bg-status-danger/5 p-3"
          : "flex flex-col gap-2 rounded-[8px] border border-status-warning/30 bg-status-warning/5 p-3"
      }
    >
      <p
        className={`flex items-center gap-2 text-[13px] font-medium ${
          blocking ? "text-status-danger-ink" : "text-status-warning-ink"
        }`}
      >
        <Icon size={14} aria-hidden />
        {blocking
          ? findings.length === 1
            ? "One thing to fix before this can be created"
            : `${findings.length} things to fix before this can be created`
          : findings.length === 1
            ? "One suggestion"
            : `${findings.length} suggestions`}
      </p>
      <ul className="flex flex-col gap-1.5">
        {findings.map((finding, index) => {
          const label = finding.field ? labelFor?.(finding.field) : undefined;
          return (
            <li
              key={`${finding.node_id}-${index}`}
              data-finding-field={finding.field || undefined}
              className="flex gap-2 text-[13px] text-fg"
            >
              <span aria-hidden className="select-none text-fg-faint">
                •
              </span>
              <span>
                {label && <span className="font-medium text-heading">{label}: </span>}
                {finding.message}
              </span>
            </li>
          );
        })}
      </ul>
      {!blocking && (
        <p className="text-xs text-fg-secondary">
          These are suggestions — you can create it anyway.
        </p>
      )}
    </div>
  );
}
