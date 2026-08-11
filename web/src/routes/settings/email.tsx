import { Inbox } from "lucide-react";
import { usePermissions } from "../../lib/hooks";
import { Permission } from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { AckTemplatePanel } from "../../components/settings/email/AckTemplatePanel";
import { SendersPanel } from "../../components/settings/email/SendersPanel";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { SourcesPanel } from "../../components/settings/email/SourcesPanel";

/**
 * Settings → Email (RADD-958; presets RADD-969).
 *
 * Mail was the last subsystem configured only by environment variables, which
 * meant changing a password was an operator with `sops` rather than an admin
 * with a form. Sources (where mail arrives), senders (where it goes out), and
 * each source's ordered ROUTING CHAIN live here as rows.
 *
 * Two affordances carry more weight than the forms:
 *
 *  - **Send test** reports the Message-ID the relay actually used, so "is this
 *    working" is answerable without waiting for a customer to complain.
 *  - **Preview** dry-runs the chain and names the rule that captured it. An
 *    ordered chain nobody can dry-run makes "why did this land there"
 *    unanswerable — the lesson Settings → Storage already paid for.
 */
export function EmailSettingsPage() {
  const canManage = usePermissions().global(Permission.globalManage);

  return (
    <SettingsPage
      title="Email"
      description="Where mail arrives, where it is sent from, and which project each message opens in."
      info={
        <>
          A <strong>source</strong> is a mailbox Radd reads (Gmail, Outlook or any IMAP server) or
          an endpoint it accepts pushes on. A <strong>sender</strong> is the relay it sends
          through. Pick Gmail or Outlook and the connection details are already known — you supply
          the address and an app password. Each source has an ordered{" "}
          <strong>routing chain</strong>: the first matching rule decides the project, and anything
          unmatched falls to the source's default. Environment variables seed the first rows on an
          empty instance and are then ignored — these rows are the truth.
        </>
      }
    >
      {!canManage ? (
        <EmptyState icon={Inbox} message="You need instance-admin access to configure email." />
      ) : (
        <div className="flex flex-col gap-10">
          <SourcesPanel />
          <SendersPanel />
          <AckTemplatePanel />
        </div>
      )}
    </SettingsPage>
  );
}
