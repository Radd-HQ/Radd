import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Send } from "lucide-react";
import { mailKindsQuery, mailSendersQuery } from "../../../lib/queries";
import type { MailSender } from "../../../lib/types";
import { Button } from "../../Button";
import { EmptyState } from "../../EmptyState";
import { QueryError } from "../../QueryError";
import { TableSkeleton } from "../../TableSkeleton";
import { SenderDialog } from "./SenderDialog";
import { TestDialog } from "./TestDialog";
import { Chip, connectionLine, kindLabel } from "./shared";

/**
 * Outgoing mail (RADD-958): the relays Radd sends replies, acknowledgements and
 * digests through. **Send test** reports the Message-ID the relay actually
 * used, so "is this working" is answerable without waiting for a customer to
 * complain.
 */
export function SendersPanel() {
  const senders = useQuery(mailSendersQuery());
  const kinds = useQuery(mailKindsQuery());
  const [editing, setEditing] = useState<MailSender | "new" | null>(null);
  const [testing, setTesting] = useState<MailSender | null>(null);

  if (senders.isError) return <QueryError label="mail senders" error={senders.error} />;

  const rows = senders.data ?? [];

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-heading">Outgoing</h3>
          <p className="text-[11px] text-fg-muted">
            The relay Radd sends replies, acknowledgements and digests through.
          </p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus size={14} aria-hidden />
          New sender
        </Button>
      </div>

      {senders.isPending ? (
        <TableSkeleton rows={2} />
      ) : rows.length === 0 ? (
        <EmptyState icon={Send} message="No sender — Radd cannot send mail." />
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((sender) => (
            <li key={sender.id} className="rounded-lg border border-subtle bg-surface px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] text-heading">{sender.name}</span>
                <Chip>{kindLabel(kinds.data?.senders, sender.kind)}</Chip>
                {sender.is_default && <Chip>default</Chip>}
                {!sender.enabled && <Chip tone="muted">disabled</Chip>}
                <span className="font-mono text-[11px] text-fg-secondary">
                  {sender.from_address}
                </span>
                <span className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setTesting(sender)}>
                    <Send size={12} aria-hidden />
                    Send test
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(sender)}>
                    Edit
                  </Button>
                </span>
              </div>
              <p className="mt-1 text-[11px] text-fg-faint">
                {connectionLine(
                  sender.resolved_username,
                  sender.resolved_host,
                  sender.resolved_port,
                )}
                {sender.resolved_starttls ? " · STARTTLS" : " · no TLS"}
                {!sender.has_secret && " · no password set"}
              </p>
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <SenderDialog
          sender={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      {testing && <TestDialog sender={testing} onClose={() => setTesting(null)} />}
    </section>
  );
}
