import { Inbox } from "lucide-react";
import { EmptyState, SettingsPage, usePermissions } from "@radd/plugin-sdk";
import { AutomaticMessagesPanel } from "./AutomaticMessagesPanel";
import { SendersPanel } from "./SendersPanel";
import { SignaturesPanel } from "./SignaturesPanel";
import { SourcesPanel } from "./SourcesPanel";

/** Settings → Email: sources (where mail arrives), senders (where it goes out) and each source's
 *  ordered routing chain. Send test and Preview make "is this working / why did it land there" answerable. */
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
