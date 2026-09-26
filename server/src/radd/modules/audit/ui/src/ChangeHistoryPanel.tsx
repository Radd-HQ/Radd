import { Link } from "@tanstack/react-router";
import { CollapsibleCard, Spinner, ChangeList, formatDateTime, relativeTime, useSlotMatch, SlotId } from "@radd/plugin-sdk";
import { useAudit, useAuditAccess } from "./queries";
const PANEL_LIMIT = 25;

export function ChangeHistoryPanel({
  entityType,
  entityId,
  projectId,
  title = "Change history",
}: {
  entityType: string;
  entityId: string;
  /** Required for a project-scoped entity when the viewer is not an instance admin. */
  projectId?: string;
  title?: string;
}) {
  const page = useSlotMatch(SlotId.settingsPage, "/settings/audit");
  const access = useAuditAccess(projectId);
  const allowed = access.data?.allowed === true;
  const history = useAudit({entityType, entityId, projectId, limit: PANEL_LIMIT}, "", allowed);
  if (!allowed) return null;
  const rows = history.isError ? [] : history.data ?? [];
  return (
    <CollapsibleCard title={title} count={rows.length}>
      {history.isPending ? (
        <span role="status" aria-label="Loading history"><Spinner /></span>
      ) : history.isError ? (
        <p className="text-xs text-fg-muted">History is unavailable right now.</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-fg-faint">No changes recorded yet.</p>
      ) : (
        <ol className="flex flex-col gap-3" data-change-history>
          {rows.map((entry) => (
            <li key={entry.id} className="text-xs">
              <p className="flex flex-wrap items-baseline gap-x-1.5">
                <span className="font-medium text-fg">{entry.actor?.name ?? "System"}</span>
                <span className="text-fg-muted">{entry.event_label.toLowerCase()}</span>
                <time className="text-fg-faint" dateTime={entry.at} title={formatDateTime(entry.at)}>
                  {relativeTime(entry.at)}
                </time>
              </p>
              {entry.changes && entry.changes.length > 0 && (
                <ChangeList entityType={entry.entity_type} changes={entry.changes} className="mt-0.5" />
              )}
            </li>
          ))}
          {page && rows.length === PANEL_LIMIT && (
            <li>
              <Link
                to={"/settings/audit"}
                search={{ entity: entityType, entity_id: entityId, project: projectId }}
                className="text-xs text-accent-text hover:text-accent-text-strong"
              >
                Older changes in the audit log
              </Link>
            </li>
          )}
        </ol>
      )}
    </CollapsibleCard>
  );
}
