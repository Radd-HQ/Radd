import { definePlugin, SlotId, type Item, type Project } from "@radd/plugin-sdk";
import { ApprovalsCard } from "./ApprovalsCard";

/**
 * The `approvals` plugin's UI remote entry (spec 94). The host loader imports this bundle and calls
 * `activate(ctx)`; `ctx.registerSlot` is pre-bound to this plugin's name so a disable removes
 * exactly this contribution. Contributes the workflow-approvals card to the issue right-rail.
 */
export default definePlugin({
  activate(ctx) {
    ctx.registerSlot(SlotId.issuePanelSection, {
      id: "approvals",
      order: 35,
      render: (props) => {
        const { item, project } = props as { item: Item; project: Project };
        return <ApprovalsCard item={item} project={project} />;
      },
    });
  },
});
