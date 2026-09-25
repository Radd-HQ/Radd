import { definePlugin } from "@radd/plugin-sdk";
import { CustomFieldsForm, CustomFieldControl } from "./CustomFieldsForm";
import { FIELD_CONTROL_SLOT, FIELDS_FORM_SLOT, type ControlProps, type CustomFieldsFormProps } from "./control-contract";
export default definePlugin({ contributions: [
  { id: "control", slot: FIELD_CONTROL_SLOT, toggleable: false, render: props => <CustomFieldControl {...(props as unknown as ControlProps)} /> },
  { id: "form", slot: FIELDS_FORM_SLOT, toggleable: false, render: props => <CustomFieldsForm {...(props as unknown as CustomFieldsFormProps)} /> },
] });
