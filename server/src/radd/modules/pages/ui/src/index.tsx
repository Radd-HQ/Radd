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

/**
 * The wiki's bundled UI (RADD-1392): pages is a core plugin, so this registers at boot.
 *
 * The routes (the spaces index, a space's tree and page, the print view) are the host router's —
 * it mounts this package's `./index-page`, `./space-page` and `./print-page` exports, lazily. What
 * registers here is what other surfaces show: the `radd:*` blocks (an issue description renders
 * them too), the sidebar's Pages section, the Page spaces settings page, and the page lookups and
 * option directory other plugins' controls read.
 */
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
