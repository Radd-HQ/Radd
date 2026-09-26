import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import type { ReportScope } from "../report-contract";

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
  if (pending) {
    return (
      <div className="flex items-center justify-center gap-2 p-10 text-sm text-fg-muted">
        <Loader2 size={16} className="animate-spin" aria-hidden />
        {loadingLabel}
      </div>
    );
  }
  if (error) return <p className="py-6 text-sm text-red-400">Failed to load: {error}</p>;
  if (empty) return <p className="py-8 text-center text-sm text-fg-faint">{emptyMessage}</p>;
  return <>{children}</>;
}
