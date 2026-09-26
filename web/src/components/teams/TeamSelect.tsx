import { Slot, Button, Modal } from "@radd/plugin-sdk";
import { TEAM_SELECT_SLOT, TEAM_CHOICES_SLOT, type TeamSelectProps, type TeamChoicesProps } from "@radd-plugin-ui/teams/relationship-contract";
/** The host's typed entries to the Teams pickers; Teams owns saved-reference queries and editing. */
export function TeamSelect(props: TeamSelectProps) {
  const fallback = <Button disabled variant="secondary" size={props.size} aria-label={props.label ?? props.placeholder}>Selection unavailable{props.selectedLabel || props.value ? ` · ${props.selectedLabel || props.value}` : ""}</Button>;
  return <Slot id={TEAM_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
export function TeamChoices(props: TeamChoicesProps) {
  const fallback = <Modal title="Selection unavailable" onClose={props.onClose}><p>This picker is unavailable. Saved values are preserved.</p>{props.footer}</Modal>;
  return <Slot id={TEAM_CHOICES_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
