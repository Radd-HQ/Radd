import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api } from "../../../lib/api";
import { ApiPath, apiMailSenderPath } from "../../../lib/constants";
import { mailKindsQuery, queryKeys } from "../../../lib/queries";
import { MailSenderKind, type MailSenderKindValue, type MailSender } from "../../../lib/types";
import { Button, ButtonVariant } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { ErrorText } from "../../ErrorText";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { CheckboxField, KindGuidance, findKind, kindLabel } from "./shared";

/**
 * Create or edit one outbound relay (RADD-958; presets RADD-969).
 *
 * Gmail and Outlook are SMTP with the host, port and TLS mode already known, so
 * those fields are hidden — see `SourceDialog` for why hiding beats
 * pre-filling. The kind is immutable after creation.
 */
export function SenderDialog({
  sender,
  onClose,
}: {
  sender: MailSender | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const kinds = useQuery(mailKindsQuery());
  const [confirmDialog, confirm] = useConfirm();
  const [form, setForm] = useState({
    name: sender?.name ?? "",
    kind: (sender?.kind ?? MailSenderKind.google) as MailSenderKindValue,
    enabled: sender?.enabled ?? true,
    is_default: sender?.is_default ?? true,
    from_address: sender?.from_address ?? "",
    reply_to: sender?.reply_to ?? "",
    host: sender?.host ?? "",
    port: sender?.port ?? 0,
    username: sender?.username ?? "",
    starttls: sender?.starttls ?? true,
    secret: "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const info = findKind(kinds.data?.senders, form.kind);
  const preset = info?.preset ?? false;
  // The catalog carries every kind's standard port, so no literal lives here.
  const port = form.port || info?.port || 0;
  // An untouched name takes the kind's — see `SourceDialog`.
  const name = form.name.trim() || info?.name || "";

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.mailSenders });
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        ...form,
        name,
        // Blank where the kind answers (RADD-969).
        host: preset ? "" : form.host,
        port: preset ? 0 : port,
      };
      if (!form.secret) delete body.secret;
      return sender
        ? api.patch(apiMailSenderPath(sender.id), body)
        : api.post(ApiPath.mailSenders, body);
    },
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete(apiMailSenderPath(sender!.id)),
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
  });

  return (
    <Modal title={sender ? `Edit ${sender.name}` : "New sender"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField
          label="Name"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder={info?.name ?? ""}
        />

        {sender ? (
          <p className="text-[11px] text-fg-muted">
            Kind: <strong>{kindLabel(kinds.data?.senders, sender.kind)}</strong> — fixed once the
            sender exists.
          </p>
        ) : (
          <SelectField
            label="Send through"
            value={form.kind}
            onChange={(e) => {
              const next = e.target.value as MailSenderKindValue;
              const picked = findKind(kinds.data?.senders, next);
              setForm((f) => ({
                ...f,
                kind: next,
                name: f.name.trim() || picked?.name || f.name,
              }));
            }}
          >
            {(kinds.data?.senders ?? []).map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.summary ? `${k.name} — ${k.summary}` : k.name}
              </option>
            ))}
          </SelectField>
        )}

        <KindGuidance info={info} />

        <TextField
          label="From address"
          value={form.from_address}
          onChange={(e) => set("from_address", e.target.value)}
          hint='The identity Radd sends as, e.g. "Radd <agent@example.com>". Mail arriving FROM this address is treated as a loop and dropped, so it should differ from the address you receive on.'
        />
        <TextField
          label="Reply-To"
          value={form.reply_to}
          onChange={(e) => set("reply_to", e.target.value)}
          hint="Where replies should go — normally your intake address. Blank uses the From address."
        />

        {!preset && (
          <div className="grid grid-cols-[1fr_120px] gap-3">
            <TextField
              label="Host"
              value={form.host}
              onChange={(e) => set("host", e.target.value)}
              placeholder="smtp.example.com"
            />
            <TextField
              label="Port"
              value={String(port)}
              onChange={(e) => set("port", Number(e.target.value) || 0)}
            />
          </div>
        )}

        <TextField
          label="Username"
          value={form.username}
          onChange={(e) => set("username", e.target.value)}
          placeholder={preset ? form.from_address || "the From address" : ""}
          hint={preset ? "Blank signs in as the From address." : undefined}
        />
        <TextField
          label={
            (preset ? "App password" : "Password") +
            (sender?.has_secret ? " (leave blank to keep)" : "")
          }
          type="password"
          value={form.secret}
          onChange={(e) => set("secret", e.target.value)}
        />

        {!preset && (
          <CheckboxField
            label="STARTTLS (port 587)"
            help="Turn off only for an implicit-TLS relay."
            checked={form.starttls}
            onChange={(v) => set("starttls", v)}
          />
        )}
        <CheckboxField
          label="Use this sender for outgoing mail"
          checked={form.is_default}
          onChange={(v) => set("is_default", v)}
        />
        <CheckboxField label="Enabled" checked={form.enabled} onChange={(v) => set("enabled", v)} />

        {(save.isError || remove.isError) && (
          <ErrorText error={save.isError ? save.error : remove.error} />
        )}
        <div className="flex justify-between gap-2">
          {sender ? (
            <Button
              variant={ButtonVariant.dangerGhost}
              onClick={() =>
                void confirm({
                  title: `Delete ${sender.name}`,
                  message: "Radd will stop sending mail unless another sender is enabled.",
                  confirmLabel: "Delete sender",
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
