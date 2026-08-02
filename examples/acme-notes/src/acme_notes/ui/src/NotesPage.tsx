import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NotesSearch } from "./NotesSearch";
import { NotesStats } from "./NotesStats";
import {
  api,
  Button,
  Card,
  EmptyState,
  Select,
  Spinner,
  TextArea,
  tokens,
  useProjectsQuery,
} from "@radd/plugin-sdk";

interface Note {
  id: string;
  project_id: string;
  item_id: string | null;
  body: string;
}

const listKey = ["acme-notes", "all"] as const;

/**
 * The full Notes page — contributed to the `route.page` slot at /notes by the EXTERNAL acme-notes
 * plugin. A standalone CRUD page over the kernel-auto-generated /api/v1/notes API, built in the
 * plugin's own project and loaded at runtime.
 */
export function NotesPage() {
  const queryClient = useQueryClient();
  const projects = useProjectsQuery();
  const { data, isLoading } = useQuery({
    queryKey: listKey,
    queryFn: () => api.get<Note[]>("/notes"),
  });
  const [projectId, setProjectId] = useState("");
  const [body, setBody] = useState("");

  const refresh = () => void queryClient.invalidateQueries({ queryKey: listKey });
  const create = useMutation({
    mutationFn: () => api.post<Note>("/notes", { project_id: projectId, body: body.trim() }),
    onSuccess: () => setBody(""),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`/notes/${id}`),
    onSettled: refresh,
  });
  const projectKey = (id: string) => (projects.data ?? []).find((p) => p.id === id)?.key ?? "—";

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "1.5rem 1.25rem" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, color: tokens.heading, marginBottom: 4 }}>
        Notes
      </h1>
      <p style={{ color: tokens.textMuted, fontSize: 13, marginBottom: 20 }}>
        From the external <strong>acme-notes</strong> plugin — a federated page loaded at runtime.
      </p>

      {/* A widget fed by the plugin's own Python endpoint (server-side aggregate). */}
      <div style={{ marginBottom: 20 }}>
        <NotesStats />
      </div>

      {/* SLQ bar: filter issues (notes are searchable via the plugin's `note` SLQ field). */}
      <div style={{ marginBottom: 20 }}>
        <NotesSearch />
      </div>

      <Card title="New note">
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <div style={{ width: 200 }}>
            <Select label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">Choose…</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.key} — {p.name}
                </option>
              ))}
            </Select>
          </div>
          <div style={{ flex: 1 }}>
            <TextArea label="Note" value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <Button
            disabled={!projectId || !body.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            Add note
          </Button>
        </div>
      </Card>

      <div style={{ marginTop: 24 }} data-plugin-page="acme-notes">
        {isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 32 }}>
            <Spinner />
          </div>
        ) : (data ?? []).length === 0 ? (
          <EmptyState>No notes yet.</EmptyState>
        ) : (
          <ul style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(data ?? []).map((n) => (
              <li
                key={n.id}
                style={{
                  display: "flex",
                  gap: 12,
                  alignItems: "flex-start",
                  border: `1px solid ${tokens.border}`,
                  borderRadius: tokens.radiusLg,
                  padding: "10px 14px",
                }}
              >
                <span
                  style={{
                    fontFamily: "monospace",
                    fontSize: 11,
                    color: tokens.textMuted,
                    background: tokens.panel,
                    borderRadius: 4,
                    padding: "1px 6px",
                  }}
                >
                  {projectKey(n.project_id)}
                </span>
                <span style={{ flex: 1, color: tokens.text, fontSize: 14, whiteSpace: "pre-wrap" }}>
                  {n.body}
                </span>
                <Button variant="ghost" small onClick={() => remove.mutate(n.id)}>
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
