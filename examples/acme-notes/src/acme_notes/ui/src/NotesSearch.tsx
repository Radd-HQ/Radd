import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Card, EmptyState, Spinner, TextField, tokens, useItemsQuery, type Item } from "@radd/plugin-sdk";
import { substituteNote } from "./substitute";

interface Note {
  id: string;
  item_id: string | null;
  body: string;
}

/**
 * An SLQ bar that filters ISSUES and shows their notes — proving a plugin can drive the host's query
 * language. Because this plugin also registered a `note` SLQ field (see slq.py), you can search
 * `note ~ "rsync"` to find issues by note body; any builtin SLQ works too (`assignee = me AND
 * state = todo`). `useItemsQuery` runs the query permission-scoped on the server.
 */
export function NotesSearch() {
  const [slq, setSlq] = useState('note ~ "rsync"');
  const active = slq.trim().length > 0;
  const items = useItemsQuery(slq, { enabled: active });
  const notes = useQuery({ queryKey: ["acme-notes", "all"], queryFn: () => api.get<Note[]>("/notes") });

  // The API returns either { items } or a bare array — tolerate both.
  const raw = items.data as unknown;
  const matched: Item[] = Array.isArray(raw) ? (raw as Item[]) : ((raw as { items?: Item[] })?.items ?? []);

  const notesByItem = new Map<string, Note[]>();
  for (const n of notes.data ?? []) {
    if (!n.item_id) continue;
    notesByItem.set(n.item_id, [...(notesByItem.get(n.item_id) ?? []), n]);
  }

  return (
    <Card title="Find issues by SLQ — notes are searchable (try note ~ &quot;rsync&quot;)">
      <TextField
        label="SLQ"
        value={slq}
        placeholder={`note ~ "rsync"   ·   assignee = me AND state = todo`}
        onChange={(e) => setSlq(e.target.value)}
      />
      {items.isError && (
        <p style={{ marginTop: 8, fontSize: 12, color: tokens.danger }}>
          {items.error instanceof Error ? items.error.message : "Invalid query"}
        </p>
      )}
      {active && !items.isError && (
        <div style={{ marginTop: 10 }} data-plugin-notes-search>
          {items.isLoading ? (
            <Spinner />
          ) : matched.length === 0 ? (
            <EmptyState>No issues match.</EmptyState>
          ) : (
            <ul style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {matched.map((it) => {
                const itemNotes = notesByItem.get(it.id) ?? [];
                return (
                  <li
                    key={it.id}
                    style={{ border: `1px solid ${tokens.border}`, borderRadius: tokens.radiusLg, padding: "8px 12px" }}
                  >
                    <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                      <span style={{ fontFamily: "monospace", fontSize: 11, color: tokens.textMuted }}>
                        {String(it.key)}
                      </span>
                      <span style={{ fontSize: 13, color: tokens.text }}>{it.title}</span>
                    </div>
                    {itemNotes.map((n) => (
                      <p key={n.id} style={{ marginTop: 4, fontSize: 12, color: tokens.textMuted }}>
                        📝 {substituteNote(n.body, it)}
                      </p>
                    ))}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
