import { definePlugin, Slot, SlotId, usePermissions } from "@radd/plugin-sdk";
import { VCS_HOST_SETTINGS_SLOT, type VcsHostConfig } from "./host-contract";
import { historyEntities } from "./queries";
import { VcsHostSettings } from "./VcsHostSettings";
import { VcsSettingsPage } from "./SettingsPage";

function HostSettings({ config }: { config: VcsHostConfig }) {
  const perms = usePermissions();
  if (!perms.global("global.manage")) {
    return <p role="alert" className="text-sm text-fg-muted">You do not have permission to manage version control connections.</p>;
  }
  return (
    <>
      <VcsHostSettings config={config} />
      <Slot id={SlotId.settingsFooter} history={{ entities: historyEntities(config.provider) }} />
    </>
  );
}

export default definePlugin({ contributions: [
  { id: "settings", slot: SlotId.settingsPage, match: "/settings/vcs", render: () => <VcsSettingsPage /> },
  { id: "host-settings", slot: VCS_HOST_SETTINGS_SLOT, toggleable: false,
    render: (props) => <HostSettings config={props.config as VcsHostConfig} /> },
] });
