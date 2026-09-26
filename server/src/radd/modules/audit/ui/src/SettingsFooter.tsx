import { Link } from "@tanstack/react-router";
import { useSlotMatch, SlotId } from "@radd/plugin-sdk";
import { History } from "lucide-react";
import { useAuditAccess } from "./queries";
export function SettingsFooter({ history }: { history: {entities?: string[]; projectId?: string} }) {
  const page = useSlotMatch(SlotId.settingsPage, "/settings/audit");
  const access = useAuditAccess(history.projectId, Boolean(page));
  if (!page || !access.data?.allowed) return null;
  return <footer className="mt-8 border-t border-subtle/60 pt-4" data-settings-history>
    <Link to="/settings/audit" search={{entity: history.entities?.length ? history.entities.join(",") : undefined, project: history.projectId}}
      className="inline-flex items-center gap-1.5 text-[13px] text-accent-text hover:text-accent-text-strong">
      <History size={14} aria-hidden />Change history for this page
    </Link>
  </footer>;
}
