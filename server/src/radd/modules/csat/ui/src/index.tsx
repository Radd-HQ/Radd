import { definePlugin, SlotId, type ContributedPageProps, type Item, type Project } from "@radd/plugin-sdk";
import { CsatChip } from "./CsatChip";
import { SurveyPage } from "./SurveyPage";
import { SURVEY_PAGE } from "./survey";

/** csat: the rail rating chip, and the public survey page the email links to (not toggleable —
 *  a visitor has no toggles; disabling csat is how it goes). */
export default definePlugin({
  contributions: [
    {
      id: "survey",
      slot: SlotId.publicPage,
      match: SURVEY_PAGE,
      label: "Public satisfaction survey page",
      toggleable: false,
      render: (props) => <SurveyPage token={(props as unknown as ContributedPageProps).params.token ?? ""} />,
    },
    {
      id: "csat",
      slot: SlotId.issuePanelSection,
      order: 30,
      render: (props) => <CsatChip itemId={(props as { item: Item; project: Project }).item.id} />,
    },
  ],
});
