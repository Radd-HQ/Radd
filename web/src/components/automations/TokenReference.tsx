/**
 * What `{{tokens}}` are available, shown where they are typed (spec 116).
 *
 * They existed since spec 58b and were documented only in a docstring, so the
 * only way to learn them was to read the server. The list comes from
 * `GET /automations/catalog`, which reads the same `TOKENS` table the resolver
 * sits next to — a token here that did not resolve would render as a literal
 * `{{…}}` in someone's issue title, and a test asserts the pairing.
 *
 * Clicking one inserts it, because the point of showing them is to use them.
 */
import { useState } from "react";
import { Braces } from "lucide-react";
import type { AutomationCatalog } from "../../lib/types";

interface TokenReferenceProps {
  catalog: AutomationCatalog | undefined;
  /** Whether this run has a target item — item tokens are blank without one. */
  hasItem: boolean;
  onInsert?: (token: string) => void;
}

export function TokenReference({ catalog, hasItem, onInsert }: TokenReferenceProps) {
  const [open, setOpen] = useState(false);
  const tokens = catalog?.tokens ?? [];
  if (tokens.length === 0) return null;

  return (
    <div className="rounded-[6px] border border-subtle">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[11px] uppercase tracking-wide text-fg-muted hover:text-heading cursor-pointer"
      >
        <Braces size={12} aria-hidden />
        Tokens you can use
        <span className="ml-auto text-fg-faint">{tokens.length}</span>
      </button>
      {open && (
        <ul className="flex flex-col gap-0.5 border-t border-subtle p-1.5">
          {tokens.map((entry) => {
            // An item token on an itemless trigger always renders blank. Saying
            // so beats letting someone build a title around nothing.
            const inert = entry.needs_item && !hasItem;
            return (
              <li key={entry.token}>
                <button
                  type="button"
                  disabled={!onInsert}
                  onClick={() => onInsert?.(entry.token)}
                  title={onInsert ? `Insert ${entry.token}` : entry.description}
                  className={`w-full rounded-[4px] px-1.5 py-1 text-left ${
                    onInsert ? "cursor-pointer hover:bg-elevated" : "cursor-default"
                  }`}
                >
                  <code className={`text-[11px] ${inert ? "text-fg-faint" : "text-accent-text"}`}>
                    {entry.token}
                  </code>
                  <span className="ml-1.5 text-[11px] text-fg-secondary">{entry.description}</span>
                  {inert && (
                    <span className="ml-1 text-[10px] uppercase text-fg-faint">
                      — blank on this trigger
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
