import type { ReactNode } from "react";
import { Spinner } from "../Spinner";

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
