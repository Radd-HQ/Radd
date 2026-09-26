import { useId } from "react";
const dateClasses = "rounded-md border border-strong bg-elevated px-2 py-1.5 text-sm text-fg outline-none focus:border-accent [color-scheme:inherit]";
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
