import { Suspense, lazy } from "react";
import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { registerPageExtensions } from "./extension-registry";
import { PageRoute } from "./links";
import { searchSource } from "./lookups";
import { optionContributions } from "./options";
import { SidebarSpaces } from "./sidebar/SidebarSpaces";
import { Loading } from "./view/Loading";

const PagesSettingsPage = lazy(() =>
  import("./settings/SpacesSettingsPage").then((module) => ({ default: module.PagesSettingsPage })),
);

/** The wiki's bundled UI (RADD-1392). The host router mounts `./index-page`, `./space-page`, `./print-page`;
 *  this registers what other surfaces show: `radd:*` blocks, the sidebar section, settings, lookups. */
export default definePlugin({
  querySources: [searchSource],
  contributions: [
    ...optionContributions,
    {
      id: "settings", slot: SlotId.settingsPage, match: PageRoute.settings, toggleable: false,
      render: () => (
        <Suspense fallback={<Loading label="Loading page spaces…" />}>
          <PagesSettingsPage />
        </Suspense>
      ),
    },
    {
      id: "sidebar", slot: SlotId.sidebarSection, match: "pages", toggleable: false,
      render: (props) => <SidebarSpaces collapsed={props.collapsed === true} onToggle={props.onToggle as () => void} />,
    },
  ],
  activate: () => registerPageExtensions(),
});
