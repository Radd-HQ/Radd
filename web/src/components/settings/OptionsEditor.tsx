import { useId } from "react";
import { TokenMultiSelect } from "../TokenMultiSelect";

interface OptionsEditorProps {
  label: string;
  value: string[];
  onChange: (options: string[]) => void;
  hint?: string;
  error?: string;
}

/**
 * A field definition's options list (select / multi_select): a single-row token editor — type +
 * Enter (or comma) adds, × / Backspace removes. Free-text (each option is its own value).
 */
export function OptionsEditor({ label, value, onChange, hint, error }: OptionsEditorProps) {
  const id = useId();
  const hintId = `${id}-hint`;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-medium text-fg-secondary">
        {label}
      </label>
      <TokenMultiSelect
        id={id}
        value={value}
        onChange={onChange}
        options={[]}
        allowCreate
        invalid={Boolean(error)}
        placeholder="Add option…"
        ariaLabel={label}
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
