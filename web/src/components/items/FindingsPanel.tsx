/**
 * What the checks said about a draft (spec 119).
 *
 * Shared by the New Item modal and both intake form pages, so the wording, the
 * ordering and the advisory/required distinction cannot drift between the three
 * surfaces someone can create an issue from.
 *
 * Every finding appears here, INCLUDING the ones already highlighted against a
 * control. A field-addressed finding sits next to an input the person may not
 * have scrolled to, and a panel that showed only the leftovers would tell them
 * "two problems" while listing one. The field-addressed ones carry their field's
 * name so the panel reads as a checklist rather than a wall of sentences.
 */
import { useEffect, useRef } from "react";
import { AlertTriangle, Info } from "lucide-react";
import { type Finding } from "../../lib/types";

interface FindingsPanelProps {
  findings: Finding[];
  /**
   * Decides the voice: a refusal you cannot proceed past, or advice you may.
   *
   * The SERVER's `verdict.blocking`, never `mode === "required"` computed here.
   * The two differ exactly when a draft is governed by a required graph and an
   * advisory one and trips only the advisory: the mode is still "required"
   * because something required is watching, and the creation is not refused.
   * Deciding it locally made the panel say "fix this before it can be created"
   * about advice, next to a bypass the caller then hid.
   */
  blocking: boolean;
  /** Human label for a field key — the form knows its own controls' names. */
  labelFor?: (field: string) => string | undefined;
}

export function FindingsPanel({ findings, blocking, labelFor }: FindingsPanelProps) {
  const ref = useRef<HTMLDivElement>(null);
  // Scroll itself into view when it appears.
  //
  // Caught by a SCREENSHOT, not by the measurements: `getBoundingClientRect`
  // reported the panel present, sized and positive-y, and every numeric check
  // passed — while the panel sat below the fold of a long New Item modal. The
  // person pressed Validate and, unless they happened to scroll, saw nothing
  // change. Answering a click somewhere the eye is not is the same failure as
  // not answering it (RADD-762, from the other direction).
  //
  // Here rather than in each surface: both the modal and the two form pages
  // would otherwise carry the same effect, and the third one added later would
  // forget it.
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
