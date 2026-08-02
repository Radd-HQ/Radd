import { useState } from "react";
import { tokens, type Item } from "@radd/plugin-sdk";
import { NotesSection } from "./NotesSection";

/**
 * The "Notes review" saved-view TYPE (spec 94) — contributed to the `view.type` slot. The host hands
 * it the view's permission-scoped issues (`items`); it renders an issue list on the left and, for the
 * selected issue, the notes editor on the right. The view still carries the SLQ query (so the user
 * can scope it, e.g. `note ~ "rsync"`); this plugin just owns the presentation.
 */
export function NotesReviewView({ items }: { items: Item[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = items.find((i) => i.id === selectedId) ?? items[0] ?? null;

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }} data-plugin-view="acme.notes">
      <div style={{ width: 320, flexShrink: 0, borderRight: `1px solid ${tokens.border}`, overflowY: "auto" }}>
        {items.length === 0 ? (
          <p style={{ padding: 16, fontSize: 13, color: tokens.textFaint }}>No issues in this view.</p>
        ) : (
          items.map((it) => {
            const active = selected?.id === it.id;
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => setSelectedId(it.id)}
                style={{
                  display: "flex",
                  gap: 8,
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 12px",
                  border: "none",
                  borderBottom: `1px solid ${tokens.border}`,
                  cursor: "pointer",
                  background: active ? tokens.panelHover : "transparent",
                  color: active ? tokens.heading : tokens.text,
                }}
              >
                <span style={{ fontFamily: "monospace", fontSize: 11, color: tokens.textMuted }}>
                  {String(it.key)}
                </span>
                <span style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {it.title}
                </span>
              </button>
            );
          })
        )}
      </div>
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto" }}>
        {selected ? (
          <div style={{ padding: "8px 4px" }}>
            <h3 style={{ padding: "8px 16px", fontSize: 14, fontWeight: 600, color: tokens.heading }}>
              {String(selected.key)} — {selected.title}
            </h3>
            <NotesSection item={selected} />
          </div>
        ) : (
          <p style={{ padding: 24, fontSize: 13, color: tokens.textFaint }}>Select an issue to review its notes.</p>
        )}
      </div>
    </div>
  );
}
