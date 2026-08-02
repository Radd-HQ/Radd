import { useId, type InputHTMLAttributes } from "react";

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  error?: string;
}

/** Labeled input with optional hint + inline error, dense dark styling. */
export function TextField({ label, hint, error, className = "", ...props }: TextFieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-medium text-fg-secondary">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint || error ? hintId : undefined}
        {...props}
        className={
          "h-8 rounded-md border bg-surface px-2.5 text-[13px] text-heading " +
          "placeholder:text-fg-faint focus:outline-none focus:ring-2 " +
          "disabled:cursor-not-allowed disabled:opacity-70 " +
          (error
            ? "border-red-500/60 focus:border-red-400 focus:ring-red-400/30 "
            : "border-subtle focus:border-accent focus:ring-accent/30 ") +
          className
        }
      />
      {error ? (
        <p id={hintId} className="text-xs text-red-400">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-fg-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
