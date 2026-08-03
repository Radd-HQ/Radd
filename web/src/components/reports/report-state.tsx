import type { ReactNode } from "react";
import { Spinner } from "../Spinner";
import type { ReportScope } from "../../lib/types";

/**
 * "across 2 of 5 projects" — what a cross-project figure was computed over
 * (RADD-789).
 *
 * A filtered LIST is visibly shorter. A filtered AVERAGE is just a different
 * number, and two people reading the same dashboard would see different
 * velocities with nothing explaining why. So the figure states its own scope.
 *
 * Renders NOTHING when the reader can see every project, which is the common
 * case — a note on every report is one nobody reads by the second week.
 */
export function scopeNote(scope: ReportScope | undefined): string | null {
  if (!scope || scope.covered.length >= scope.total) return null;
  return `across ${scope.covered.length} of ${scope.total} projects you can read`;
}

/** The scope note as a line under a report's description. */
export function ScopeNote({ scope }: { scope: ReportScope | undefined }) {
  const note = scopeNote(scope);
  if (!note) return null;
  return (
    <p className="mt-1 text-xs text-fg-faint" title={`Covers: ${scope?.covered.join(", ")}`}>
      {note}
    </p>
  );
}

/** Shared loading/error/empty gate for a report card's body (spec 19). */
export function CardBody({
  pending,
  error,
  empty,
  emptyMessage,
  loadingLabel = "Loading…",
  children,
}: {
  pending: boolean;
  error: string | null;
  empty: boolean;
  emptyMessage: string;
  loadingLabel?: string;
  children: ReactNode;
}) {
  if (pending) return <Spinner label={loadingLabel} />;
  if (error) return <p className="py-6 text-sm text-red-400">Failed to load: {error}</p>;
  if (empty) return <p className="py-8 text-center text-sm text-fg-faint">{emptyMessage}</p>;
  return <>{children}</>;
}

/** Compact segmented control shared by the report controls (interval, etc.). */
export function Segmented<T extends string>({
  ariaLabel,
  value,
  options,
  onChange,
}: {
  ariaLabel: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={ariaLabel} className="flex rounded-md border border-subtle p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={
            "rounded px-2 py-0.5 text-xs cursor-pointer focus-visible:outline-2 focus-visible:outline-focus " +
            (value === option.value
              ? "bg-elevated text-heading"
              : "text-fg-muted hover:text-fg")
          }
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
