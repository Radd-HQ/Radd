import { SlotId } from "@radd/plugin-sdk";
import { ContributedPage } from "./ContributedPage";

export function PluginPage() { return <ContributedPage slot={SlotId.routePage} />; }
