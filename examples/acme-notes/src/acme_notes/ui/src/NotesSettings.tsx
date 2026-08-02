import { Card, tokens } from "@radd/plugin-sdk";

/**
 * A minimal Settings page for the acme-notes plugin — contributed to the `settings.page` slot at
 * /settings/acme-notes by this EXTERNAL plugin. It renders inside Radd's Settings chrome (the
 * secondary nav stays), proving a third-party plugin can add a settings page at runtime with zero
 * host code.
 */
export function NotesSettings() {
  return (
    <div style={{ maxWidth: 640 }} data-plugin-settings="acme-notes">
      <h1 style={{ fontSize: 18, fontWeight: 600, color: tokens.heading, marginBottom: 12 }}>
        Notes — settings
      </h1>
      <Card title="About">
        <p style={{ color: tokens.text, fontSize: 13, lineHeight: 1.5 }}>
          This settings page is served by the external <strong>acme-notes</strong> plugin as a
          federated <code>settings.page</code> remote. Radd's Settings shell renders it with zero
          plugin-specific host code — the plugin only registered a slot contribution.
        </p>
      </Card>

      <p style={{ marginTop: 12, fontSize: 12, color: tokens.textFaint }}>
        Tip: an admin sets which UI components are available <em>instance-wide</em> under Settings →
        Plugins → acme.notes; each user then turns the available ones on/off for themselves on their
        Profile page.
      </p>
    </div>
  );
}
