import { Slot, Button } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT, type ProjectSelectProps } from "@radd-plugin-ui/projects/picker-contract";
/** The host's typed entry to the Projects select; Projects owns rendering and queries. */
export function ProjectSelect(props: ProjectSelectProps) {
  const fallback = <Button disabled variant="secondary" aria-label={props.label}>Selection unavailable{props.value ? ` · ${props.value}` : ""}</Button>;
  return <Slot id={PROJECT_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
