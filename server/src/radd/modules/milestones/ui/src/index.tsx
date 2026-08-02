import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { MilestonesPage } from "./MilestonesPage";

/**
 * The `milestones` plugin's UI remote (spec 94). Registers a `route.page` matched at /milestones —
 * the host's catch-all route renders it there. The nav item (backend manifest) points at the same
 * path. Zero host code references milestones.
 */
export default definePlugin({
  activate(ctx) {
    ctx.registerSlot(SlotId.routePage, {
      id: "milestones-page",
      match: "/milestones",
      render: () => <MilestonesPage />,
    });
  },
});
