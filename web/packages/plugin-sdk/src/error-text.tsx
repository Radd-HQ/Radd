import { errorMessage } from "./api";

export interface ErrorTextProps {
  /** An ApiError/unknown from a mutation or query, or an already-built string. */
  error: unknown;
  /** Matches the two sizes the hand-rolled copies used. */
  size?: "xs" | "sm";
  /** Layout only (margins); the color and size are this component's job. */
  className?: string;
}

/** The inline error paragraph, on the status tier; renders nothing for a null/undefined error. */
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
