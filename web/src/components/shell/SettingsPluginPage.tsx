import { SlotId } from "@radd/plugin-sdk";
import { ContributedPage } from "./ContributedPage";

export function SettingsPluginPage() { return <ContributedPage slot={SlotId.settingsPage} />; }
