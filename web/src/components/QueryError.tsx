import { ApiError, errorMessage } from "../lib/api";
import { AccessRefusal } from "./AccessRefusal";

/**
 * The standard full-width query-failure line: "Failed to load {label}: {msg}".
 * One shared box so route-level load errors stop drifting in style — pages
 * with a padded layout wrapper keep the wrapper and render this inside it.
 * Panels/modals with genuinely different (compact) presentation keep their own.
 *
 * RADD-836 U3: a 403 renders as a REAL refusal — what is required, at which
 * scope, who can grant it — instead of a dead-end line. Every surface using
 * this component inherits it at once.
 */
export function QueryError({ label, error }: { label: string; error: unknown }) {
  if (!error) return null;
  if (error instanceof ApiError && error.status === 403) {
    return <AccessRefusal error={error} />;
  }
  return (
    <p className="w-full text-sm text-red-400">
      Failed to load {label}: {errorMessage(error)}
    </p>
  );
}
