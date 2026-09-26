import { useEffect } from "react";
import type { SlqFieldProps } from "@radd/plugin-sdk";
import { SlqProbeStatus, useSlqValidation } from "../../lib/hooks";
import { SlqEditor } from "./SlqEditor";

/**
 * The SDK's SlqField, as the shell provides it (RADD-1393): the house SLQ editor with its live
 * validation line and autocomplete, scoped to a project when the form has one, reporting whether
 * the draft parses so a plugin's form can hold Save until it does.
 */
export function SlqField({ label, value, onChange, projectId, placeholder, onValidity }: SlqFieldProps) {
  const probe = useSlqValidation(projectId ?? null, value);
  const valid = probe.status !== SlqProbeStatus.invalid;
  useEffect(() => { onValidity?.(valid); }, [valid, onValidity]);
  return (
    <SlqEditor label={label} value={value} onChange={onChange} probe={probe} placeholder={placeholder}
      suggestScope={projectId ? { project_id: projectId } : {}} />
  );
}
