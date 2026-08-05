import { errorMessage } from "../lib/api";

interface ErrorTextProps {
  /** An ApiError/unknown from a mutation or query, or an already-built string. */
  error: unknown;
  /** Matches the two sizes the hand-rolled copies used. */
  size?: "xs" | "sm";
  /** Layout only (margins); the color and size are this component's job. */
  className?: string;
}

/**
 * The inline error paragraph (RADD-901). `<p className="text-xs text-red-400">
 * {errorMessage(error)}</p>` existed in ~109 hand-typed copies — this is that
 * shape as a component, on the status tier so the danger color has ONE home.
 * Renders nothing for a null/undefined error, so call sites can drop their
 * `isError &&` guard or keep it, whichever reads better.
 */
export function ErrorText({ error, size = "xs", className = "" }: ErrorTextProps) {
  if (error == null) return null;
  const text = typeof error === "string" ? error : errorMessage(error);
  return (
    <p
      className={`${size === "sm" ? "text-sm" : "text-xs"} text-status-danger-ink ${className}`}
    >
      {text}
    </p>
  );
}
