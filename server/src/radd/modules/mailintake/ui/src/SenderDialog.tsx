import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal, SelectField, TextField } from "@radd/plugin-sdk";
import { MailPath, mailKeys, mailKindsQuery } from "./api";
import { MailSenderKind, type MailSenderKindValue, type MailSender } from "./types";
import { CheckboxField, KindGuidance, RowDialogFooter, findKind, kindLabel, useRowEditor } from "./shared";

/** Create/edit an outbound relay; preset kinds hide host/port/TLS (see SourceDialog). */
export function SenderDialog({
  sender,
  onClose,
}: {
  sender: MailSender | null;
  onClose: () => void;
}) {
  const kinds = useQuery(mailKindsQuery());
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

  const { save, remove } = useRowEditor(mailKeys.senders, MailPath.senders, sender ? MailPath.sender(sender.id) : null, onClose);
  // Blank where the kind answers (RADD-969).
  const body = () => ({ ...form, name, host: preset ? "" : form.host, port: preset ? 0 : port });

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

        <RowDialogFooter
          save={save}
          remove={remove}
          confirmDelete={sender && {
            title: `Delete ${sender.name}`,
            message: "Radd will stop sending mail unless another sender is enabled.",
            confirmLabel: "Delete sender",
            danger: true,
          }}
          canSave={Boolean(name)}
          onSave={() => save.mutate(body())}
          onClose={onClose}
        />
      </div>
    </Modal>
  );
}
