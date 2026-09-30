import { definePlugin, SlotId, type AutomationNodeInspectorProps } from "@radd/plugin-sdk";
import { optionContributions } from "./options";
import { PERSON_IN_GROUP_NODE, PersonInGroupInspector } from "./PersonInGroupInspector";

/** groups: the directory-group option source, and the form of its "Person is in directory group" gate. */
export default definePlugin({
  contributions: [
    ...optionContributions,
    {
      id: "person-in-group-inspector",
      slot: SlotId.automationNodeInspector,
      match: PERSON_IN_GROUP_NODE,
      // The node's form, not a feature to switch off: without it the node is edited from its schema.
      toggleable: false,
      render: (props) => <PersonInGroupInspector {...(props as unknown as AutomationNodeInspectorProps)} />,
    },
  ],
});
