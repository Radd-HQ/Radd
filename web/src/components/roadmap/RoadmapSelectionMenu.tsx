/** Right-click menu over a MULTI-selection (viewport wave): bulk verbs on the
 *  rubber-band/ctrl-click selection. Date/flag verbs ride the same
 *  one-optimistic-unit `applyPatches` the row menu uses; membership verbs go
 *  through the bulk pin seam (one invalidation, not N). */

import { BookmarkPlus, BookmarkX, CalendarX, Flag, FlagOff, X } from "lucide-react";
import type { RoadmapDatePatch } from "../../lib/item-mutations";
import type { Item } from "../../lib/types";
import { ContextMenu, type MenuNode } from "../ContextMenu";

export function RoadmapSelectionMenu({
  items,
  x,
  y,
  memberIds,
  canCurate,
  onToggleMembers,
  onPatch,
  onDeselect,
  onClose,
}: {
  /** The selected items (already resolved by the surface). */
  items: Item[];
  x: number;
  y: number;
  memberIds: ReadonlySet<string>;
  canCurate: boolean;
  onToggleMembers: (itemIds: string[], makeMember: boolean) => void;
  onPatch: (patches: RoadmapDatePatch[]) => void;
  onDeselect: () => void;
  onClose: () => void;
}) {
  const n = items.length;
  const plural = n === 1 ? "item" : "items";
  const nodes: MenuNode[] = [];

  if (canCurate) {
    const notMembers = items.filter((item) => !memberIds.has(item.id));
    const members = items.filter((item) => memberIds.has(item.id));
    if (notMembers.length > 0) {
      nodes.push({
        kind: "action",
        label: `Add ${notMembers.length} to this roadmap`,
        icon: BookmarkPlus,
        onSelect: () => onToggleMembers(notMembers.map((item) => item.id), true),
      });
    }
    if (members.length > 0) {
      nodes.push({
        kind: "action",
        label: `Remove ${members.length} from this roadmap`,
        icon: BookmarkX,
        onSelect: () => onToggleMembers(members.map((item) => item.id), false),
      });
    }
  }

  nodes.push({
    kind: "action",
    label: `Clear dates on ${n} ${plural}`,
    icon: CalendarX,
    hint: "Every selected item returns to the Unscheduled tray.",
    onSelect: () =>
      onPatch(
        items.map((item) => ({
          itemId: item.id,
          patch: { start_date: null, target_date: null },
          optimistic: { start_date: null, target_date: null },
        })),
      ),
  });
  const unflagged = items.filter((item) => !item.flagged);
  nodes.push(
    unflagged.length > 0
      ? {
          kind: "action",
          label: `Flag ${unflagged.length} ${unflagged.length === 1 ? "item" : "items"}`,
          icon: Flag,
          onSelect: () =>
            onPatch(
              unflagged.map((item) => ({
                itemId: item.id,
                patch: { flagged: true },
                optimistic: { flagged: true },
              })),
            ),
        }
      : {
          kind: "action",
          label: `Unflag ${n} ${plural}`,
          icon: FlagOff,
          onSelect: () =>
            onPatch(
              items.map((item) => ({
                itemId: item.id,
                patch: { flagged: false },
                optimistic: { flagged: false },
              })),
            ),
        },
  );
  nodes.push({ kind: "separator" });
  nodes.push({
    kind: "action",
    label: "Deselect",
    icon: X,
    onSelect: onDeselect,
  });

  return <ContextMenu x={x} y={y} items={nodes} onClose={onClose} />;
}
