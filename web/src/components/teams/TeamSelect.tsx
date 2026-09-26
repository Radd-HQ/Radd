import { Slot, Button } from "@radd/plugin-sdk";
import { TEAM_SELECT_SLOT, type TeamSelectProps } from "@radd-plugin-ui/teams/relationship-contract";
/** The host's typed entries to the Teams pickers; Teams owns saved-reference queries and editing. */
export function TeamSelect(props: TeamSelectProps) {
  const fallback = <Button disabled variant="secondary" size={props.size} aria-label={props.label ?? props.placeholder}>Selection unavailable{props.selectedLabel || props.value ? ` · ${props.selectedLabel || props.value}` : ""}</Button>;
  return <Slot id={TEAM_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
