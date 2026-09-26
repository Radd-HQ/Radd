import { ScopedSettings } from "@radd/plugin-sdk";

/** What the desk sends a requester unasked (receipt, resolution notice) — the plugin's own `email`
 *  settings, all OFF by default, overridable per project. Public replies go out regardless. */
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
