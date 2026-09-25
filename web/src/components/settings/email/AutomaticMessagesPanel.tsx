import { Link } from "@tanstack/react-router";
import { RoutePath } from "../../../lib/constants";
import { IntegrationAutomations } from "../IntegrationAutomations";

/**
 * What the desk sends on its own (RADD-1318): only a person's public reply,
 * relayed to the requester. The receipt and the resolution notice were
 * switches here (`mail_ack_body`, `mail_send_resolved`) that defaulted ON —
 * mail nobody chose to send. Both are automation templates now; this panel
 * says so instead of offering switches that no longer exist.
 */
export function AutomaticMessagesPanel() {
  return (
    <section data-automatic-messages>
      <div className="mb-2">
        <h3 className="text-sm font-semibold text-heading">Automatic messages</h3>
      </div>
      <p className="text-[13px] text-fg-muted">
        Public replies are relayed to the issue's external email contacts. A receipt for new email
        tickets and a notice when an issue is resolved are automations you switch on: start from the “Acknowledge
        new email tickets” or “Tell the requester when resolved” template in{" "}
        <Link to={RoutePath.settingsAutomations} className="text-accent-text hover:underline">
          Automations
        </Link>
        .
      </p>
      <IntegrationAutomations group="Email" />
    </section>
  );
}
