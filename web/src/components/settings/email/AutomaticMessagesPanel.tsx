import { ScopedSettingsEditor } from "../ScopedSettingsEditor";
import { SettingScope, type ScopedSetting } from "../../../lib/types";

/** The one `email`-section row this page renders SOMEWHERE ELSE — see below. */
const ACK_BODY_KEY = "mail_ack_body";

/**
 * The email section's switches (RADD-982): which messages the desk sends on its
 * own, as opposed to the relays it sends them through.
 *
 * It exists because of the trap RADD-1045 documented and this wave walked into.
 * `section="email"` is claimed by this page in `INSTANCE_HOMED_SECTIONS`, so
 * the instance General page SUBTRACTS it — and this page rendered exactly one
 * email row, the ack body, in its own bespoke card. A second `email` setting
 * was therefore editable nowhere at instance scope: registered, resolving,
 * documented, and with no form anywhere in the product.
 *
 * So the rows are rendered generically and the ack body is excluded by KEY,
 * because `AckTemplatePanel` owns it (a paragraph of prose with `{{token}}`
 * variables wants a textarea, not the generic single-line input). The
 * alternative — moving `mail_send_resolved` to another section — would have
 * put "does the desk tell customers their ticket is done" on the General page,
 * a screen away from every other thing about email.
 *
 * Project scope needs none of this: `email` is not in `PROJECT_HOMED_SECTIONS`,
 * so a project's own override already renders on its General settings page.
 */
export function AutomaticMessagesPanel() {
  return (
    <section>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-heading">Automatic messages</h3>
        <p className="text-[11px] text-fg-muted">
          What the desk sends without being asked. Each can be overridden per project.
        </p>
      </div>
      <ScopedSettingsEditor
        scope={SettingScope.instance}
        section="email"
        filter={(row: ScopedSetting) => row.key !== ACK_BODY_KEY}
        emptyLabel="No automatic messages are configurable — the email plugin is disabled."
      />
    </section>
  );
}
