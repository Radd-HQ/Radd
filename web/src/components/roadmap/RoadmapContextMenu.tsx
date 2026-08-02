import { useNavigate } from "@tanstack/react-router";
import {
  BookmarkPlus,
  BookmarkX,
  CalendarArrowDown,
  CalendarPlus,
  CalendarX,
  ChevronsDownUp,
  ExternalLink,
  Flag,
  Focus,
  Link2,
  Shrink,
  Wand2,
  X,
} from "lucide-react";
import { RoutePath } from "../../lib/constants";
import type { RoadmapDatePatch } from "../../lib/item-mutations";
import { ItemLinkType, type Item, type ItemLink } from "../../lib/types";
import { ContextMenu, type MenuNode } from "../ContextMenu";
import { RANK_CHAIN_MIN_ITEMS, RoadmapRowKind, type RoadmapRow } from "./roadmap-model";

/**
 * Right-click verbs for a roadmap bar (specs 77 + 78 + 82). EPIC bars: Fit to
 * children / Bring children into roadmap / Auto-schedule children / Order
 * children by date / Expand-collapse / Clear dates / Open. LEAF bars: Clear
 * dates / Open / Flag.
 * Every bar carries a "Dependencies" submenu listing its manual links with
 * per-link Remove. Disabled entries carry the reason as the ContextMenu hint.
 * Date mutations flow through the roadmap patch unit (`onPatch`), so
 * optimistic paint + rollback behave like the drag gestures; the date-order
 * verb rewrites the global manual rank instead (spec 82).
 */

interface RoadmapContextMenuProps {
  row: RoadmapRow;
  x: number;
  y: number;
  onClose: () => void;
  collapsed: boolean;
  /** This epic is in the solo set (focused-scheduling mode). */
  soloed: boolean;
  /** Curated membership (roadmap wave): pinned to this roadmap? */
  isMember: boolean;
  /** View edit rights gate curation — viewers browse, they don't pin. */
  canCurate: boolean;
  /** Rows follow the manual rank (spec 82) — gates "Order children by date". */
  rankOrdered: boolean;
  onToggleCollapse: (epicId: string) => void;
  onToggleSolo: (epicId: string) => void;
  onToggleMember: (itemId: string, makeMember: boolean) => void;
  onPatch: (patches: RoadmapDatePatch[]) => void;
  /** "Bring children into roadmap" — as-is date fills, no reflow. */
  onImportChildren: (row: RoadmapRow) => void;
  /** "Auto-schedule children" (spec 78) — the owner supplies durations/edges. */
  onAutoSchedule: (row: RoadmapRow) => void;
  /** "Order children by date" (spec 82) — rank chain over the loaded children. */
  onOrderChildren: (row: RoadmapRow) => void;
  /** Remove one manual link (either endpoint id works for DELETE). */
  onRemoveLink: (itemId: string, linkId: string) => void;
}

/** The "Dependencies" submenu body: one Remove action per manual link. */
function dependencyNodes(item: Item, onRemoveLink: (itemId: string, linkId: string) => void): MenuNode[] {
  const verbFor = (linkType: string, incoming: boolean): string => {
    if (linkType === ItemLinkType.blocks) return incoming ? "blocked by" : "blocks";
    if (linkType === ItemLinkType.duplicates) return incoming ? "duplicated by" : "duplicates";
    return "relates";
  };
  const nodes: MenuNode[] = [];
  const push = (links: ItemLink[], incoming: boolean) => {
    for (const link of links) {
      if (link.link_type === ItemLinkType.mentions) continue; // auto-derived
      nodes.push({
        kind: "action",
        label: `${verbFor(link.link_type, incoming)} ${link.item.key}`,
        icon: X,
        hint: "Remove this link.",
        onSelect: () => onRemoveLink(item.id, link.id),
      });
    }
  };
  push(item.links?.outgoing ?? [], false);
  push(item.links?.incoming ?? [], true);
  if (nodes.length === 0) {
    nodes.push({ kind: "action", label: "No links", disabled: true, onSelect: () => undefined });
  }
  return nodes;
}

export function RoadmapContextMenu({
  row,
  x,
  y,
  onClose,
  collapsed,
  soloed,
  isMember,
  canCurate,
  rankOrdered,
  onToggleCollapse,
  onToggleSolo,
  onToggleMember,
  onPatch,
  onImportChildren,
  onAutoSchedule,
  onOrderChildren,
  onRemoveLink,
}: RoadmapContextMenuProps) {
  const navigate = useNavigate();
  const { item } = row;
  const nodes: MenuNode[] = [];

  const clearDates: MenuNode = {
    kind: "action",
    label: "Clear dates",
    icon: CalendarX,
    disabled: row.derived,
    hint: row.derived
      ? "The epic has no dates of its own — this span is derived from its children."
      : "Remove both dates — the item returns to the Unscheduled tray.",
    onSelect: () =>
      onPatch([
        {
          itemId: item.id,
          patch: { start_date: null, target_date: null },
          optimistic: { start_date: null, target_date: null },
        },
      ]),
  };

  const open: MenuNode = {
    kind: "action",
    label: "Open",
    icon: ExternalLink,
    onSelect: () => void navigate({ to: RoutePath.issue, params: { itemKey: item.key } }),
  };

  const dependencies: MenuNode = {
    kind: "submenu",
    label: "Dependencies",
    icon: Link2,
    items: dependencyNodes(item, onRemoveLink),
  };

  if (row.rowKind === RoadmapRowKind.epic) {
    const bounds = row.childrenBounds;
    nodes.push({
      kind: "action",
      label: "Fit to children",
      icon: Shrink,
      disabled: !bounds,
      hint: bounds
        ? `Set the epic to exactly ${bounds.minStart} → ${bounds.maxTarget}.`
        : "No scheduled children to fit to.",
      onSelect: () => {
        if (!bounds) return;
        onPatch([
          {
            itemId: item.id,
            patch: { start_date: bounds.minStart, target_date: bounds.maxTarget },
            optimistic: { start_date: bounds.minStart, target_date: bounds.maxTarget },
          },
        ]);
      },
    });

    // The AS-IS counterpart to Auto-schedule: fill only the missing dates of
    // the epic's children (existing dates untouched), fit the epic around
    // the result — no reflow, no rank rewrite. The full child list (date-less
    // ones included) is fetched when the verb runs (perf wave) — the roadmap
    // itself only ever loads the scheduled children.
    nodes.push({
      kind: "action",
      label: "Bring children into roadmap",
      icon: CalendarPlus,
      hint: "Place the epic's unscheduled children as-is at the epic's start — an estimate sets the bar length, otherwise one day; already-dated children stay put. The epic is fit to the result.",
      onSelect: () => onImportChildren(row),
    });

    nodes.push({
      kind: "action",
      label: "Auto-schedule children",
      icon: Wand2,
      hint: "Lay out ALL the epic's children from its start: estimates set bar lengths, blocks-links order them, and items sharing an assignee run one after another. The epic is fit to the result.",
      onSelect: () => onAutoSchedule(row),
    });

    // Spec 82: rows no longer re-sort by date — this verb makes date order a
    // deliberate, persistent act (a sequential rank chain over the children).
    const canDateOrder = rankOrdered && row.children.length >= RANK_CHAIN_MIN_ITEMS;
    nodes.push({
      kind: "action",
      label: "Order children by date",
      icon: CalendarArrowDown,
      disabled: !canDateOrder,
      hint: !rankOrdered
        ? "This view has an explicit ORDER BY — rows don't follow the manual rank."
        : row.children.length < RANK_CHAIN_MIN_ITEMS
          ? "Fewer than two loaded children — nothing to reorder."
          : "Rewrite the manual rank so the children read start-date first (date-less last). The order is global — rank-sorted lists follow it too.",
      onSelect: () => onOrderChildren(row),
    });

    nodes.push({
      kind: "action",
      label: collapsed ? "Expand children" : "Collapse children",
      icon: ChevronsDownUp,
      disabled: row.scheduledChildCount === 0,
      hint: row.scheduledChildCount === 0 ? "No scheduled children." : undefined,
      onSelect: () => onToggleCollapse(item.id),
    });

    nodes.push({
      kind: "action",
      label: soloed ? "Unsolo epic" : "Solo epic",
      icon: Focus,
      hint: soloed
        ? "Bring the other rows back."
        : "Show only this epic and its children — focus mode for scheduling one epic. Solo more epics to compare; session-only.",
      onSelect: () => onToggleSolo(item.id),
    });

    if (canCurate) {
      nodes.push({
        kind: "action",
        label: isMember ? "Remove from this roadmap" : "Add to this roadmap",
        icon: isMember ? BookmarkX : BookmarkPlus,
        hint: isMember
          ? "Unpin — the Members toggle stops showing it."
          : "Pin to this roadmap's curated set — the Members toggle shows only pinned items (an epic brings its children along).",
        onSelect: () => onToggleMember(item.id, !isMember),
      });
    }

    nodes.push(dependencies);
    nodes.push({ kind: "separator" });
    nodes.push(clearDates);
    nodes.push(open);
  } else {
    const flagged = Boolean(item.flagged);
    if (canCurate) {
      nodes.push({
        kind: "action",
        label: isMember ? "Remove from this roadmap" : "Add to this roadmap",
        icon: isMember ? BookmarkX : BookmarkPlus,
        hint: isMember
          ? "Unpin — the Members toggle stops showing it."
          : "Pin to this roadmap's curated set — the Members toggle shows only pinned items.",
        onSelect: () => onToggleMember(item.id, !isMember),
      });
    }
    nodes.push(dependencies);
    nodes.push(clearDates);
    nodes.push(open);
    nodes.push({
      kind: "action",
      label: flagged ? "Unflag" : "Flag",
      icon: Flag,
      checked: flagged,
      onSelect: () =>
        onPatch([
          { itemId: item.id, patch: { flagged: !flagged }, optimistic: { flagged: !flagged } },
        ]),
    });
  }

  return <ContextMenu x={x} y={y} items={nodes} onClose={onClose} />;
}
