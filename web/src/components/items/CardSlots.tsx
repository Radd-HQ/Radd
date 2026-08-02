import { CardSlot, type CardDisplayConfig, type CardSlotValue } from "../../lib/card-display";
import {
  ItemKind,
  StateCategory,
  type Item,
  type ItemRollup,
  type SlaBatchTimer,
} from "../../lib/types";
import { RollupRowBar } from "./RollupBar";
import {
  AssigneeAvatar,
  CycleChip,
  DueBadge,
  ParentTag,
  PointsChip,
  PriorityIcon,
  ReleaseChip,
  StatePill,
  TeamBadge,
  UnassignedSlot,
} from "./ItemBadges";
import { SlaRowChip } from "./SlaChips";

/** True when the item's target date has passed and it isn't finished. */
export function isOverdue(item: Item): boolean {
  if (!item.target_date) return false;
  if (
    item.state.category === StateCategory.done ||
    item.state.category === StateCategory.canceled
  ) {
    return false;
  }
  return item.target_date < new Date().toISOString().slice(0, 10);
}

/**
 * The configurable right-hand metadata cluster of a row (canonical slot
 * order, state pill last). Labels and issue-type are positioned by each
 * surface itself (they sit near the title), so they're not rendered here.
 */
export function RowMetaSlots({
  item,
  display,
  sla,
  rollup,
}: {
  item: Item;
  display: CardDisplayConfig;
  /** Batch timers for the sla slot (spec 63) — surfaces that fetch them pass
   * `slaByItem[item.id]`; omitted (or no matched policy) renders nothing. */
  sla?: SlaBatchTimer[];
  /** Epic-progress aggregates for the progress slot (spec 76) — surfaces pass
   * `rollupByItem[item.id]`; renders only on epic-kind items. */
  rollup?: ItemRollup;
}) {
  const on = (slot: CardSlotValue) => display.slots.includes(slot);
  return (
    <>
      {on(CardSlot.parent) && item.parent && <ParentTag parent={item.parent} />}
      {on(CardSlot.cycle) && item.cycle && <CycleChip cycle={item.cycle} />}
      {on(CardSlot.release) && item.release && <ReleaseChip release={item.release} />}
      {on(CardSlot.targetDate) && item.target_date && (
        <DueBadge date={item.target_date} overdue={isOverdue(item)} />
      )}
      {on(CardSlot.team) && item.team && <TeamBadge team={item.team} />}
      {on(CardSlot.priority) && <PriorityIcon priority={item.priority} size={13} />}
      {on(CardSlot.assignee) &&
        (item.assignee ? <AssigneeAvatar assignee={item.assignee} /> : <UnassignedSlot />)}
      {on(CardSlot.sla) && (
        // Fixed slot (chip or empty) so the assignee/state columns line up.
        <span className="inline-flex w-24 shrink-0 items-center justify-end">
          <SlaRowChip timers={sla} />
        </span>
      )}
      {on(CardSlot.points) && item.estimate_points != null && (
        <PointsChip points={item.estimate_points} />
      )}
      {on(CardSlot.progress) && item.kind === ItemKind.epic && (
        <RollupRowBar rollup={rollup} />
      )}
      {on(CardSlot.state) && <StatePill state={item.state} />}
    </>
  );
}
