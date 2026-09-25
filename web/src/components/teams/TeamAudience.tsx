import { Slot } from "@radd/plugin-sdk";
import { TEAM_AUDIENCE_SLOT, type TeamAudienceProps } from "../../../../server/src/radd/modules/teams/ui/src/relationship-contract";
/** The caller retains all IDs while the owner supplies names, counts and editing. */
export function TeamAudience(props: TeamAudienceProps) {
  const fallback = <p className="text-sm text-fg-muted">Team selection unavailable. {props.value.length} saved team{props.value.length === 1 ? "" : "s"} preserved.</p>;
  return <Slot id={TEAM_AUDIENCE_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
