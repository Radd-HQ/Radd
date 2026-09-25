import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { LeaveSection } from "./LeaveSection";

import { leaveDataSources } from "./data";

export default definePlugin({
  dataSources: leaveDataSources,
  contributions: [
    { id: "my-leave", slot: SlotId.profileSection, label: "My leave", render: () => <LeaveSection kind="leave" /> },
    { id: "team-holidays", slot: SlotId.settingsSection, match: "timelogging", label: "Team holidays", render: () => <LeaveSection kind="holiday" /> },
  ],
});
