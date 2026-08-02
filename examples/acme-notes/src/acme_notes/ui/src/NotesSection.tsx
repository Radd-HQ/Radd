import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Button, TextArea, tokens, type Item } from "@radd/plugin-sdk";
import { NOTE_TOKENS, substituteNote } from "./substitute";

/** A note attached to an issue (a subset of the acme_notes entity). */
interface Note {
  id: string;
  project_id: string;
  item_id: string | null;
  body: string;
}

const notesKey = (projectId: string) => ["acme-notes", "by-project", projectId] as const;

/**
 * The Notes card in the issue right-rail — contributed to the `issue.panel.section` slot by the
 * EXTERNAL acme-notes plugin. Proves a third-party plugin, built in its own project, can add an
 * issue-panel section at runtime with zero host code.
 */
export function NotesSection({ item }: { item: Item }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: notesKey(item.project_id),
    queryFn: () => api.get<Note[]>("/notes", { query: { project_id: item.project_id } }),
  });
  const [body, setBody] = useState("");
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: notesKey(item.project_id) });
  const add = useMutation({
    mutationFn: () =>
      api.post<Note>("/notes", { project_id: item.project_id, item_id: item.id, body: body.trim() }),
    onSuccess: () => setBody(""),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`/notes/${id}`),
    onSettled: refresh,
  });

  const notes = (data ?? []).filter((n) => n.item_id === item.id);

  return (
    <div style={{ padding: "12px 16px" }} data-plugin-section="acme-notes">
      <p style={{ marginBottom: 6, fontSize: 12, fontWeight: 500, color: tokens.textMuted }}>
        Notes
      </p>
      <ul style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}>
        {notes.map((n) => (
          <li
            key={n.id}
            style={{
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
              fontSize: 13,
              color: tokens.text,
              background: tokens.panel,
              border: `1px solid ${tokens.border}`,
              borderRadius: tokens.radius,
              padding: "6px 8px",
            }}
          >
            {/* Render with {{token}} substitution against THIS issue's fields — proof the plugin
                has (permission-scoped) access to the issue it's attached to. */}
            <span style={{ flex: 1, whiteSpace: "pre-wrap" }}>{substituteNote(n.body, item)}</span>
            <button
              type="button"
              onClick={() => remove.mutate(n.id)}
              aria-label="Delete note"
              style={{ background: "none", border: "none", color: tokens.textFaint, cursor: "pointer" }}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <TextArea
        value={body}
        placeholder="Add a note… try {{title}} or {{parent}}"
        onChange={(e) => setBody(e.target.value)}
        style={{ minHeight: "3rem" }}
      />
      <p style={{ marginTop: 4, fontSize: 11, color: tokens.textFaint }}>
        Tokens: {NOTE_TOKENS.map((t) => `{{${t}}}`).join(" ")} {"{{cf:<field>}}"}
      </p>
      {body.trim() && (
        <p style={{ marginTop: 2, fontSize: 11, color: tokens.textMuted }}>
          Preview: {substituteNote(body, item)}
        </p>
      )}
      <div style={{ marginTop: 6 }}>
        <Button small disabled={!body.trim() || add.isPending} onClick={() => add.mutate()}>
          Add note
        </Button>
      </div>
    </div>
  );
}
