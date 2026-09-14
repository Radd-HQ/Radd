import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { RoutePath } from "../../lib/constants";
import { formatDateTime, relativeTime } from "../../lib/dates";
import { usePermissions } from "../../lib/hooks";
import { auditQuery } from "../../lib/queries";
import { Permission } from "../../lib/types";
import { CollapsibleCard } from "../CollapsibleCard";
import { Spinner } from "../Spinner";
import { ChangeList } from "./ChangeLines";

const PANEL_LIMIT = 25;

/**
 * "Change history" on an entity editor (spec 123, RADD-1171): the audit rows
 * for ONE thing — a role, a field, a webhook, a storage host — read from the
 * same `GET /audit` the Audit log page uses, rendered with the same change
 * lines, collapsed behind its heading with the row count as the chip.
 *
 * Renders nothing for a viewer the server would refuse (no `global.manage`,
 * and no `project.manage` when the entity is project-scoped), so nobody is
 * shown a section whose every fetch is a 403.
 */
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
  const perms = usePermissions();
  const instanceWide = perms.global(Permission.globalManage);
  const allowed = instanceWide || (Boolean(projectId) && perms.anyProject(Permission.projectManage));
  const history = useQuery({
    ...auditQuery({
      entityType,
      entityId,
      projectId: instanceWide ? undefined : projectId,
      limit: PANEL_LIMIT,
    }),
    enabled: allowed,
  });
  if (!allowed) return null;
  const rows = history.data ?? [];
  return (
    <CollapsibleCard title={title} count={rows.length}>
      {history.isPending ? (
        <Spinner label="Loading history…" />
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
                <ChangeList changes={entry.changes} className="mt-0.5" />
              )}
            </li>
          ))}
          {rows.length === PANEL_LIMIT && (
            <li>
              <Link
                to={RoutePath.settingsAudit}
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
