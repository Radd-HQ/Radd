import { useNavigate } from "@tanstack/react-router";
import {
  CircleDot,
  Copy,
  ExternalLink,
  Flag,
  Link as LinkIcon,
  SignalHigh,
  Star,
  UserRound,
} from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { PRIORITY_META, PRIORITY_ORDER } from "../../lib/meta";
import { pushToast, ToastKind } from "../../lib/toast";
import type { Item, ItemUpdate, Me, State } from "../../lib/types";
import { ContextMenu, type MenuNode } from "../ContextMenu";

interface ItemContextMenuProps {
  item: Item;
  x: number;
  y: number;
  onClose: () => void;
  /** Apply a mutation (optimistic partial merged into the view cache). */
  onAct: (patch: ItemUpdate, optimistic: Partial<Item>) => void;
  /** Toggle the personal star (available to anyone who can read the item). */
  onStar: (item: Item, star: boolean) => void;
  /** Gates the mutating actions; false → only Open/Star/Copy show. */
  canUpdate: boolean;
  /** Opens the searchable cycle picker after this menu closes. */
  onChooseCycle: () => void;
  states?: State[];
  currentUser: Me | null;
}

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    pushToast(`Copied ${what}`, ToastKind.success);
  } catch {
    pushToast(`Couldn't copy ${what}`, ToastKind.error);
  }
}

/** Right-click quick-actions menu for a work item (spec 24). */
export function ItemContextMenu({
  item,
  x,
  y,
  onClose,
  onAct,
  onStar,
  canUpdate,
  onChooseCycle,
  states,
  currentUser,
}: ItemContextMenuProps) {
  const navigate = useNavigate();
  const nodes: MenuNode[] = [];

  nodes.push({
    kind: "action",
    label: "Open",
    icon: ExternalLink,
    onSelect: () => void navigate({ to: RoutePath.issue, params: { itemKey: item.key } }),
  });

  const starred = Boolean(item.starred);
  nodes.push({
    kind: "action",
    label: starred ? "Unstar" : "Star",
    icon: Star,
    checked: starred,
    onSelect: () => onStar(item, !starred),
  });

  if (canUpdate) {
    nodes.push({ kind: "separator" });

    nodes.push({
      kind: "submenu",
      label: "Set priority",
      icon: SignalHigh,
      items: PRIORITY_ORDER.map((priority) => ({
        kind: "action",
        label: PRIORITY_META[priority].label,
        checked: item.priority === priority,
        onSelect: () => onAct({ priority }, { priority }),
      })),
    });

    if (states && states.length > 0) {
      nodes.push({
        kind: "submenu",
        label: "Set state",
        icon: CircleDot,
        items: [...states]
          .sort((a, b) => a.position - b.position)
          .map((state) => ({
            kind: "action",
            label: state.name,
            checked: item.state.id === state.id,
            onSelect: () =>
              onAct(
                { state_id: state.id },
                { state: { id: state.id, name: state.name, category: state.category } },
              ),
          })),
      });
    }

    if (currentUser) {
      const isMe = item.assignee?.id === currentUser.id;
      nodes.push({
        kind: "action",
        label: isMe ? "Unassign" : "Assign to me",
        icon: UserRound,
        onSelect: () =>
          isMe
            ? onAct({ assignee_id: null }, { assignee: null })
            : onAct(
                { assignee_id: currentUser.id },
                { assignee: { id: currentUser.id, name: currentUser.name } },
              ),
      });
    }

    nodes.push({ kind: "action", label: "Move to cycle…", onSelect: onChooseCycle });

    const flagged = Boolean(item.flagged);
    nodes.push({
      kind: "action",
      label: flagged ? "Unflag" : "Flag",
      icon: Flag,
      checked: flagged,
      onSelect: () => onAct({ flagged: !flagged }, { flagged: !flagged }),
    });
  }

  nodes.push({ kind: "separator" });
  nodes.push({
    kind: "action",
    label: "Copy key",
    icon: Copy,
    onSelect: () => void copy(item.key, item.key),
  });
  nodes.push({
    kind: "action",
    label: "Copy link",
    icon: LinkIcon,
    onSelect: () => void copy(`${window.location.origin}/issues/${item.key}`, "link"),
  });

  return <ContextMenu x={x} y={y} items={nodes} onClose={onClose} />;
}
