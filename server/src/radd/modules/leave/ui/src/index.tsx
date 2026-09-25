import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { LeaveSection } from "./LeaveSection";

export default definePlugin({
  contributions: [
    { id: "my-leave", slot: SlotId.profileSection, label: "My leave", render: () => <LeaveSection kind="leave" /> },
    { id: "team-holidays", slot: SlotId.settingsSection, match: "timelogging", label: "Team holidays", render: () => <LeaveSection kind="holiday" /> },
  ],
});
