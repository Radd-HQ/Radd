import { useId } from "react";
// The house date input (RADD-1376: the move into the SDK had dropped the shared focus ring for a
// border-only focus, and changed its size and surface). The picker follows the page's scheme.
const dateClasses =
  "h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading " +
  "focus:outline-2 focus:outline-offset-1 focus:outline-focus [color-scheme:inherit]";
export function DateField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-medium text-fg-secondary">
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        className={dateClasses}
      />
    </div>
  );
}
