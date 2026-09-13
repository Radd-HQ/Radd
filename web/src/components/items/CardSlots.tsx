import { StateCategory, type Item } from "../../lib/types";
import { todayIso } from "../../lib/dates";

/** True when the item's target date has passed and it isn't finished. */
export function isOverdue(item: Item): boolean {
  if (!item.target_date) return false;
  if (
    item.state.category === StateCategory.done ||
    item.state.category === StateCategory.canceled
  ) {
    return false;
  }
  return item.target_date < todayIso();
}

