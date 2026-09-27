import { definePlugin, SlotId, type AutomationNodeInspectorProps, type Item, type Project } from "@radd/plugin-sdk";
import { ADD_PARTICIPANT_NODE, AddParticipantInspector } from "./AddParticipantInspector";
import { ParticipantsSection } from "./ParticipantsSection";

/** participants: the issue's Participants section, and the form of its Add participant automation action. */
export default definePlugin({
  contributions: [{
    id: "participants",
    slot: SlotId.issuePanelSection,
    order: 20,
    render: (props) => {
      const { item } = props as { item: Item; project: Project };
      return <ParticipantsSection item={item} />;
    },
  }, {
    id: "add-participant-inspector",
    slot: SlotId.automationNodeInspector,
    match: ADD_PARTICIPANT_NODE,
    // The node's form, not a feature to switch off: without it the node is edited from its schema.
    toggleable: false,
    render: (props) => <AddParticipantInspector {...(props as unknown as AutomationNodeInspectorProps)} />,
  }],
});
