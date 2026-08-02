import { definePlugin, GlobalContributionToggles, SlotId, tokens, type Item } from "@radd/plugin-sdk";
import { NotesPage } from "./NotesPage";
import { NotesProfileSection } from "./NotesProfileSection";
import { NotesReviewView } from "./NotesReviewView";
import { NotesSection } from "./NotesSection";
import { NotesSettings } from "./NotesSettings";
import { NotesViewPanel } from "./NotesViewPanel";
import { RecentNotesWidget } from "./RecentNotesWidget";

/**
 * The acme-notes remote entry (spec 94 acceptance).
 *
 * EVERY place this plugin attaches to the UI is one row in the `contributions` array below — read
 * it top to bottom and you see the whole footprint. Each row is `{ slot, … }`:
 *   • `slot`   = WHERE it attaches (a `SlotId`; see docs/plugin-ui.md for every anchor + the host
 *                file that renders it).
 *   • `match`  = for page slots, the path/key it owns.
 *   • `title`  = the label for tab/menu slots (e.g. the Activity tab).
 *   • `render` = WHAT to show — a React component; this is browser code, so it lives here in the UI
 *                bundle, not in the Python manifest (which only declares the entity, the nav LINKS,
 *                and the `remote` URL pointing at this bundle).
 *
 * To attach somewhere new: add a row. To stop: delete it. Nothing else in Radd changes.
 */
export default definePlugin({
  contributions: [
    // Each row has a stable `id` (the per-contribution toggle key) + a `label` (shown in the
    // enable/disable UI: this plugin's settings page + Settings → Plugins).
    { slot: SlotId.routePage, id: "notes-page", match: "/notes", label: "Notes page", render: () => <NotesPage /> },
    { slot: SlotId.settingsPage, id: "settings-page", match: "/settings/acme-notes", label: "Settings page", render: () => <NotesSettings /> },
    { slot: SlotId.issuePanelSection, id: "rail-section", order: 40, label: "Issue rail section", render: ({ item }) => <NotesSection item={item as Item} /> },
    { slot: SlotId.issueRailBottom, id: "rail-bottom", label: "Issue rail (below fields)", render: ({ item }) => <RailNote item={item as Item} /> },
    { slot: SlotId.issueTab, id: "issue-tab", title: "Notes", label: "Issue Notes tab", render: ({ item }) => <NotesSection item={item as Item} /> },
    { slot: SlotId.issueTitleAction, id: "title-button", label: "Issue title button", render: ({ item }) => <TitleButton item={item as Item} /> },
    { slot: SlotId.viewHeader, id: "view-header", label: "View header summary", render: ({ items }) => <NotesViewPanel items={(items as Item[]) ?? []} /> },
    { slot: SlotId.viewType, id: "view-type", match: "acme.notes", label: "Notes-review view type", render: ({ items }) => <NotesReviewView items={(items as Item[]) ?? []} /> },
    { slot: SlotId.dashboardWidget, id: "recent-widget", match: "acme.recent-notes", label: "Recent-notes widget", render: () => <RecentNotesWidget /> },
    // --- the plugin's OWN control surfaces (opt-in, and `toggleable: false` so they don't list or
    //     hide THEMSELVES in the toggle lists) ---
    // Instance-wide availability, under this plugin's row in Settings → Plugins (admin). Off here is
    // off for everyone. `pluginId` is passed by the host through the slot props.
    {
      slot: SlotId.pluginManagerSection,
      id: "admin-toggles",
      match: "acme-notes",
      label: "Admin availability toggles",
      toggleable: false,
      render: ({ pluginId }) => (
        <GlobalContributionToggles plugin="acme-notes" pluginId={String(pluginId ?? "")} />
      ),
    },
    // Per-user control on the user's PROFILE page (only lists globally-enabled pieces).
    {
      slot: SlotId.profileSection,
      id: "profile-section",
      label: "Profile section",
      toggleable: false,
      render: () => <NotesProfileSection />,
    },
  ],
});

function RailNote({ item }: { item: Item }) {
  return (
    <div style={{ padding: "8px 16px", fontSize: 12, color: tokens.textFaint }}>
      acme-notes attached below the fields (issue {String(item.key ?? "")}).
    </div>
  );
}

function TitleButton({ item }: { item: Item }) {
  return (
    <a
      href="/notes"
      data-plugin-title-action="acme-notes"
      title={`Notes for ${String(item.key ?? "")}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        borderRadius: tokens.radius,
        border: `1px solid ${tokens.borderStrong}`,
        padding: "4px 8px",
        fontSize: 12,
        color: tokens.textMuted,
        textDecoration: "none",
      }}
    >
      Notes
    </a>
  );
}
