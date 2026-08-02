import type { SlqSuggestion } from "../../lib/slq-suggest";

interface SlqSuggestDropdownProps {
  suggestions: SlqSuggestion[];
  activeIndex: number;
  contextLabel: string | null;
  /** Mouse hover highlights a row; keyboard drives it otherwise. */
  onHover: (index: number) => void;
  /** Accept a row (click). Hints (`insert === ""`) are inert. */
  onPick: (suggestion: SlqSuggestion) => void;
}

/**
 * SLQ autocomplete dropdown (spec 13): the suggestion list under the editor.
 * Presentational — open/active state and keyboard live in the editor + the
 * `useSlqAutocomplete` controller. Non-insertable hints render muted and
 * unselectable (e.g. the date-format hint).
 */
export function SlqSuggestDropdown({
  suggestions,
  activeIndex,
  contextLabel,
  onHover,
  onPick,
}: SlqSuggestDropdownProps) {
  return (
    <div
      className="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-md border border-strong bg-surface shadow-xl shadow-black/40"
      role="listbox"
    >
      {contextLabel && (
        <div className="border-b border-subtle px-2.5 py-1 text-[10px] font-medium uppercase tracking-wide text-fg-muted">
          {contextLabel}
        </div>
      )}
      <ul className="max-h-64 overflow-y-auto py-1">
        {suggestions.map((suggestion, index) => {
          const hint = suggestion.insert === "";
          const active = index === activeIndex;
          return (
            <li
              key={`${suggestion.value}-${index}`}
              role="option"
              aria-selected={active}
              // Keep focus in the textarea — accept on mousedown, not click/blur.
              onMouseDown={(event) => {
                event.preventDefault();
                if (!hint) onPick(suggestion);
              }}
              onMouseEnter={() => onHover(index)}
              className={
                "flex items-center justify-between gap-3 px-2.5 py-1 font-mono text-[13px] " +
                (hint
                  ? "cursor-default text-fg-muted"
                  : "cursor-pointer " + (active ? "bg-accent/20 text-heading" : "text-fg"))
              }
            >
              <span className="truncate">{suggestion.label}</span>
              {suggestion.detail && (
                <span className="shrink-0 text-[11px] text-fg-muted">{suggestion.detail}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
