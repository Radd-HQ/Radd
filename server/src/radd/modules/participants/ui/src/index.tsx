import { definePlugin, SlotId, type Item, type Project } from "@radd/plugin-sdk";
import { ParticipantsSection } from "./ParticipantsSection";

/**
 * The `participants` plugin's UI remote entry (spec 94). The host loader imports this bundle and
 * calls `activate(ctx)`; `ctx.registerSlot` is pre-bound to this plugin's name so a disable removes
 * exactly this contribution. Contributes the Participants card to the issue right-rail.
 */
export default definePlugin({
  activate(ctx) {
    ctx.registerSlot(SlotId.issuePanelSection, {
      id: "participants",
      order: 20,
      render: (props) => {
        const { item } = props as { item: Item; project: Project };
        return <ParticipantsSection item={item} />;
      },
    });
  },
});
