import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { MilestonesPage } from "./MilestonesPage";

export default definePlugin({
  contributions: [{ id: "milestones-page", slot: SlotId.routePage, match: "/milestones", render: () => <MilestonesPage /> }],
});
