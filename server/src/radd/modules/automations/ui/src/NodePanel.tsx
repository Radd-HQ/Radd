/** The node list beside the canvas. Long trigger groups start collapsed; everything opens while searching. */
import { useMemo, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { groupTemplates, searchTemplates, type NodeTemplate } from "./automation-nodes";
import { NodeKind } from "./types";
import { NODE_KIND_ICON, NODE_KIND_TONE } from "./node-visuals";

interface NodePanelProps {
  templates: NodeTemplate[];
  onAdd: (template: NodeTemplate) => void;
}

export function NodePanel({ templates, onAdd }: NodePanelProps) {
  const [query, setQuery] = useState("");
  // Groups the user OPENED. Not a useState initializer: it ran before the catalogue loaded (a 3,316px panel).
  const [opened, setOpened] = useState<Set<string>>(new Set());

  const groups = useMemo(
    () => groupTemplates(searchTemplates(templates, query)),
    [templates, query],
  );
  const searching = query.trim().length > 0;

  return (
    <aside data-node-panel className="flex w-[248px] shrink-0 flex-col gap-2 rounded-[10px] border border-subtle bg-surface p-2">
      <label className="relative block">
        <Search
          size={13}
          className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-muted"
          aria-hidden
        />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search nodes…"
          aria-label="Search nodes"
          className="h-8 w-full rounded-[6px] border border-subtle bg-base pl-7 pr-2 text-[13px] text-fg outline-none placeholder:text-fg-faint focus:outline focus:outline-2 focus:outline-focus"
        />
      </label>

      <div className="flex max-h-[600px] flex-col gap-1 overflow-y-auto pr-0.5">
        {groups.length === 0 && (
          <p className="px-1 py-3 text-center text-xs text-fg-muted">No node matches “{query}”.</p>
        )}
        {groups.map(([group, entries]) => {
          // Searching opens everything; long trigger groups stay shut until asked for.
          const open = searching || opened.has(group) || !group.startsWith("Triggers");
          return (
            <section key={group}>
              <button
                type="button"
                onClick={() =>
                  setOpened((current) => {
                    const next = new Set(current);
                    if (open) next.delete(group);
                    else next.add(group);
                    return next;
                  })
                }
                aria-expanded={open}
                className="flex w-full items-center gap-1 rounded-[6px] px-1 py-1 text-left text-[11px] uppercase tracking-wide text-fg-muted hover:text-heading cursor-pointer"
              >
                <ChevronRight
                  size={12}
                  className={`transition-transform ${open ? "rotate-90" : ""}`}
                  aria-hidden
                />
                {group}
                <span className="ml-auto text-fg-faint">{entries.length}</span>
              </button>
              {open && (
                <ul className="flex flex-col">
                  {entries.map((template) => {
                    const Icon = NODE_KIND_ICON[template.kind];
                    return (
                      <li key={template.key}>
                        <button
                          type="button"
                          onClick={() => onAdd(template)}
                          title={`Add ${template.label}`}
                          className="flex w-full items-center gap-1.5 rounded-[6px] px-2 py-1.5 text-left text-[13px] text-fg hover:bg-elevated cursor-pointer"
                        >
                          <Icon
                            size={12}
                            className="shrink-0"
                            style={{ color: NODE_KIND_TONE[template.kind] }}
                            aria-hidden
                          />
                          <span className="truncate">{template.label}</span>
                          {template.kind === NodeKind.trigger && (
                            <span className="ml-auto shrink-0 text-[10px] uppercase text-fg-faint">
                              start
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}
