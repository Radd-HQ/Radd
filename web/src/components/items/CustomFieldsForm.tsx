import { Slot } from "@radd/plugin-sdk";
import { FIELD_CONTROL_SLOT, FIELDS_FORM_SLOT, type ControlProps, type CustomFieldsFormProps } from "@radd-plugin-ui/fields/control-contract";
/** The host's typed entries to the Fields form controls; Fields owns rendering and change semantics. */
export function CustomFieldsForm(props: CustomFieldsFormProps) {
  const fallback = <p className="text-sm text-fg-muted">Fields are unavailable. Saved values are preserved.</p>;
  return <Slot id={FIELDS_FORM_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
export function CustomFieldControl(props: ControlProps) {
  const fallback = <p className="text-sm text-fg-muted">{props.field.name}: field unavailable. Saved value is preserved.</p>;
  return <Slot id={FIELD_CONTROL_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}
