import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Inbox, Plus, Send, Trash2, Wand2 } from "lucide-react";
import { api } from "../../lib/api";
import { usePermissions } from "../../lib/hooks";
import { projectsQuery } from "../../lib/queries";
import {
  MailRuleType,
  MailSourceKind,
  Permission,
  type MailRule,
  type MailRuleTypeValue,
  type MailSender,
  type MailSource,
  type MailTestResult,
  type Project,
  type RoutingPreviewResult,
} from "../../lib/types";
import { Button, ButtonVariant } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorText } from "../../components/ErrorText";
import { IconButton } from "../../components/IconButton";
import { Modal } from "../../components/Modal";
import { QueryError } from "../../components/QueryError";
import { SelectField } from "../../components/SelectField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { TokenMultiSelect } from "../../components/TokenMultiSelect";

const KEYS = {
  sources: ["mail", "sources"] as const,
  senders: ["mail", "senders"] as const,
  rules: (id: string) => ["mail", "rules", id] as const,
};

/**
 * Settings → Email (RADD-958).
 *
 * Mail was the last subsystem configured only by environment variables, which
 * meant changing a password was an operator with `sops` rather than an admin
 * with a form. Sources (where mail arrives), senders (where it goes out), and
 * each source's ordered ROUTING CHAIN live here as rows.
 *
 * Two affordances carry more weight than the forms:
 *
 *  - **Send test** reports the Message-ID the relay actually used, so "is this
 *    working" is answerable without waiting for a customer to complain.
 *  - **Preview** dry-runs the chain and names the rule that captured it. An
 *    ordered chain nobody can dry-run makes "why did this land there"
 *    unanswerable — the lesson Settings → Storage already paid for.
 */
export function EmailSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.globalManage);
  const sources = useQuery({
    queryKey: KEYS.sources,
    queryFn: () => api.get<MailSource[]>("/mail/sources"),
    enabled: canManage,
  });
  const senders = useQuery({
    queryKey: KEYS.senders,
    queryFn: () => api.get<MailSender[]>("/mail/senders"),
    enabled: canManage,
  });
  const projects = useQuery(projectsQuery());

  if (!canManage) {
    return (
      <SettingsPage title="Email" description="Instance mail configuration.">
        <EmptyState icon={Inbox} message="You need instance-admin access to configure email." />
      </SettingsPage>
    );
  }

  return (
    <SettingsPage
      title="Email"
      description="Where mail arrives, where it is sent from, and which project each message opens in."
      info={
        <>
          A <strong>source</strong> is a mailbox Radd reads (IMAP) or an endpoint it accepts
          pushes on. A <strong>sender</strong> is the relay it sends through. Each source has an
          ordered <strong>routing chain</strong>: the first matching rule decides the project,
          and anything unmatched falls to the source's default. Environment variables seed the
          first rows on an empty instance and are then ignored — these rows are the truth.
        </>
      }
    >
      {sources.isError ? (
        <QueryError label="mail sources" error={sources.error} />
      ) : sources.isPending || senders.isPending ? (
        <TableSkeleton rows={4} />
      ) : (
        <div className="flex flex-col gap-10">
          <SourcesSection
            sources={sources.data ?? []}
            projects={projects.data ?? []}
          />
          <SendersSection senders={senders.data ?? []} />
        </div>
      )}
    </SettingsPage>
  );
}

// --- sources -------------------------------------------------------------------

function SourcesSection({ sources, projects }: { sources: MailSource[]; projects: Project[] }) {
  const [editing, setEditing] = useState<MailSource | "new" | null>(null);
  const [rulesFor, setRulesFor] = useState<MailSource | null>(null);

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-heading">Incoming</h3>
          <p className="text-[11px] text-fg-muted">
            Mailboxes Radd polls, and push endpoints it accepts.
          </p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus size={14} aria-hidden />
          Add source
        </Button>
      </div>

      {sources.length === 0 ? (
        <EmptyState
          icon={Inbox}
          message="No mail sources — inbound email is off."
          action={
            <Button variant="ghost" onClick={() => setEditing("new")}>
              <Plus size={14} aria-hidden />
              Add the first source
            </Button>
          }
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {sources.map((source) => (
            <li
              key={source.id}
              className="rounded-lg border border-subtle bg-surface px-4 py-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] text-heading">{source.name}</span>
                <Chip>{source.kind}</Chip>
                {!source.enabled && <Chip tone="muted">disabled</Chip>}
                {source.address && (
                  <span className="font-mono text-[11px] text-fg-secondary">
                    {source.address}
                  </span>
                )}
                <span className="ml-auto flex items-center gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setRulesFor(source)}>
                    Routing ({source.rule_count})
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(source)}>
                    Edit
                  </Button>
                </span>
              </div>
              <p className="mt-1 text-[11px] text-fg-faint">
                {source.kind === MailSourceKind.imap
                  ? `${source.username || "—"} at ${source.host || "—"}:${source.port} · ${source.folder}`
                  : "HTTPS push — signed with this source's secret"}
                {!source.has_secret && " · no secret set"}
              </p>
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <SourceModal
          source={editing === "new" ? null : editing}
          projects={projects}
          onClose={() => setEditing(null)}
        />
      )}
      {rulesFor && <RulesModal source={rulesFor} projects={projects} onClose={() => setRulesFor(null)} />}
    </section>
  );
}

function SourceModal({
  source,
  projects,
  onClose,
}: {
  source: MailSource | null;
  projects: Project[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [form, setForm] = useState({
    name: source?.name ?? "",
    kind: source?.kind ?? MailSourceKind.imap,
    enabled: source?.enabled ?? true,
    address: source?.address ?? "",
    host: source?.host ?? "imap.migadu.com",
    port: source?.port ?? 993,
    username: source?.username ?? "",
    folder: source?.folder ?? "INBOX",
    default_project_id: source?.default_project_id ?? "",
    secret: "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const invalidate = () => queryClient.invalidateQueries({ queryKey: KEYS.sources });
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        ...form,
        default_project_id: form.default_project_id || null,
      };
      // Omitted = unchanged, so editing a port never re-types a password.
      if (!form.secret) delete body.secret;
      return source
        ? api.patch(`/mail/sources/${source.id}`, body)
        : api.post("/mail/sources", body);
    },
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/mail/sources/${source!.id}`),
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
  });

  return (
    <Modal title={source ? `Edit ${source.name}` : "New mail source"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField label="Name" value={form.name} onChange={(e) => set("name", e.target.value)} />
        <SelectField
          label="Kind"
          value={form.kind}
          onChange={(e) => set("kind", e.target.value as typeof form.kind)}
        >
          <option value={MailSourceKind.imap}>IMAP — Radd polls a mailbox</option>
          <option value={MailSourceKind.webhook}>Webhook — something pushes to Radd</option>
        </SelectField>
        <TextField
          label="Address"
          value={form.address}
          onChange={(e) => set("address", e.target.value)}
          hint="The address mail arrives at. Used as Reply-To on outgoing mail, and to recognise Radd's own messages so a reply is never mistaken for a loop."
        />

        {form.kind === MailSourceKind.imap ? (
          <>
            <div className="grid grid-cols-[1fr_120px] gap-3">
              <TextField label="Host" value={form.host} onChange={(e) => set("host", e.target.value)} />
              <TextField
                label="Port"
                value={String(form.port)}
                onChange={(e) => set("port", Number(e.target.value) || 993)}
              />
            </div>
            <TextField
              label="Username"
              value={form.username}
              onChange={(e) => set("username", e.target.value)}
            />
            <TextField
              label="Folder"
              value={form.folder}
              onChange={(e) => set("folder", e.target.value)}
            />
          </>
        ) : (
          <p className="rounded-md border border-subtle bg-surface/60 px-3 py-2 text-[11px] text-fg-secondary">
            Push to <code className="font-mono">POST /api/v1/integrations/email</code> with the raw
            message and an <code className="font-mono">X-Radd-Signature</code> HMAC of the body,
            keyed with the secret below. An empty secret rejects everything.
          </p>
        )}

        <TextField
          label={source?.has_secret ? "Password / secret (leave blank to keep)" : "Password / secret"}
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
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.key} · {p.name}
            </option>
          ))}
        </SelectField>
        <label className="flex items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set("enabled", e.target.checked)}
          />
          Enabled
        </label>

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
            <Button onClick={() => save.mutate()} disabled={save.isPending || !form.name.trim()}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </span>
        </div>
      </div>
      {confirmDialog}
    </Modal>
  );
}

// --- routing chain --------------------------------------------------------------

const RULE_LABELS: Record<MailRuleTypeValue, string> = {
  recipient: "Delivered to (alias)",
  sender: "From address or domain",
  subject: "Subject contains",
  llm: "AI — decide from the content",
};

function RulesModal({
  source,
  projects,
  onClose,
}: {
  source: MailSource;
  projects: Project[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const rules = useQuery({
    queryKey: KEYS.rules(source.id),
    queryFn: () => api.get<MailRule[]>(`/mail/sources/${source.id}/rules`),
  });
  const [editing, setEditing] = useState<MailRule | "new" | null>(null);
  const [preview, setPreview] = useState(false);

  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: KEYS.rules(source.id) }),
      queryClient.invalidateQueries({ queryKey: KEYS.sources }),
    ]);

  const reorder = useMutation({
    mutationFn: (ids: string[]) =>
      api.put(`/mail/sources/${source.id}/rules/order`, { rule_ids: ids }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/mail/rules/${id}`),
    onSuccess: invalidate,
  });

  const list = rules.data ?? [];
  const move = (index: number, delta: number) => {
    const next = [...list];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next.map((r) => r.id));
  };

  return (
    <Modal title={`Routing — ${source.name}`} onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        <p className="text-[11px] text-fg-muted">
          Checked top to bottom; the first match decides the project and stops the chain.
          Anything unmatched falls to this source's default. Keep the AI rule last — the rules
          above it cost nothing, and only mail none of them claimed pays for an inference.
        </p>

        {rules.isPending ? (
          <TableSkeleton rows={3} />
        ) : list.length === 0 ? (
          <EmptyState icon={Wand2} message="No rules — everything opens in the default project." />
        ) : (
          <ol className="flex flex-col gap-1">
            {list.map((rule, index) => (
              <li
                key={rule.id}
                className="flex items-center gap-2 rounded-md border border-subtle bg-surface/60 px-3 py-2"
              >
                <span className="w-5 shrink-0 text-center font-mono text-[11px] text-fg-faint">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-fg">{rule.name}</span>
                  <span className="block truncate text-[11px] text-fg-faint">
                    {RULE_LABELS[rule.rule_type]} →{" "}
                    {projects.find((p) => p.id === rule.project_id)?.key ?? "—"}
                  </span>
                </span>
                {!rule.enabled && <Chip tone="muted">off</Chip>}
                <IconButton onClick={() => move(index, -1)} aria-label="Move up" disabled={index === 0}>
                  <ArrowUp size={13} />
                </IconButton>
                <IconButton
                  onClick={() => move(index, 1)}
                  aria-label="Move down"
                  disabled={index === list.length - 1}
                >
                  <ArrowDown size={13} />
                </IconButton>
                <Button size="sm" variant="ghost" onClick={() => setEditing(rule)}>
                  Edit
                </Button>
                <IconButton danger onClick={() => remove.mutate(rule.id)} aria-label="Delete rule">
                  <Trash2 size={13} />
                </IconButton>
              </li>
            ))}
          </ol>
        )}

        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setEditing("new")}>
            <Plus size={13} aria-hidden />
            Add rule
          </Button>
          <Button variant="ghost" onClick={() => setPreview(true)}>
            <Wand2 size={13} aria-hidden />
            Test where a message lands
          </Button>
        </div>
      </div>

      {editing && (
        <RuleModal
          source={source}
          rule={editing === "new" ? null : editing}
          projects={projects}
          onClose={() => {
            setEditing(null);
            void invalidate();
          }}
        />
      )}
      {preview && <PreviewModal source={source} onClose={() => setPreview(false)} />}
    </Modal>
  );
}

function RuleModal({
  source,
  rule,
  projects,
  onClose,
}: {
  source: MailSource;
  rule: MailRule | null;
  projects: Project[];
  onClose: () => void;
}) {
  const [name, setName] = useState(rule?.name ?? "");
  const [type, setType] = useState<MailRuleTypeValue>(rule?.rule_type ?? MailRuleType.recipient);
  const [projectId, setProjectId] = useState(rule?.project_id ?? "");
  const [values, setValues] = useState<string[]>(() => {
    const c = (rule?.config ?? {}) as Record<string, string[]>;
    return c.addresses ?? c.patterns ?? c.contains ?? [];
  });
  const [prompt, setPrompt] = useState(
    (rule?.config as { prompt?: string } | undefined)?.prompt ??
      "Classify this support email into one of the given categories.",
  );
  const [answers, setAnswers] = useState<{ answer: string; project_id: string }[]>(
    ((rule?.config as { answers?: { answer: string; project_id: string }[] } | undefined)
      ?.answers ?? []),
  );

  const configFor = (): Record<string, unknown> => {
    if (type === MailRuleType.recipient) return { addresses: values };
    if (type === MailRuleType.sender) return { patterns: values };
    if (type === MailRuleType.subject) return { contains: values };
    return { prompt, answers: answers.filter((a) => a.answer && a.project_id) };
  };

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        rule_type: type,
        enabled: rule?.enabled ?? true,
        config: configFor(),
        project_id: type === MailRuleType.llm ? null : projectId || null,
      };
      return rule
        ? api.patch(`/mail/rules/${rule.id}`, body)
        : api.post(`/mail/sources/${source.id}/rules`, body);
    },
    onSuccess: onClose,
  });

  return (
    <Modal title={rule ? `Edit ${rule.name}` : "New routing rule"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <SelectField
          label="Match on"
          value={type}
          onChange={(e) => setType(e.target.value as MailRuleTypeValue)}
        >
          {Object.entries(RULE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>

        {type === MailRuleType.llm ? (
          <>
            <TextField
              label="Prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              hint="The model picks from the categories below and can never invent a project. If AI is off or slow, the chain simply continues to the next rule."
            />
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-fg-secondary">Categories → project</span>
              {answers.map((a, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    value={a.answer}
                    onChange={(e) =>
                      setAnswers((prev) =>
                        prev.map((x, j) => (j === i ? { ...x, answer: e.target.value } : x)),
                      )
                    }
                    placeholder="build failure"
                    className="h-8 flex-1 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-focus"
                  />
                  <select
                    value={a.project_id}
                    onChange={(e) =>
                      setAnswers((prev) =>
                        prev.map((x, j) => (j === i ? { ...x, project_id: e.target.value } : x)),
                      )
                    }
                    className="h-8 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading"
                  >
                    <option value="">— project —</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.key}
                      </option>
                    ))}
                  </select>
                  <IconButton
                    danger
                    aria-label="Remove category"
                    onClick={() => setAnswers((prev) => prev.filter((_, j) => j !== i))}
                  >
                    <Trash2 size={13} />
                  </IconButton>
                </div>
              ))}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setAnswers((p) => [...p, { answer: "", project_id: "" }])}
              >
                <Plus size={12} aria-hidden />
                Add category
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-fg-secondary">
                {type === MailRuleType.recipient
                  ? "Addresses (aliases)"
                  : type === MailRuleType.sender
                    ? "Addresses or @domains"
                    : "Subject contains"}
              </span>
              <TokenMultiSelect
                value={values}
                onChange={setValues}
                options={[]}
                allowCreate
                placeholder={
                  type === MailRuleType.recipient
                    ? "pipeline@radd-hq.com — type and press Enter"
                    : type === MailRuleType.sender
                      ? "@vip-customer.com — type and press Enter"
                      : "[URGENT] — type and press Enter"
                }
                ariaLabel="Rule values"
              />
            </div>
            <SelectField
              label="Opens in project"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">— none —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.key} · {p.name}
                </option>
              ))}
            </SelectField>
          </>
        )}

        {save.isError && <ErrorText error={save.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !name.trim()}>
            {save.isPending ? "Saving…" : "Save rule"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function PreviewModal({ source, onClose }: { source: MailSource; onClose: () => void }) {
  const [form, setForm] = useState({
    recipient: source.address,
    sender: "",
    subject: "",
    body: "",
  });
  const run = useMutation({
    mutationFn: () => api.post<RoutingPreviewResult>(`/mail/sources/${source.id}/preview`, form),
  });

  return (
    <Modal title="Where would this land?" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-[11px] text-fg-muted">
          Runs the chain against a made-up message. Nothing is sent and no ticket is created.
        </p>
        <TextField
          label="Delivered to"
          value={form.recipient}
          onChange={(e) => setForm((f) => ({ ...f, recipient: e.target.value }))}
        />
        <TextField
          label="From"
          value={form.sender}
          onChange={(e) => setForm((f) => ({ ...f, sender: e.target.value }))}
        />
        <TextField
          label="Subject"
          value={form.subject}
          onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))}
        />
        <TextField
          label="Body"
          value={form.body}
          onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
        />
        {run.data && (
          <div className="rounded-md border border-subtle bg-surface/60 px-3 py-2 text-[13px]">
            <span className="text-fg">
              Opens in <strong>{run.data.project_key || "nowhere — no default set"}</strong>
            </span>
            <span className="mt-0.5 block text-[11px] text-fg-faint">{run.data.reason}</span>
          </div>
        )}
        {run.isError && <ErrorText error={run.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? "Checking…" : "Check"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// --- senders --------------------------------------------------------------------

function SendersSection({ senders }: { senders: MailSender[] }) {
  const [editing, setEditing] = useState<MailSender | "new" | null>(null);
  const [testing, setTesting] = useState<MailSender | null>(null);

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-heading">Outgoing</h3>
          <p className="text-[11px] text-fg-muted">
            The relay Radd sends replies, acknowledgements and digests through.
          </p>
        </div>
        <Button onClick={() => setEditing("new")}>
          <Plus size={14} aria-hidden />
          Add sender
        </Button>
      </div>

      {senders.length === 0 ? (
        <EmptyState icon={Send} message="No sender — Radd cannot send mail." />
      ) : (
        <ul className="flex flex-col gap-2">
          {senders.map((sender) => (
            <li key={sender.id} className="rounded-lg border border-subtle bg-surface px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] text-heading">{sender.name}</span>
                {sender.is_default && <Chip>default</Chip>}
                {!sender.enabled && <Chip tone="muted">disabled</Chip>}
                <span className="font-mono text-[11px] text-fg-secondary">
                  {sender.from_address}
                </span>
                <span className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setTesting(sender)}>
                    <Send size={12} aria-hidden />
                    Send test
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(sender)}>
                    Edit
                  </Button>
                </span>
              </div>
              <p className="mt-1 text-[11px] text-fg-faint">
                {sender.username || "—"} at {sender.host || "—"}:{sender.port}
                {sender.starttls ? " · STARTTLS" : " · no TLS"}
                {!sender.has_secret && " · no password set"}
              </p>
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <SenderModal
          sender={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      {testing && <TestModal sender={testing} onClose={() => setTesting(null)} />}
    </section>
  );
}

function SenderModal({ sender, onClose }: { sender: MailSender | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [form, setForm] = useState({
    name: sender?.name ?? "",
    kind: "smtp" as const,
    enabled: sender?.enabled ?? true,
    is_default: sender?.is_default ?? true,
    from_address: sender?.from_address ?? "",
    reply_to: sender?.reply_to ?? "",
    host: sender?.host ?? "smtp.migadu.com",
    port: sender?.port ?? 587,
    username: sender?.username ?? "",
    starttls: sender?.starttls ?? true,
    secret: "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const invalidate = () => queryClient.invalidateQueries({ queryKey: KEYS.senders });
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { ...form };
      if (!form.secret) delete body.secret;
      return sender
        ? api.patch(`/mail/senders/${sender.id}`, body)
        : api.post("/mail/senders", body);
    },
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/mail/senders/${sender!.id}`),
    onSuccess: async () => {
      await invalidate();
      onClose();
    },
  });

  return (
    <Modal title={sender ? `Edit ${sender.name}` : "New sender"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField label="Name" value={form.name} onChange={(e) => set("name", e.target.value)} />
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
        <div className="grid grid-cols-[1fr_120px] gap-3">
          <TextField label="Host" value={form.host} onChange={(e) => set("host", e.target.value)} />
          <TextField
            label="Port"
            value={String(form.port)}
            onChange={(e) => set("port", Number(e.target.value) || 587)}
          />
        </div>
        <TextField
          label="Username"
          value={form.username}
          onChange={(e) => set("username", e.target.value)}
        />
        <TextField
          label={sender?.has_secret ? "Password (leave blank to keep)" : "Password"}
          type="password"
          value={form.secret}
          onChange={(e) => set("secret", e.target.value)}
        />
        <label className="flex items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={form.starttls}
            onChange={(e) => set("starttls", e.target.checked)}
          />
          STARTTLS (port 587). Turn off only for an implicit-TLS relay.
        </label>
        <label className="flex items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={form.is_default}
            onChange={(e) => set("is_default", e.target.checked)}
          />
          Use this sender for outgoing mail
        </label>
        <label className="flex items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set("enabled", e.target.checked)}
          />
          Enabled
        </label>

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
            <Button onClick={() => save.mutate()} disabled={save.isPending || !form.name.trim()}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </span>
        </div>
      </div>
      {confirmDialog}
    </Modal>
  );
}

function TestModal({ sender, onClose }: { sender: MailSender; onClose: () => void }) {
  const [to, setTo] = useState("");
  const send = useMutation({
    mutationFn: () => api.post<MailTestResult>(`/mail/senders/${sender.id}/test`, { to_address: to }),
  });

  return (
    <Modal title={`Send a test through ${sender.name}`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField
          label="Send to"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="you@example.com"
        />
        {send.data?.ok && (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-[13px] text-fg">
            Sent. The relay used Message-ID{" "}
            <code className="font-mono text-[11px]">{send.data.message_id}</code> — that is the
            value replies thread against.
          </div>
        )}
        {send.data && !send.data.ok && (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-[12px] text-fg">
            {send.data.error}
          </div>
        )}
        {send.isError && <ErrorText error={send.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => send.mutate()} disabled={send.isPending || !to.includes("@")}>
            {send.isPending ? "Sending…" : "Send test"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function Chip({ children, tone }: { children: React.ReactNode; tone?: "muted" }) {
  return (
    <span
      className={
        "rounded px-1.5 py-px text-[10px] uppercase tracking-wide " +
        (tone === "muted" ? "bg-elevated text-fg-faint" : "bg-elevated text-fg-secondary")
      }
    >
      {children}
    </span>
  );
}
