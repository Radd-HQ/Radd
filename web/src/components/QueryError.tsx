import { errorMessage } from "../lib/api";

/**
 * The standard full-width query-failure line: "Failed to load {label}: {msg}".
 * One shared box so route-level load errors stop drifting in style — pages
 * with a padded layout wrapper keep the wrapper and render this inside it.
 * Panels/modals with genuinely different (compact) presentation keep their own.
 */
export function QueryError({ label, error }: { label: string; error: unknown }) {
  return (
    <p className="w-full text-sm text-red-400">
      Failed to load {label}: {errorMessage(error)}
    </p>
  );
}
