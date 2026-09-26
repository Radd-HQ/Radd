import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Button, ErrorText } from "@radd/plugin-sdk";
import { MailPath, mailKeys } from "./api";
interface Rule { domain: string; include_subdomains: boolean; pattern: string; enabled: boolean }
interface Settings { rules: Rule[]; ai_enabled: boolean }
export function SignaturesPanel() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: mailKeys.signatures, queryFn: ({ signal }) => api.get<Settings>(MailPath.signatures, { signal }) });
  const [draft, setDraft] = useState<Settings | null>(null);
  const [sender, setSender] = useState("");
  const [body, setBody] = useState("");
  const value = draft ?? query.data;
  const save = useMutation({ mutationFn: () => api.put<Settings>(MailPath.signatures, value), onSuccess: data => { client.setQueryData(mailKeys.signatures, data); setDraft(null); } });
  const preview = useMutation({ mutationFn: () => api.post<{ body: string; signature: string | null; method: string }>(MailPath.signaturesPreview, { settings: value, sender, body }) });
  if (query.isError) return <ErrorText error={query.error} />;
  if (!value) return <p>Loading signature settings…</p>;
  const update = (i: number, patch: Partial<Rule>) => { setDraft({ ...value, rules: value.rules.map((rule, index) => index === i ? { ...rule, ...patch } : rule) }); preview.reset(); };
  const move = (i: number, delta: number) => { const rows = [...value.rules]; rows.splice(i + delta, 0, rows.splice(i, 1)[0]); setDraft({ ...value, rules: rows }); preview.reset(); };
  return <section className="space-y-3">
    <h2 className="text-sm font-semibold">Signature detection</h2>
    <p className="text-xs text-fg-muted">First matching domain rule wins, then built-in detection, then optional AI. The matching text and everything after it are hidden under “Show signature”. Original text is preserved. Applies to new incoming tickets and replies.</p>
    {value.rules.map((rule, i) => <fieldset key={i} className="flex flex-wrap items-end gap-2 rounded border border-subtle p-3 text-xs">
      <label>Sender domain<input aria-label={`Sender domain ${i+1}`} value={rule.domain} placeholder="acme.com" onChange={e => update(i, { domain: e.target.value })} className="block rounded border border-subtle bg-base p-2" /></label>
      <label className="flex-1">Signature-start regex<input aria-label={`Signature regex ${i+1}`} value={rule.pattern} placeholder="^Kind regards,\\s*$" onChange={e => update(i, { pattern: e.target.value })} className="block w-full rounded border border-subtle bg-base p-2 font-mono" /></label>
      <label><input type="checkbox" checked={rule.include_subdomains} onChange={e => update(i, { include_subdomains: e.target.checked })} /> Include subdomains</label>
      <label><input type="checkbox" checked={rule.enabled} onChange={e => update(i, { enabled: e.target.checked })} /> Enabled</label>
      <Button size="sm" disabled={!i} onClick={() => move(i, -1)}>Up</Button><Button size="sm" disabled={i===value.rules.length-1} onClick={() => move(i, 1)}>Down</Button>
      <Button size="sm" variant="ghost" onClick={() => setDraft({ ...value, rules: value.rules.filter((_, index) => index !== i) })}>Remove</Button>
    </fieldset>)}
    <div className="flex gap-2"><Button size="sm" disabled={value.rules.length >= 30} onClick={() => setDraft({ ...value, rules: [...value.rules, { domain: "", pattern: "", enabled: true, include_subdomains: false }] })}>Add signature rule</Button></div>
    <label className="block text-sm"><input type="checkbox" checked={value.ai_enabled} onChange={e => setDraft({ ...value, ai_enabled: e.target.checked })} /> AI email signature detection</label>
    <p className="text-xs text-fg-muted">Uses your configured AI chat provider when ordinary detection does not match. Email text is sent to that provider. Save to enable AI preview.</p>
    <div className="flex gap-2"><Button disabled={!draft || save.isPending} onClick={() => save.mutate()}>Save signature settings</Button>{draft && <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>}</div>
    {save.isError && <ErrorText error={save.error} />}
    <details><summary className="cursor-pointer text-sm">Test signature detection</summary><div className="mt-3 space-y-2">
      <input aria-label="Preview sender email" placeholder="sender@acme.com" value={sender} onChange={e => { setSender(e.target.value); preview.reset(); }} className="block rounded border border-subtle bg-base p-2 text-sm" />
      <textarea aria-label="Preview email body" placeholder="Paste an email to preview" value={body} onChange={e => { setBody(e.target.value); preview.reset(); }} rows={6} className="w-full rounded border border-subtle bg-base p-2 text-sm" />
      <Button disabled={!body || !sender || preview.isPending} onClick={() => preview.mutate()}>{preview.isPending ? "Testing…" : "Preview"}</Button>
      {preview.isError && <ErrorText error={preview.error} />}
      {preview.data && <div className="space-y-2 text-sm"><p>{preview.data.method}</p><pre className="whitespace-pre-wrap">{preview.data.body}</pre>{preview.data.signature && <div className="rounded border border-subtle p-3"><p className="text-xs font-medium">Detected signature</p><pre className="whitespace-pre-wrap">{preview.data.signature}</pre></div>}</div>}
    </div></details>
  </section>;
}
