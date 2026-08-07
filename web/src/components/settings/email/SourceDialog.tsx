import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api } from "../../../lib/api";
import { ApiPath, apiMailSourcePath } from "../../../lib/constants";
import { mailKindsQuery, projectsQuery, queryKeys } from "../../../lib/queries";
import { MailSourceKind, type MailSourceKindValue, type MailSource } from "../../../lib/types";
import { Button, ButtonVariant } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { ErrorText } from "../../ErrorText";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { CheckboxField, KindGuidance, findKind, kindLabel } from "./shared";

/**
 * Create or edit one mail source (RADD-958; presets RADD-969).
 *
 * The kind is immutable after creation — it decides which fields the row is
 * even allowed to leave blank — and for a preset kind (Gmail, Outlook) the
 * connection fields are HIDDEN rather than pre-filled. Pre-filling would put
 * `imap.gmail.com` in an editable box, the save would store it, and that stored
 * copy would then outlive the preset it came from. The row keeps nothing; the
 * server resolves it on every read.
 */
export function SourceDialog({
  source,
  onClose,
}: {
  source: MailSource | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const kinds = useQuery(mailKindsQuery());
  const projects = useQuery(projectsQuery());
  const [confirmDialog, confirm] = useConfirm();
  const [form, setForm] = useState({
    name: source?.name ?? "",
    kind: (source?.kind ?? MailSourceKind.google) as MailSourceKindValue,
    enabled: source?.enabled ?? true,
    address: source?.address ?? "",
    host: source?.host ?? "",
    port: source?.port ?? 0,
    username: source?.username ?? "",
    folder: source?.folder ?? "",
    default_project_id: source?.default_project_id ?? "",
    secret: "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const info = findKind(kinds.data?.sources, form.kind);
  const isWebhook = form.kind === MailSourceKind.webhook;
  const preset = info?.preset ?? false;
  const showConnection = !isWebhook && !preset;
  // The kind catalog carries the standard port for every kind, preset or not —
  // so this form holds no port literal of its own to drift from the server's.
  const port = form.port || info?.port || 0;
  // An untouched name takes the kind's — otherwise picking the default kind and
  // filling everything else leaves Save disabled with nothing saying why.
  const name = form.name.trim() || info?.name || "";

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.mailSources });
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        ...form,
        name,
        // Blank where the kind answers (RADD-969) — that is what lets an
        // upgraded preset upgrade rows that already exist.
        host: showConnection ? form.host : "",
        port: showConnection ? port : 0,
        default_project_id: form.default_project_id || null,
      };
      // Omitted = unchanged, so editing a port never re-types a password.
      if (!form.secret) delete body.secret;
      return source
        ? api.patch(apiMailSourcePath(source.id), body)
        : api.post(ApiPath.mailSources, body);
    },
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete(apiMailSourcePath(source!.id)),
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
  });

  return (
    <Modal title={source ? `Edit ${source.name}` : "New mail source"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField
          label="Name"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder={info?.name ?? ""}
        />

        {source ? (
          <p className="text-[11px] text-fg-muted">
            Kind: <strong>{kindLabel(kinds.data?.sources, source.kind)}</strong> — fixed once the
            source exists.
          </p>
        ) : (
          <SelectField
            label="Where mail comes from"
            value={form.kind}
            onChange={(e) => {
              const next = e.target.value as MailSourceKindValue;
              const picked = findKind(kinds.data?.sources, next);
              setForm((f) => ({
                ...f,
                kind: next,
                name: f.name.trim() || picked?.name || f.name,
              }));
            }}
          >
            {(kinds.data?.sources ?? []).map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.summary ? `${k.name} — ${k.summary}` : k.name}
              </option>
            ))}
          </SelectField>
        )}

        <KindGuidance info={info} />

        <TextField
          label="Address"
          value={form.address}
          onChange={(e) => set("address", e.target.value)}
          hint="The address mail arrives at. Used as Reply-To on outgoing mail, and to recognise Radd's own messages so a reply is never mistaken for a loop."
        />

        {showConnection && (
          <div className="grid grid-cols-[1fr_120px] gap-3">
            <TextField
              label="Host"
              value={form.host}
              onChange={(e) => set("host", e.target.value)}
              placeholder="imap.example.com"
            />
            <TextField
              label="Port"
              value={String(port)}
              onChange={(e) => set("port", Number(e.target.value) || 0)}
            />
          </div>
        )}

        {isWebhook ? (
          <p className="rounded-md border border-subtle bg-surface/60 px-3 py-2 text-[11px] text-fg-secondary">
            Push to <code className="font-mono">POST /api/v1/integrations/email</code> with the raw
            message and an <code className="font-mono">X-Radd-Signature</code> HMAC of the body,
            keyed with the secret below. An empty secret rejects everything.
          </p>
        ) : (
          <>
            <TextField
              label="Username"
              value={form.username}
              onChange={(e) => set("username", e.target.value)}
              placeholder={preset ? form.address || "the address above" : ""}
              hint={preset ? "Blank signs in as the address above." : undefined}
            />
            <TextField
              label="Folder"
              value={form.folder}
              onChange={(e) => set("folder", e.target.value)}
              placeholder="INBOX"
              hint="Blank polls the inbox."
            />
          </>
        )}

        <TextField
          label={
            (preset ? "App password" : "Password / secret") +
            (source?.has_secret ? " (leave blank to keep)" : "")
          }
          type="password"
          value={form.secret}
          onChange={(e) => set("secret", e.target.value)}
        />
        <SelectField
          label="Default project"
          value={form.default_project_id}
          onChange={(e) => set("default_project_id", e.target.value)}
          hint="Where a message lands when no routing rule matches. Without one, mail that matches nothing cannot open a ticket at all."
        >
          <option value="">— none —</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.key} · {p.name}
            </option>
          ))}
        </SelectField>
        <CheckboxField label="Enabled" checked={form.enabled} onChange={(v) => set("enabled", v)} />

        {(save.isError || remove.isError) && (
          <ErrorText error={save.isError ? save.error : remove.error} />
        )}
        <div className="flex justify-between gap-2">
          {source ? (
            <Button
              variant={ButtonVariant.dangerGhost}
              onClick={() =>
                void confirm({
                  title: `Delete ${source.name}`,
                  message:
                    "Mail will stop arriving here and this source's routing rules go with it. Tickets already created are untouched.",
                  confirmLabel: "Delete source",
                  danger: true,
                }).then((ok) => ok && remove.mutate())
              }
            >
              <Trash2 size={13} aria-hidden />
              Delete
            </Button>
          ) : (
            <span />
          )}
          <span className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => save.mutate()} disabled={save.isPending || !name}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </span>
        </div>
      </div>
      {confirmDialog}
    </Modal>
  );
}
