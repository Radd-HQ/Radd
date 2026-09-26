import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, Button, errorMessage, ErrorText, Modal, SelectField, TextField } from "@radd/plugin-sdk";
import { connectionsQuery, jiraProjectsQuery, JiraPath } from "./api";
import type { JiraSnapshot, SnapshotStartInput } from "./types";

/** Start a download: which connection, which project, which JQL, and what else to cache. */
export function NewDownloadModal({
  onClose,
  onStarted,
}: {
  onClose: () => void;
  onStarted: () => void;
}) {
  const connections = useQuery(connectionsQuery());
  const [form, setForm] = useState<SnapshotStartInput>({
    name: "",
    jira_project_key: "",
    jql: "",
    connection_id: null,
    include_attachments: false,
    include_history: false,
  });
  const set = <K extends keyof SnapshotStartInput>(key: K, value: SnapshotStartInput[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const connectionId =
    form.connection_id ?? connections.data?.find((c) => c.is_default)?.id ?? null;
  const projects = useQuery(jiraProjectsQuery(connectionId));

  // A bad JQL answers 422 with Jira's reason; a good one, the match count — before any download.
  const testJql = useMutation({
    mutationFn: () =>
      api.post<{ total: number }>(JiraPath.preview, { jql: form.jql, connection_id: connectionId }),
  });

  const start = useMutation({
    mutationFn: () =>
      api.post<JiraSnapshot>(JiraPath.snapshots, { ...form, connection_id: connectionId }),
    onSuccess: () => {
      onStarted();
      onClose();
    },
  });

  const pickProject = (key: string) => {
    setForm((prev) => ({
      ...prev,
      jira_project_key: key,
      // Left un-ordered on purpose: the server appends `ORDER BY created ASC`
      // when the caller does not sort, because Jira pages by offset and an
      // unstable sort skips and repeats rows under a long download.
      jql: key ? `project = ${key}` : "",
    }));
  };

  return (
    <Modal title="Download a Jira project" onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        {(connections.data?.length ?? 0) > 1 && (
          <SelectField
            label="Connection"
            value={connectionId ?? ""}
            onChange={(e) => set("connection_id", e.target.value || null)}
          >
            {connections.data?.map((connection) => (
              <option key={connection.id} value={connection.id}>
                {connection.name}
              </option>
            ))}
          </SelectField>
        )}

        <SelectField
          label="Project"
          value={form.jira_project_key}
          onChange={(e) => pickProject(e.target.value)}
          hint={
            projects.isPending && connectionId
              ? "Loading projects…"
              : `${projects.data?.length ?? 0} projects visible to this connection`
          }
        >
          <option value="">Pick a project…</option>
          {projects.data?.map((project) => (
            <option key={project.key} value={project.key}>
              {project.key} — {project.name}
            </option>
          ))}
        </SelectField>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="jql" className="text-xs font-medium text-fg-secondary">
            JQL
          </label>
          <textarea
            id="jql"
            rows={3}
            value={form.jql}
            onChange={(e) => set("jql", e.target.value)}
            placeholder='project = DEV AND created >= "2025-01-01"'
            className="rounded-md border border-strong bg-surface px-2.5 py-2 font-mono text-[12px] text-heading outline-none focus-visible:outline-2 focus-visible:outline-focus"
          />
          <div className="flex items-center gap-2">
            <p className="flex-1 text-xs text-fg-faint">
              Narrow it to download less. Ordering is added automatically so paging stays stable.
            </p>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => testJql.mutate()}
              disabled={testJql.isPending || form.jql.trim() === ""}
            >
              {testJql.isPending ? "Testing…" : "Test JQL"}
            </Button>
          </div>
          {testJql.isSuccess && (
            <p className="text-xs text-status-success-ink">
              Valid — {testJql.data.total.toLocaleString()} issue
              {testJql.data.total === 1 ? "" : "s"} match.
            </p>
          )}
          {testJql.isError && (
            <p className="text-xs text-status-danger-ink">{errorMessage(testJql.error)}</p>
          )}
        </div>

        <TextField
          label="Name"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder={form.jira_project_key ? `${form.jira_project_key} · today` : "Optional"}
          hint="How this cached download is labelled."
        />

        <fieldset className="rounded-md border border-subtle p-2.5">
          <legend className="px-1 text-xs font-medium text-fg-secondary">Also download</legend>
          <label className="flex items-start gap-2 text-xs text-fg-secondary">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={form.include_attachments}
              onChange={(e) => set("include_attachments", e.target.checked)}
            />
            <span>
              Attachments
              <span className="block text-fg-faint">
                Files are usually the bulk of a project — this can take a while.
              </span>
            </span>
          </label>
          <label className="mt-2 flex items-start gap-2 text-xs text-fg-secondary">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={form.include_history}
              onChange={(e) => set("include_history", e.target.checked)}
            />
            <span>
              Change history
              <span className="block text-fg-faint">
                Gives imported issues a real activity trail and real cycle-time data, instead of
                every change appearing to have happened at import time.
              </span>
            </span>
          </label>
        </fieldset>

        {start.isError && <ErrorText error={start.error} />}

        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => start.mutate()}
            disabled={!form.jira_project_key || !form.jql.trim() || start.isPending}
          >
            {start.isPending ? "Starting…" : "Start download"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
