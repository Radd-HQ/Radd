import { Link } from "@tanstack/react-router";
import { RoutePath } from "../../lib/constants";
import { LINK_GROUP_LABELS } from "../../lib/meta";
import { ItemLinkType, type Item, type ItemLink } from "../../lib/types";

/**
 * Read-only issue `#`-mention backlinks (spec 52). The links are derived from the
 * text of items — outgoing = items this one references, incoming = items that
 * reference this one — so there is no add/remove here; editing the description is
 * how they change. Renders nothing when there are no mentions either way.
 */
export function MentionsSection({ item }: { item: Item }) {
  const links = item.links ?? { outgoing: [], incoming: [] };
  const references = links.outgoing.filter((l) => l.link_type === ItemLinkType.mentions);
  const referencedBy = links.incoming.filter((l) => l.link_type === ItemLinkType.mentions);
  if (references.length === 0 && referencedBy.length === 0) return null;

  return (
    <section className="mt-6 border-t border-subtle pt-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        Mentions
      </h3>
      <ul className="flex flex-col gap-3">
        <MentionGroup label={LINK_GROUP_LABELS[ItemLinkType.mentions].outgoing} links={references} />
        <MentionGroup
          label={LINK_GROUP_LABELS[ItemLinkType.mentions].incoming}
          links={referencedBy}
        />
      </ul>
    </section>
  );
}

function MentionGroup({ label, links }: { label: string; links: ItemLink[] }) {
  if (links.length === 0) return null;
  return (
    <li>
      <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-fg-faint">{label}</p>
      <ul className="flex flex-col gap-1">
        {links.map((link) => (
          <li
            key={link.id}
            className="flex items-center gap-2 rounded-md border border-subtle bg-surface/50 px-2 py-1.5"
          >
            <Link
              to={RoutePath.issue}
              params={{ itemKey: link.item.key }}
              className="flex min-w-0 flex-1 items-center gap-2 text-[13px] hover:underline"
            >
              <span className="shrink-0 font-mono text-[11px] text-fg-muted">{link.item.key}</span>
              <span className="truncate text-fg">{link.item.title}</span>
            </Link>
          </li>
        ))}
      </ul>
    </li>
  );
}
