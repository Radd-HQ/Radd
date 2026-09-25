import { definePlugin } from "@radd/plugin-sdk";
import { CycleSelect, CycleChoices } from "./CycleSelect";
import { CYCLE_SELECT_SLOT, CYCLE_CHOICES_SLOT, type CycleSelectProps, type CycleChoicesProps } from "./picker-contract";
export default definePlugin({ contributions: [
  { id: "select", slot: CYCLE_SELECT_SLOT, toggleable: false, render: props => <CycleSelect {...(props as unknown as CycleSelectProps)} /> },
  { id: "choices", slot: CYCLE_CHOICES_SLOT, toggleable: false, render: props => <CycleChoices {...(props as unknown as CycleChoicesProps)} /> },
] });
