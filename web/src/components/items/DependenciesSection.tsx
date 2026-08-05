import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { errorMessage } from "../../lib/api";
import { RoutePath } from "../../lib/constants";
import { useDebounced } from "../../lib/hooks";
import { useAddItemLink, useRemoveItemLink } from "../../lib/item-mutations";
import { linkSearchQuery, linkTypesQuery } from "../../lib/queries";
import {
  ItemLinkType,
  type Item,
  type ItemLink,
  type ItemLinkCreate,
  type ItemLinks,
  type Project,
} from "../../lib/types";
import { Button } from "../Button";
import { Select } from "../Select";
import { IconButton } from "../IconButton";

/**
 * Dependency links for an item (spec 18/91): edges grouped by their directional
 * label ("blocks" / "is blocked by" / "relates to" / any custom type), each
 * linking to the far item's page with a remove (×), plus an add-link row whose
 * type dropdown offers the link types scoped to this project. Links may span
 * projects (spec 80) — the typeahead searches server-wide, same-project first.
 */

interface LinkGroup {
  key: string;
  label: string;
  links: ItemLink[];
}

/** How many dependency edges the section will show — the collapsed card's count
 * chip. Mirrors `buildLinkGroups`' rule: mentions are NOT dependencies. */
export function dependencyLinkCount(links: ItemLinks | null | undefined): number {
  if (!links) return 0;
  return [...links.outgoing, ...links.incoming].filter(
    (edge) => edge.link_type !== ItemLinkType.mentions,
  ).length;
}

/** Group edges by their directional label — this naturally splits directed types
 * (outward vs inward), merges symmetric ones, and works for custom types. The
 * auto-managed `mentions` type is shown in its own section, not here. */
function buildLinkGroups(links: ItemLinks): LinkGroup[] {
  const byLabel = new Map<string, ItemLink[]>();
  for (const edge of [...links.outgoing, ...links.incoming]) {
    if (edge.link_type === ItemLinkType.mentions) continue;
    const bucket = byLabel.get(edge.label) ?? [];
    bucket.push(edge);
    byLabel.set(edge.label, bucket);
  }
  return [...byLabel.entries()].map(([label, edges]) => ({ key: label, label, links: edges }));
}

export function DependenciesSection({ project, item }: { project: Project; item: Item }) {
  const links = item.links ?? { outgoing: [], incoming: [] };
  const groups = buildLinkGroups(links);
  const addLink = useAddItemLink(project.id);
  const removeLink = useRemoveItemLink(project.id);

  return (
    <div>
      {groups.length === 0 ? (
        <p className="text-[13px] text-fg-faint">No dependencies yet.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {groups.map((group) => (
            <li key={group.key}>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
                {group.label}
              </p>
              <ul className="flex flex-col gap-1">
                {group.links.map((link) => (
                  <li
                    key={link.id}
                    className="group/link flex items-center gap-2 rounded-md border border-subtle bg-surface/50 px-2 py-1.5"
                  >
                    <Link
                      to={RoutePath.issue}
                      params={{ itemKey: link.item.key }}
                      className="flex min-w-0 flex-1 items-center gap-2 text-[13px] hover:underline"
                    >
                      <span className="shrink-0 font-mono text-[11px] text-fg-muted">
                        {link.item.key}
                      </span>
                      <span className="truncate text-fg">{link.item.title}</span>
                    </Link>
                    <IconButton
                      danger
                      onClick={() => removeLink.mutate({ itemId: item.id, linkId: link.id })}
                      disabled={removeLink.isPending}
                      aria-label={`Remove link to ${link.item.key}`}
                    >
                      <X size={13} />
                    </IconButton>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      {removeLink.isError && (
        <p className="mt-2 text-xs text-red-400">Remove failed: {errorMessage(removeLink.error)}</p>
      )}

      <AddLinkRow project={project} item={item} addLink={addLink} />
    </div>
  );
}

function AddLinkRow({
  project,
  item,
  addLink,
}: {
  project: Project;
  item: Item;
  addLink: ReturnType<typeof useAddItemLink>;
}) {
  const linkTypes = useQuery(linkTypesQuery(project.id));
  const typeOptions = linkTypes.data ?? [];
  const [linkType, setLinkType] = useState("");
  const activeType = linkType || typeOptions[0]?.key || "blocks";
  const [target, setTarget] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const query = useDebounced(target.trim(), 200);
  const search = useQuery({
    ...linkSearchQuery(project.id, query, item.id),
    enabled: open && query.length > 0,
  });
  const suggestions = open ? (search.data ?? []) : [];

  const submitBody = (body: ItemLinkCreate) => {
    setLocalError(null);
    addLink.mutate(
      { itemId: item.id, body },
      {
        onSuccess: () => {
          setTarget("");
          setOpen(false);
        },
      },
    );
  };

  const submitNumber = (raw: string) => {
    setLocalError(null);
    const trimmed = raw.trim();
    if (!trimmed) return;
    // Typed form: a per-project number ("23") or a same-project key ("TD-23").
    // Cross-project targets come from the typeahead (addressed by id, spec 80).
    const numberPart = trimmed.includes("-") ? trimmed.slice(trimmed.lastIndexOf("-") + 1) : trimmed;
    const targetNumber = Number(numberPart);
    if (!Number.isInteger(targetNumber) || targetNumber <= 0) {
      setLocalError("Enter an item number or key, e.g. 23 or TD-23.");
      return;
    }
    submitBody({ target_number: targetNumber, link_type: activeType });
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submitNumber(target);
      }}
      className="mt-3 flex items-end gap-2"
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor="link-type" className="text-xs font-medium text-fg-secondary">
          Link
        </label>
        <Select
          id="link-type"
          value={activeType}
          onChange={setLinkType}
          options={typeOptions.map((type) => ({ value: type.key, label: type.outward_name }))}
        />
      </div>
      <div className="relative flex flex-1 flex-col gap-1.5">
        <label htmlFor="link-target" className="text-xs font-medium text-fg-secondary">
          Item
        </label>
        <input
          id="link-target"
          value={target}
          onChange={(event) => {
            setTarget(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          autoComplete="off"
          placeholder="Search by title, number, or key…"
          className="h-8 rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
        {suggestions.length > 0 && (
          <ul className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-md border border-strong bg-surface py-1 shadow-xl">
            {suggestions.map((candidate) => (
              <li key={candidate.id}>
                <button
                  type="button"
                  // onMouseDown fires before the input's onBlur, so the pick lands.
                  // By id: candidates may live in another project (spec 80),
                  // where their per-project number would resolve wrongly.
                  onMouseDown={(event) => {
                    event.preventDefault();
                    submitBody({ target_id: candidate.id, link_type: activeType });
                  }}
                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] hover:bg-elevated cursor-pointer"
                >
                  <span className="shrink-0 font-mono text-[11px] text-fg-muted">
                    {candidate.key}
                  </span>
                  <span className="truncate text-fg">{candidate.title}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button type="submit" disabled={addLink.isPending || target.trim() === ""}>
        <Plus size={14} aria-hidden />
        {addLink.isPending ? "Adding…" : "Add"}
      </Button>
      {(localError || addLink.isError) && (
        <span className="pb-2 text-xs text-red-400">
          {localError ?? errorMessage(addLink.error)}
        </span>
      )}
    </form>
  );
}
