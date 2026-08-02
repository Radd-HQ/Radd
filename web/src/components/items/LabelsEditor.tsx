import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { labelsQuery } from "../../lib/queries";
import { TokenMultiSelect, type TokenOption } from "../TokenMultiSelect";

interface LabelsEditorProps {
  value: string[];
  onChange: (labels: string[]) => void;
  disabled?: boolean;
  /** Reason shown on hover when disabled (e.g. a field-grant restriction). */
  lockedReason?: string;
}

/**
 * Issue labels as a single-row token editor: type to filter existing labels + pick, or free-text a
 * new one (Enter / comma) — labels auto-create server-side on first use. × / Backspace removes.
 */
export function LabelsEditor({ value, onChange, disabled, lockedReason }: LabelsEditorProps) {
  const id = useId();
  const labels = useQuery(labelsQuery());
  const options: TokenOption[] = (labels.data ?? []).map((label) => ({
    value: label.name,
    label: label.name,
  }));

  return (
    <div className="flex flex-col gap-1.5" title={disabled ? lockedReason : undefined}>
      <label htmlFor={id} className="text-xs font-medium text-fg-secondary">
        Labels
      </label>
      <TokenMultiSelect
        id={id}
        value={value}
        onChange={onChange}
        options={options}
        allowCreate
        disabled={disabled}
        placeholder="Add label…"
        ariaLabel="Labels"
      />
    </div>
  );
}
