import { definePlugin, SlotId, type ContributedPageProps, type Item, type Project } from "@radd/plugin-sdk";
import { CsatChip } from "./CsatChip";
import { SurveyPage } from "./SurveyPage";
import { SURVEY_PAGE } from "./survey";

/**
 * The `csat` plugin's UI remote entry (spec 94). The host loader imports this bundle and registers
 * its contributions under this plugin's name, so a disable removes exactly these:
 *   - the requester-satisfaction chip in the issue right-rail;
 *   - the PUBLIC rating page the survey email links to (RADD-1401), a `public.page` matched by
 *     pattern — the host draws the frame and names no survey. Not toggleable: it is where csat's
 *     own emails land, and a visitor has no toggles to read; disabling csat is how it goes.
 */
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
  ],
  activate(ctx) {
    ctx.registerSlot(SlotId.issuePanelSection, {
      id: "csat",
      order: 30,
      render: (props) => {
        const { item } = props as { item: Item; project: Project };
        return <CsatChip itemId={item.id} />;
      },
    });
  },
});
