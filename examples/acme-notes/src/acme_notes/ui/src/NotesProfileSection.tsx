import { UserContributionToggles, tokens } from "@radd/plugin-sdk";

/**
 * Contributed to the `profile.section` slot (spec 94) — the plugin registers itself on the user's
 * Profile page for PER-USER control. `<UserContributionToggles>` lists only the components an admin
 * has left enabled instance-wide; each user turns their own On/Off (saved server-side, so they
 * follow the user across browsers). A globally-disabled component never appears here.
 */
export function NotesProfileSection() {
  return (
    <section className="mt-8 border-t border-zinc-800 pt-6" data-plugin-profile="acme-notes">
      <h2 style={{ fontSize: 13, fontWeight: 600, color: tokens.heading, marginBottom: 4 }}>
        Notes plugin
      </h2>
      <p style={{ fontSize: 12, color: tokens.textFaint, marginBottom: 10 }}>
        Turn this plugin's UI components on or off for your account.
      </p>
      <UserContributionToggles plugin="acme-notes" />
    </section>
  );
}
