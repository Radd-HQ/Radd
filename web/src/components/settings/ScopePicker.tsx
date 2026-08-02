import type { Project } from "../../lib/types";
import { TokenMultiSelect, type TokenOption } from "../TokenMultiSelect";

/**
 * Scope selector shared by fields, link types, and grants (spec 92) — now the app-wide token
 * multiselect (spec 94 UX pass). Chips are the chosen projects on a single scrolling row; an EMPTY
 * selection means GLOBAL (everywhere), signalled by the placeholder. Type to filter projects by key
 * or name; × / Backspace to remove.
 */
export function ScopePicker({
  value,
  onChange,
  projects,
  disabled = false,
  globalLabel = "Global",
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  projects: Project[];
  disabled?: boolean;
  globalLabel?: string;
}) {
  const options: TokenOption[] = projects.map((p) => ({ value: p.id, label: p.key, hint: p.name }));
  return (
    <div className="min-w-44 max-w-72">
      <TokenMultiSelect
        value={value}
        onChange={onChange}
        options={options}
        disabled={disabled}
        placeholder={`${globalLabel} — everywhere`}
        ariaLabel="Project scope"
      />
    </div>
  );
}
