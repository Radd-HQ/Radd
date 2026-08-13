/**
 * What `{{tokens}}` are available HERE, shown where they are typed (spec 116,
 * made topology-aware by spec 120).
 *
 * Two lists, and the difference between them is the point:
 *
 * * the ROOTS — `{{item.key}}`, `{{actor.name}}`, `{{payload.…}}` — come from
 *   `GET /automations/catalog`, which reads the same table the resolver sits
 *   next to. A token listed here that did not resolve would render as a literal
 *   `{{…}}` in someone's issue title, and a test asserts the pairing.
 * * the VARIABLES are computed from the graph: only nodes that this one can be
 *   reached from, only ones that have been NAMED, only the outputs they declare.
 *   Listing every named node instead would offer values from branches that never
 *   run with this one — tokens that compile, save, and resolve to nothing.
 *
 * Clicking one inserts it into whichever field was last focused, because the
 * point of showing them is to use them.
 */
import { useState } from "react";
import { Braces, CornerDownRight } from "lucide-react";
import type {
  AutomationCatalog,
  AutomationEdge,
  AutomationNode,
} from "../../lib/types";
import { upstreamProducers } from "../../lib/automation-outputs";

interface TokenReferenceProps {
  catalog: AutomationCatalog | undefined;
  /** Whether this run has a target item — item tokens are blank without one. */
  hasItem: boolean;
  /** The node being edited, plus the graph, so the variables listed are the ones
   * that can actually reach it. Omitted on a surface with no graph in scope, in
   * which case only the roots are shown. */
  node?: AutomationNode;
  nodes?: AutomationNode[];
  edges?: AutomationEdge[];
  onInsert?: (token: string) => void;
}

export function TokenReference({
  catalog,
  hasItem,
  node,
  nodes = [],
  edges = [],
  onInsert,
}: TokenReferenceProps) {
  const [open, setOpen] = useState(false);
  const tokens = catalog?.tokens ?? [];
  const producers = node ? upstreamProducers(node.id, nodes, edges, catalog) : [];
  const variableCount = producers.reduce((total, entry) => total + entry.outputs.length, 0);
  if (tokens.length === 0 && variableCount === 0) return null;

  return (
    <div className="rounded-[6px] border border-subtle" data-token-reference>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[11px] uppercase tracking-wide text-fg-muted hover:text-heading cursor-pointer"
      >
        <Braces size={12} aria-hidden />
        Tokens you can use
        <span className="ml-auto text-fg-faint">{tokens.length + variableCount}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-1.5 border-t border-subtle p-1.5">
          {producers.length > 0 && (
            <div className="flex flex-col gap-0.5" data-token-variables>
              <p className="px-1.5 text-[10px] uppercase tracking-wide text-fg-faint">
                From nodes above this one
              </p>
              {producers.map(({ node: producer, outputs }) => (
                <ul key={producer.id} className="flex flex-col gap-0.5">
                  {outputs.map((output) => (
                    <li key={output.name}>
                      <TokenRow
                        token={`{{${producer.name}.${output.name}}}`}
                        description={
                          output.choices.length > 0
                            ? `${output.description || output.label} — one of ${output.choices.join(", ")}`
                            : output.description || output.label
                        }
                        onInsert={onInsert}
                        variable
                      />
                    </li>
                  ))}
                </ul>
              ))}
            </div>
          )}
          <ul className="flex flex-col gap-0.5">
            {tokens.map((entry) => (
              <li key={entry.token}>
                <TokenRow
                  token={entry.token}
                  description={entry.description}
                  // An item token on an itemless trigger always renders blank.
                  // Saying so beats letting someone build a title around nothing.
                  inert={entry.needs_item && !hasItem}
                  onInsert={onInsert}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TokenRow({
  token,
  description,
  inert = false,
  variable = false,
  onInsert,
}: {
  token: string;
  description: string;
  inert?: boolean;
  variable?: boolean;
  onInsert?: (token: string) => void;
}) {
  return (
    <button
      type="button"
      data-token={token}
      disabled={!onInsert}
      onClick={() => onInsert?.(token)}
      title={onInsert ? `Insert ${token}` : description}
      className={`flex w-full items-baseline gap-1.5 rounded-[4px] px-1.5 py-1 text-left ${
        onInsert ? "cursor-pointer hover:bg-elevated" : "cursor-default"
      }`}
    >
      {variable && (
        <CornerDownRight size={10} className="shrink-0 text-fg-faint" aria-hidden />
      )}
      <code
        className={`text-[11px] ${
          inert ? "text-fg-faint" : variable ? "text-accent-text-strong" : "text-accent-text"
        }`}
      >
        {token}
      </code>
      <span className="min-w-0 truncate text-[11px] text-fg-secondary">{description}</span>
      {inert && (
        <span className="ml-auto shrink-0 text-[10px] uppercase text-fg-faint">
          — blank on this trigger
        </span>
      )}
    </button>
  );
}
