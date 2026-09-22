import { ScopedSettingsEditor } from "../ScopedSettingsEditor";
import { SettingScope, type ScopedSetting } from "../../../lib/types";

/** The one `email`-section row this panel owns; `AutomaticMessagesPanel` skips it. */
export const RAW_RETENTION_KEY = "mail_raw_retention_days";

/**
 * How long the desk keeps the ORIGINAL bytes of an inbound email (RADD-1048).
 *
 * Its own card rather than a row under "Automatic messages", which is where an
 * `email`-section setting lands by default: that heading answers "what does the
 * desk send without being asked", and this answers "what does it keep" — the
 * one question on this page a privacy review turns up to ask. A setting whose
 * heading misdescribes it is read wrong or not read at all, and this one
 * deletes customer mail.
 *
 * The exclusion is by KEY on the other panel, so the default for the next
 * `email` setting stays "visible under Automatic messages" rather than
 * "invisible" — the trap RADD-1045 documented and that panel's own comment
 * carries.
 */
export function RetentionPanel() {
  return (
    // `data-settings-card` is the proof hook: every row editor on this page
    // renders an identically-named Save button, so a proof that clicks "the
    // first one" silently exercises another panel's row.
    <section data-settings-card="retention">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-heading">Retention</h3>
        <p className="text-[11px] text-fg-muted">
          What the desk keeps, and when it deletes it. Lowering the window is retroactive: the
          next sweep reclaims messages that are already past it.
        </p>
      </div>
      <ScopedSettingsEditor
        scope={SettingScope.instance}
        section="email"
        filter={(row: ScopedSetting) => row.key === RAW_RETENTION_KEY}
        emptyLabel="Nothing is retained — the email plugin is disabled."
      />
    </section>
  );
}
