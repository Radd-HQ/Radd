import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, Button, ErrorText, Modal, SelectField, TextField } from "@radd/plugin-sdk";
import { JiraPath } from "./api";
import {
  JIRA_AUTH_MODE_LABELS,
  JiraAuthMode,
  type JiraAuthModeValue,
  type JiraConnection,
  type JiraConnectionInput,
} from "./types";

const EMPTY: JiraConnectionInput = {
  name: "",
  base_url: "",
  auth_mode: JiraAuthMode.pat,
  username: "",
  credential: "",
  verify_ssl: true,
  is_default: false,
};

/** Create or edit one connection. The stored credential is never shown or round-tripped. */
export function ConnectionModal({
  connection,
  onClose,
  onSaved,
}: {
  connection: JiraConnection | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = connection !== null;
  const [form, setForm] = useState<JiraConnectionInput>(
    connection
      ? {
          name: connection.name,
          base_url: connection.base_url,
          auth_mode: connection.auth_mode,
          username: connection.username,
          credential: "", // never round-tripped; empty keeps the stored one
          verify_ssl: connection.verify_ssl,
          is_default: connection.is_default,
        }
      : EMPTY,
  );
  const set = <K extends keyof JiraConnectionInput>(key: K, value: JiraConnectionInput[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        base_url: form.base_url.trim(),
        auth_mode: form.auth_mode,
        username: form.auth_mode === JiraAuthMode.basic ? form.username.trim() : "",
        verify_ssl: form.verify_ssl,
        is_default: form.is_default,
      };
      // On edit, an untouched credential field must NOT blank the stored token.
      if (form.credential) body.credential = form.credential;
      return isEdit
        ? api.patch<JiraConnection>(`${JiraPath.connections}/${connection.id}`, body)
        : api.post<JiraConnection>(JiraPath.connections, { ...body, credential: form.credential });
    },
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  const isBasic = form.auth_mode === JiraAuthMode.basic;
  const missingCredential = !isEdit && !form.credential;
  const canSave =
    form.name.trim() !== "" &&
    form.base_url.trim() !== "" &&
    !missingCredential &&
    (!isBasic || form.username.trim() !== "");

  return (
    <Modal title={isEdit ? `Edit ${connection.name}` : "New Jira connection"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField
          label="Name"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="Production Jira"
          hint="How this instance is labelled in Radd."
        />
        <TextField
          label="Base URL"
          value={form.base_url}
          onChange={(e) => set("base_url", e.target.value)}
          placeholder="https://jira.example.com"
          hint="The site root — not the /rest path."
        />
        <SelectField
          label="Authentication"
          value={form.auth_mode}
          onChange={(e) => set("auth_mode", e.target.value as JiraAuthModeValue)}
        >
          <option value={JiraAuthMode.pat}>{JIRA_AUTH_MODE_LABELS[JiraAuthMode.pat]}</option>
          <option value={JiraAuthMode.basic}>{JIRA_AUTH_MODE_LABELS[JiraAuthMode.basic]}</option>
        </SelectField>
        {isBasic && (
          <TextField
            label="Username"
            value={form.username}
            onChange={(e) => set("username", e.target.value)}
            autoComplete="off"
          />
        )}
        <TextField
          label={isBasic ? "Password" : "Personal access token"}
          type="password"
          value={form.credential}
          onChange={(e) => set("credential", e.target.value)}
          autoComplete="new-password"
          placeholder={isEdit ? "Leave blank to keep the stored credential" : ""}
          hint={
            isEdit
              ? "Stored credentials are never shown. Type a new one only to replace it."
              : "Read access is enough — the importer only reads from Jira."
          }
        />
        <label className="flex items-center gap-2 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={form.verify_ssl}
            onChange={(e) => set("verify_ssl", e.target.checked)}
          />
          Verify the TLS certificate
          <span className="text-fg-faint">(turn off only for an internal CA)</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={form.is_default}
            onChange={(e) => set("is_default", e.target.checked)}
          />
          Use as the default connection
        </label>

        {save.isError && <ErrorText error={save.error} />}

        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={!canSave || save.isPending}>
            {save.isPending ? "Saving…" : isEdit ? "Save" : "Create connection"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
