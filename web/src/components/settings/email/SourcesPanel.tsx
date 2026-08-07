import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Inbox, Plus } from "lucide-react";
import { mailKindsQuery, mailSourcesQuery } from "../../../lib/queries";
import { MailSourceKind, type MailSource } from "../../../lib/types";
import { Button } from "../../Button";
import { EmptyState } from "../../EmptyState";
import { QueryError } from "../../QueryError";
import { TableSkeleton } from "../../TableSkeleton";
import { RuleChainDialog } from "./RuleChainDialog";
import { SourceDialog } from "./SourceDialog";
import { Chip, connectionLine, kindLabel } from "./shared";

/**
 * Incoming mail (RADD-958): every mailbox Radd polls and every endpoint it
 * accepts pushes on, each with its own ordered routing chain.
 *
 * The connection line reads the RESOLVED host/port/username (RADD-969) — a
 * Gmail row stores none of them, so printing the raw columns would show
 * "— at —:0" for a source that is polling perfectly well.
 */
export function SourcesPanel() {
  const sources = useQuery(mailSourcesQuery());
  const kinds = useQuery(mailKindsQuery());
  const [editing, setEditing] = useState<MailSource | "new" | null>(null);
  const [rulesFor, setRulesFor] = useState<MailSource | null>(null);

  if (sources.isError) return <QueryError label="mail sources" error={sources.error} />;

  const rows = sources.data ?? [];

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-heading">Incoming</h3>
          <p className="text-[11px] text-fg-muted">
            Mailboxes Radd polls, and push endpoints it accepts.
          </p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus size={14} aria-hidden />
          Add source
        </Button>
      </div>

      {sources.isPending ? (
        <TableSkeleton rows={3} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Inbox}
          message="No mail sources — inbound email is off."
          action={
            <Button variant="ghost" onClick={() => setEditing("new")}>
              <Plus size={14} aria-hidden />
              Add the first source
            </Button>
          }
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((source) => (
            <li key={source.id} className="rounded-lg border border-subtle bg-surface px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] text-heading">{source.name}</span>
                <Chip>{kindLabel(kinds.data?.sources, source.kind)}</Chip>
                {!source.enabled && <Chip tone="muted">disabled</Chip>}
                {source.address && (
                  <span className="font-mono text-[11px] text-fg-secondary">{source.address}</span>
                )}
                <span className="ml-auto flex items-center gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setRulesFor(source)}>
                    Routing ({source.rule_count})
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(source)}>
                    Edit
                  </Button>
                </span>
              </div>
              <p className="mt-1 text-[11px] text-fg-faint">
                {source.kind === MailSourceKind.webhook
                  ? "HTTPS push — signed with this source's secret"
                  : `${connectionLine(
                      source.resolved_username,
                      source.resolved_host,
                      source.resolved_port,
                    )} · ${source.folder || "INBOX"}`}
                {!source.has_secret && " · no secret set"}
              </p>
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <SourceDialog
          source={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      {rulesFor && <RuleChainDialog source={rulesFor} onClose={() => setRulesFor(null)} />}
    </section>
  );
}
