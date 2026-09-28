import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { LeaveSection } from "./LeaveSection";
import { TeamLeaveSection } from "./TeamLeaveSection";

import { leaveDataSources } from "./data";

export default definePlugin({
  dataSources: leaveDataSources,
  contributions: [
    { id: "my-leave", slot: SlotId.profileSection, label: "My leave", render: () => <LeaveSection kind="leave" /> },
    // RADD-1481: a steward's view of their team's absences; renders nothing for anyone else.
    { id: "team-leave", slot: SlotId.profileSection, label: "Team leave", render: () => <TeamLeaveSection /> },
    { id: "team-holidays", slot: SlotId.settingsSection, match: "timelogging", label: "Team holidays", render: () => <LeaveSection kind="holiday" /> },
  ],
});
