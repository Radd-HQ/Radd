import { tokens, type Item } from "@radd/plugin-sdk";

/**
 * Contributed to the `view.header` slot — a plugin attached to a VIEW. The host hands it the view's
 * currently-loaded, permission-scoped issues (`items`), so it can run its OWN logic over exactly
 * what the user can see. Here: a tiny computed summary (count · unassigned · busiest assignee). Any
 * calculation a plugin wants over the visible set goes here; heavier/server-authoritative logic
 * would instead call the plugin's own backend endpoint via the SDK `api` client.
 */
export function NotesViewPanel({ items }: { items: Item[] }) {
  const total = items.length;
  const unassigned = items.filter((i) => !(i as Record<string, unknown>).assignee).length;

  const counts = new Map<string, number>();
  for (const i of items) {
    const a = (i.assignee as { name?: string } | null | undefined)?.name;
    if (a) counts.set(a, (counts.get(a) ?? 0) + 1);
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];

  return (
    <span
      data-plugin-view-panel="acme-notes"
      title="Computed by the acme-notes plugin over the issues you can see in this view"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        borderRadius: tokens.radius,
        border: `1px solid ${tokens.border}`,
        background: tokens.panel,
        padding: "2px 8px",
        fontSize: 11,
        color: tokens.textMuted,
      }}
    >
      📝 {total} issues · {unassigned} unassigned
      {top ? ` · busiest: ${top[0]} (${top[1]})` : ""}
    </span>
  );
}
