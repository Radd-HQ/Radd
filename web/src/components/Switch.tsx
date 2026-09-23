/**
 * An on/off switch (RADD-1288) — for a setting that takes effect the moment it
 * flips (a rule enabled, a filter applied), where a checkbox reads as "part of a
 * form you still have to submit". The label names the thing, never its state:
 * "Enabled" beside an unticked box, as automations used to read, says the
 * opposite of what is true.
 */
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
  hideLabel = false,
  className = "",
  ...data
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
  /** Keep `label` for screen readers only (a row whose title already names it). */
  hideLabel?: boolean;
  className?: string;
} & { [key: `data-${string}`]: string | boolean | undefined }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={hideLabel ? label : undefined}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={
        "inline-flex shrink-0 items-center gap-2 text-xs text-fg-secondary cursor-pointer " +
        "disabled:cursor-default disabled:opacity-50 focus-visible:outline-none group " + className
      }
      {...data}
    >
      <span
        aria-hidden
        className={
          "relative inline-flex h-4 w-7 items-center rounded-full border transition-colors " +
          "group-focus-visible:outline-2 group-focus-visible:outline-offset-2 group-focus-visible:outline-focus " +
          (checked ? "border-accent bg-accent" : "border-strong bg-elevated")
        }
      >
        <span
          className={
            "absolute size-3 rounded-full transition-transform " +
            (checked ? "translate-x-3.5 bg-white" : "translate-x-0.5 bg-fg-muted")
          }
        />
      </span>
      {!hideLabel && label}
    </button>
  );
}
