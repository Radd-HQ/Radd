import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  Button,
  Card,
  EmptyState,
  Select,
  Spinner,
  TextArea,
  TextField,
  tokens,
  useProjectsQuery,
} from "@radd/plugin-sdk";

/**
 * The Milestones CRUD page (spec 94) — the north-star `milestones` plugin's real UI, shipped as a
 * federated `route.page` remote and mounted by the host at /milestones with zero host code. Talks
 * to the kernel-auto-generated CRUD API at /api/v1/milestones. Styled from SDK tokens/primitives —
 * no hardcoded color.
 */

interface Milestone {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  due_on: string | null;
  status: string;
}

const STATUSES = ["open", "in_progress", "closed"];
const listKey = ["radd-remote", "milestones"] as const;

export function MilestonesPage() {
  const queryClient = useQueryClient();
  const projects = useProjectsQuery();
  const { data, isLoading } = useQuery({
    queryKey: listKey,
    queryFn: () => api.get<Milestone[]>("/milestones"),
  });

  const [title, setTitle] = useState("");
  const [projectId, setProjectId] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = () => void queryClient.invalidateQueries({ queryKey: listKey });
  const onError = (e: unknown) => setError(e instanceof Error ? e.message : "Something went wrong");

  const create = useMutation({
    mutationFn: () =>
      api.post<Milestone>("/milestones", {
        project_id: projectId,
        title: title.trim(),
        description: description.trim() || null,
        due_on: dueOn || null,
        status: "open",
      }),
    onError,
    onSuccess: () => {
      setTitle("");
      setDueOn("");
      setDescription("");
      setError(null);
    },
    onSettled: refresh,
  });
  const patch = useMutation({
    mutationFn: (input: { id: string; body: Partial<Milestone> }) =>
      api.patch<Milestone>(`/milestones/${input.id}`, input.body),
    onError,
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`/milestones/${id}`),
    onError,
    onSettled: refresh,
  });

  const projectName = (id: string) =>
    (projects.data ?? []).find((p) => p.id === id)?.key ?? "—";
  const canSubmit = title.trim().length > 0 && projectId.length > 0 && !create.isPending;

  return (
    <div style={{ maxWidth: 820, margin: "0 auto", padding: "1.5rem 1.25rem" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, color: tokens.heading, marginBottom: 4 }}>
        Milestones
      </h1>
      <p style={{ color: tokens.textMuted, fontSize: 13, marginBottom: 20 }}>
        Project milestones — a federated plugin page loaded at runtime.
      </p>

      <Card title="New milestone">
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 12 }}>
          <TextField
            label="Title"
            value={title}
            placeholder="Ship v2"
            onChange={(e) => setTitle(e.target.value)}
          />
          <Select label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Choose…</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.key} — {p.name}
              </option>
            ))}
          </Select>
          <TextField
            label="Due"
            type="date"
            value={dueOn}
            onChange={(e) => setDueOn(e.target.value)}
          />
        </div>
        <div style={{ marginTop: 12 }}>
          <TextArea
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 12 }}>
          <Button disabled={!canSubmit} onClick={() => create.mutate()}>
            Add milestone
          </Button>
          {error && <span style={{ color: tokens.danger, fontSize: 12 }}>{error}</span>}
        </div>
      </Card>

      <div style={{ marginTop: 24 }} data-plugin-page="milestones">
        {isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 32 }}>
            <Spinner />
          </div>
        ) : (data ?? []).length === 0 ? (
          <EmptyState>No milestones yet.</EmptyState>
        ) : (
          <ul style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(data ?? []).map((m) => (
              <li
                key={m.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
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
                  {projectName(m.project_id)}
                </span>
                <span style={{ flex: 1, color: tokens.text, fontSize: 14 }}>{m.title}</span>
                {m.due_on && (
                  <span style={{ color: tokens.textFaint, fontSize: 12 }}>due {m.due_on}</span>
                )}
                <Select
                  value={m.status}
                  onChange={(e) => patch.mutate({ id: m.id, body: { status: e.target.value } })}
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </Select>
                <Button variant="ghost" small onClick={() => remove.mutate(m.id)}>
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
