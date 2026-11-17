import { useId, type InputHTMLAttributes } from "react";

// The house date input; the picker follows the page's scheme.
const dateClasses =
  "h-8 rounded-md border border-strong bg-surface px-2 text-row text-heading " +
  "focus:outline-2 focus:outline-offset-1 focus:outline-focus " +
  "disabled:cursor-not-allowed disabled:opacity-70 [color-scheme:inherit]";

/** THE date input (RADD-1563). There were seven hand-styled `<input type="date">`
 *  in four looks, two of them pinning a dark picker onto the light theme. Every
 *  bare date input is this one; a labelled one is `DateField` or a `TextField`
 *  with `type="date"`. `className` is for layout (width, margin), not for looks. */
export function DateInput({ className = "", ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  return <input {...props} type="date" className={`${dateClasses} ${className}`} />;
}

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
      <DateInput id={id} value={value ?? ""} onChange={(event) => onChange(event.target.value || null)} />
    </div>
  );
}
