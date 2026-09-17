import { useIsAuthenticated } from "../../lib/hooks";
import { useToggleStarOnItem } from "../../lib/item-mutations";
import { pushToast } from "../../lib/toast";
import type { Item } from "../../lib/types";
import { StarButton } from "./ItemBadges";

/** Personal action: read access is sufficient; never starts a card drag or peek. */
export function QuickStar({item}: {item: Item}) {
  const authenticated = useIsAuthenticated();
  const mutation = useToggleStarOnItem();
  if (!authenticated) return null;
  const starred = mutation.isPending ? mutation.variables!.star : Boolean(item.starred);
  return <StarButton starred={starred} itemKey={item.key} disabled={mutation.isPending}
    onToggle={()=>mutation.mutate({itemId:item.id,star:!starred}, {
      onError:()=>pushToast(`Could not ${starred ? "unstar" : "star"} ${item.key}. Try again.`),
    })} />;
}
