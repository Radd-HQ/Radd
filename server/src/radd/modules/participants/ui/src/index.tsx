import { definePlugin, SlotId, type Item, type Project } from "@radd/plugin-sdk";
import { ParticipantsSection } from "./ParticipantsSection";

export default definePlugin({
  contributions: [{
    id: "participants",
    slot: SlotId.issuePanelSection,
    order: 20,
    render: (props) => {
      const { item } = props as { item: Item; project: Project };
      return <ParticipantsSection item={item} />;
    },
  }],
});
