import { Inbox } from "lucide-react";
import { EmptyState, SettingsPage, usePermissions } from "@radd/plugin-sdk";
import { AutomaticMessagesPanel } from "./AutomaticMessagesPanel";
import { SendersPanel } from "./SendersPanel";
import { SignaturesPanel } from "./SignaturesPanel";
import { SourcesPanel } from "./SourcesPanel";

/**
 * Settings → Email (RADD-958; presets RADD-969; the mailintake plugin's own
 * page since RADD-1378, so disabling the plugin withdraws the page and its nav
 * entry together).
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
  const canManage = usePermissions().global("global.manage");

  return (
    <SettingsPage history={{ entities: ["mail_source", "mail_sender", "mail_rule"] }}
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
          empty instance and are then ignored — these rows are the truth. Email received, sent and
          failed are also automation triggers, for anything the switches below don't cover.
        </>
      }
    >
      {!canManage ? (
        <EmptyState icon={Inbox} message="You need instance-admin access to configure email." />
      ) : (
        <div className="flex flex-col gap-10" data-email-settings>
          <SourcesPanel />
          <SendersPanel />
          <SignaturesPanel />
          <AutomaticMessagesPanel />
        </div>
      )}
    </SettingsPage>
  );
}
