import { ScopedSettings } from "@radd/plugin-sdk";

/**
 * What the desk sends a requester on its own (RADD-1368): the receipt for a
 * new email ticket, its text, and the resolution notice. Settings this plugin
 * contributes to the `email` section and runs itself — all OFF until someone
 * switches them on here. A project can override either switch on its own
 * General page.
 *
 * Rendered by the host's cascade editor through the SDK (RADD-1377): the
 * receipt text is a `multiline` setting, so it gets a textarea without a
 * bespoke card. Public replies are relayed to the thread's contacts regardless
 * — that is the conversation, not a message the desk decides to send.
 */
export function AutomaticMessagesPanel() {
  return (
    <section data-automatic-messages>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-heading">Automatic messages</h3>
        <p className="text-[11px] text-fg-muted">
          What the desk sends without being asked. Public replies always reach the issue's
          external contacts; these are the messages beyond them. Each switch can be overridden per
          project.
        </p>
      </div>
      <ScopedSettings
        scope="instance"
        section="email"
        emptyLabel="No automatic messages are configurable — the email plugin is disabled."
      />
    </section>
  );
}
