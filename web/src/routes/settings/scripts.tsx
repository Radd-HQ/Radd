/**
 * Settings → Scripts (RADD-1269): the managed interpreter, its packages, and
 * the script library — one page, three sections, because the three are one
 * thing: what runs when an automation says "run a script".
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Package, Play, Plus, RotateCcw, Terminal, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import {
  scriptInterpreterQuery,
  scriptKeys,
  scriptPackagesQuery,
  scriptQuery,
  scriptVersionsQuery,
  scriptsQuery,
} from "../../lib/queries";
import type { Script, ScriptInterpreter, ScriptPackage, ScriptRunOutcome } from "../../lib/types";
import { Button, ButtonVariant } from "../../components/Button";
import { Callout, CalloutKind } from "../../components/Callout";
import { useConfirm } from "../../components/ConfirmDialog";
import { SelectField } from "../../components/SelectField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TextField } from "../../components/TextField";
import { PythonEditor } from "../../components/scripts/PythonEditor";

export function ScriptsSettingsPage() {
  return (
    <SettingsPage
      history={{ entities: ["script", "script_package", "script_interpreter"] }}
      title="Scripts"
      description="Python that automations can run. Scripts execute in a managed interpreter of their own, out of process, with the Radd SDK client and the packages you install here — acting as the automation's identity, never beyond it."
    >
      <div className="flex flex-col gap-6">
        <InterpreterSection />
        <PackagesSection />
        <LibrarySection />
      </div>
    </SettingsPage>
  );
}

// --- the interpreter ---------------------------------------------------------

const STATUS_TONE: Record<ScriptInterpreter["status"], string> = {
  ready: "bg-emerald-500/15 text-emerald-300",
  missing: "bg-elevated text-fg-secondary",
  failed: "bg-status-danger/15 text-status-danger",
};

function InterpreterSection() {
  const queryClient = useQueryClient();
  const interpreter = useQuery(scriptInterpreterQuery);
  const [version, setVersion] = useState("");
  const [showLog, setShowLog] = useState(false);
  const rebuild = useMutation({
    mutationFn: (python_version: string) =>
      api.post<ScriptInterpreter>(`${ApiPath.scripts}/interpreter/rebuild`, { python_version }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: scriptKeys.interpreter });
      await queryClient.invalidateQueries({ queryKey: scriptKeys.packages });
    },
  });
  const data = interpreter.data;
  const chosen = version || data?.python_version || "3.12";
  const choices = [...new Set([...(data?.available ?? []), "3.12", "3.13", chosen])].sort();

  return (
    <section data-scripts-interpreter className="flex flex-col gap-3 rounded-[10px] border border-subtle bg-surface p-4">
      <div className="flex items-center gap-2">
        <Terminal size={15} className="text-accent-text" aria-hidden />
        <h2 className="text-sm font-medium text-heading">Interpreter</h2>
        {data && (
          <span data-interpreter-status={data.status} className={`rounded px-1.5 py-px text-[10px] uppercase tracking-wide ${STATUS_TONE[data.status]}`}>
            {data.status}
          </span>
        )}
        {data?.resolved && <span className="text-[11px] text-fg-muted">Python {data.resolved}</span>}
        {data?.built_at && <span className="text-[11px] text-fg-faint">built {relativeTime(data.built_at)}</span>}
      </div>
      <p className="text-xs text-fg-secondary">
        A virtual environment built by uv under <code className="text-fg">{data?.path ?? "…"}</code>, with the
        Radd SDK client (<code className="text-fg">{data?.sdk_source || "radd-sdk"}</code>) installed. Rebuilding
        recreates it for the chosen Python and reinstalls every package below.
      </p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          rebuild.mutate(chosen);
        }}
      >
        <SelectField label="Python" value={chosen} onChange={(event) => setVersion(event.target.value)}>
          {choices.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </SelectField>
        <Button type="submit" disabled={rebuild.isPending}>
          <RotateCcw size={13} aria-hidden />
          {rebuild.isPending ? "Building…" : data?.status === "ready" ? "Rebuild" : "Build"}
        </Button>
        {(data?.log || rebuild.data?.log) && (
          <Button type="button" variant={ButtonVariant.ghost} size="sm" onClick={() => setShowLog((v) => !v)}>
            {showLog ? "Hide log" : "Show log"}
          </Button>
        )}
      </form>
      {rebuild.isError && <p className="text-xs text-status-danger">{errorMessage(rebuild.error)}</p>}
      {data?.status === "missing" && (
        <Callout kind={CalloutKind.info}>Nothing runs until the interpreter is built.</Callout>
      )}
      {showLog && (
        <pre className="max-h-64 overflow-auto rounded-[8px] border border-subtle bg-base p-2 text-[11px] text-fg-secondary">
          {rebuild.data?.log || data?.log}
        </pre>
      )}
    </section>
  );
}

// --- packages -----------------------------------------------------------------

const PACKAGE_TONE: Record<ScriptPackage["status"], string> = {
  installed: "bg-emerald-500/15 text-emerald-300",
  pending: "bg-elevated text-fg-secondary",
  failed: "bg-status-danger/15 text-status-danger",
};

function PackagesSection() {
  const queryClient = useQueryClient();
  const packages = useQuery(scriptPackagesQuery);
  const [spec, setSpec] = useState("");
  const [openLog, setOpenLog] = useState<string | null>(null);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: scriptKeys.packages });
  const add = useMutation({
    mutationFn: (value: string) => api.post<ScriptPackage>(`${ApiPath.scripts}/packages`, { spec: value }),
    onSuccess: async () => {
      setSpec("");
      await invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`${ApiPath.scripts}/packages/${id}`),
    onSuccess: invalidate,
  });

  return (
    <section data-scripts-packages className="flex flex-col gap-3 rounded-[10px] border border-subtle bg-surface p-4">
      <div className="flex items-center gap-2">
        <Package size={15} className="text-accent-text" aria-hidden />
        <h2 className="text-sm font-medium text-heading">Packages</h2>
        <span className="text-[11px] text-fg-muted">What your scripts may import, beyond the standard library and the SDK.</span>
      </div>
      {packages.data && packages.data.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {packages.data.map((row) => (
            <li key={row.id} data-package={row.name} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded border border-subtle/80 bg-base/40 px-2.5 py-1.5 text-xs">
              <span data-package-status={row.status} className={`rounded px-1.5 py-px text-[10px] uppercase tracking-wide ${PACKAGE_TONE[row.status]}`}>
                {row.status}
              </span>
              <span className="font-medium text-fg">{row.name}</span>
              <span className="text-[11px] text-fg-muted">{row.spec}</span>
              {row.resolved_version && <span className="text-[11px] text-fg-secondary">→ {row.resolved_version}</span>}
              <span className="ml-auto flex items-center gap-1">
                {row.log && (
                  <Button type="button" variant={ButtonVariant.ghost} size="sm" onClick={() => setOpenLog(openLog === row.id ? null : row.id)}>
                    log
                  </Button>
                )}
                <Button type="button" variant={ButtonVariant.dangerGhost} size="sm" aria-label={`Remove ${row.name}`} disabled={remove.isPending} onClick={() => remove.mutate(row.id)}>
                  <Trash2 size={12} aria-hidden />
                </Button>
              </span>
              {openLog === row.id && (
                <pre className="mt-1 max-h-48 w-full overflow-auto rounded border border-subtle bg-base p-2 text-[11px] text-fg-secondary">{row.log}</pre>
              )}
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          if (spec.trim()) add.mutate(spec.trim());
        }}
      >
        <TextField label="Add a package" value={spec} onChange={(event) => setSpec(event.target.value)} placeholder="requests>=2.31" hint="A name with optional extras and version specifiers. Not a URL, a path or an option." className="min-w-[280px]" />
        <Button type="submit" disabled={add.isPending || !spec.trim()}>
          <Plus size={13} aria-hidden />
          {add.isPending ? "Installing…" : "Install"}
        </Button>
      </form>
      {(add.isError || remove.isError) && <p className="text-xs text-status-danger">{errorMessage(add.error ?? remove.error)}</p>}
    </section>
  );
}

// --- the library --------------------------------------------------------------

function LibrarySection() {
  const queryClient = useQueryClient();
  const scripts = useQuery(scriptsQuery);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const create = useMutation({
    mutationFn: async () => {
      const starter = await api.get<{ body: string }>(`${ApiPath.scripts}/starter`);
      const count = scripts.data?.length ?? 0;
      return api.post<Script>(ApiPath.scripts, { name: `New script ${count + 1}`, body: starter.body, note: "created" });
    },
    onSuccess: async (script) => {
      await queryClient.invalidateQueries({ queryKey: scriptKeys.all });
      setEditing(script.id);
    },
  });

  return (
    <section data-scripts-library className="flex flex-col gap-3 rounded-[10px] border border-subtle bg-surface p-4">
      <div className="flex items-center gap-2">
        <Play size={15} className="text-accent-text" aria-hidden />
        <h2 className="text-sm font-medium text-heading">Scripts</h2>
        <span className="text-[11px] text-fg-muted">
          Each defines <code className="text-fg">main(ctx)</code>. A “Run a script” node publishes the dict it returns; a “Decide with a script” node takes the port it names.
        </span>
        <Button type="button" size="sm" className="ml-auto" disabled={create.isPending} onClick={() => create.mutate()}>
          <Plus size={13} aria-hidden />
          New script
        </Button>
      </div>
      {create.isError && <p className="text-xs text-status-danger">{errorMessage(create.error)}</p>}
      {scripts.data && scripts.data.length === 0 && (
        <p className="text-xs text-fg-secondary">No scripts yet. New script starts you from the author contract.</p>
      )}
      {scripts.data && scripts.data.length > 0 && (
        <ul className="flex flex-col gap-0.5" data-scripts-list>
          {scripts.data.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                data-script-row={row.name}
                aria-expanded={editing === row.id}
                onClick={() => setEditing(editing === row.id ? null : row.id)}
                className={`flex w-full flex-wrap items-baseline gap-x-2 rounded border px-2.5 py-1.5 text-left text-xs cursor-pointer hover:bg-elevated ${
                  editing === row.id ? "border-emphasis bg-elevated" : "border-subtle/80 bg-base/40"
                }`}
              >
                <span className="font-medium text-fg">{row.name}</span>
                <span className="text-[11px] text-fg-muted">v{row.version}</span>
                {row.description && <span className="text-[11px] text-fg-secondary">{row.description}</span>}
                <span className="ml-auto text-[11px] text-fg-faint">{relativeTime(row.updated_at)}</span>
              </button>
              {editing === row.id && <ScriptEditor id={row.id} onDeleted={() => setEditing(null)} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ScriptEditor({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const queryClient = useQueryClient();
  const script = useQuery(scriptQuery(id));
  const versions = useQuery(scriptVersionsQuery(id));
  const [draft, setDraft] = useState<{ name: string; description: string; body: string; note: string } | null>(null);
  const [packet, setPacket] = useState('{"items": [], "vars": {}, "params": {}}');
  const [confirmDialog, confirm] = useConfirm();
  const current = draft ?? (script.data ? { name: script.data.name, description: script.data.description, body: script.data.body, note: "" } : null);

  const save = useMutation({
    mutationFn: () => api.patch<Script>(`${ApiPath.scripts}/${id}`, current),
    onSuccess: async () => {
      setDraft(null);
      await queryClient.invalidateQueries({ queryKey: scriptKeys.all });
      await queryClient.invalidateQueries({ queryKey: scriptKeys.one(id) });
      await queryClient.invalidateQueries({ queryKey: scriptKeys.versions(id) });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(`${ApiPath.scripts}/${id}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: scriptKeys.all });
      onDeleted();
    },
  });
  const run = useMutation({
    mutationFn: () => {
      let body: unknown = {};
      try {
        body = JSON.parse(packet || "{}");
      } catch {
        throw new Error("the packet is not valid JSON");
      }
      return api.post<ScriptRunOutcome>(`${ApiPath.scripts}/${id}/run`, body);
    },
  });

  if (!current) return <p className="px-2 py-2 text-xs text-fg-muted">Loading…</p>;
  const dirty = draft !== null;
  return (
    <div data-script-editor className="mt-1 flex flex-col gap-3 rounded border border-subtle bg-surface/60 p-3">
      {confirmDialog}
      <div className="flex flex-wrap items-end gap-2">
        <TextField label="Name" value={current.name} onChange={(event) => setDraft({ ...current, name: event.target.value })} className="max-w-xs" />
        <TextField label="Description" value={current.description} onChange={(event) => setDraft({ ...current, description: event.target.value })} className="min-w-[280px] flex-1" />
      </div>
      <PythonEditor value={current.body} onChange={(body) => setDraft({ ...current, body })} />
      <div className="flex flex-wrap items-end gap-2">
        <TextField label="Why this change (optional)" value={current.note} onChange={(event) => setDraft({ ...current, note: event.target.value })} className="min-w-[260px] flex-1" />
        <Button type="button" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button
          type="button"
          variant={ButtonVariant.dangerGhost}
          disabled={remove.isPending}
          onClick={async () => {
            if (await confirm({ title: `Delete ${current.name}?`, message: "Automations that name this script will skip their script nodes.", confirmLabel: "Delete", danger: true })) remove.mutate();
          }}
        >
          <Trash2 size={13} aria-hidden />
          Delete
        </Button>
      </div>
      {save.isError && <p className="text-xs text-status-danger">{errorMessage(save.error)}</p>}
      {versions.data && versions.data.length > 1 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-fg-secondary">{versions.data.length} versions</summary>
          <ul className="mt-1 flex flex-col gap-0.5">
            {versions.data.map((version) => (
              <li key={version.id} className="flex items-baseline gap-2">
                <span className="font-medium text-fg">v{version.version}</span>
                <span className="text-fg-muted">{relativeTime(version.created_at)}</span>
                {version.note && <span className="text-fg-secondary">{version.note}</span>}
                {version.version !== script.data?.version && (
                  <Button type="button" variant={ButtonVariant.ghost} size="sm" onClick={() => setDraft({ ...current, body: version.body, note: `Restored v${version.version}` })}>
                    Load into editor
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      <div data-script-run className="flex flex-col gap-2 rounded border border-subtle bg-base/40 p-2">
        <span className="text-[11px] uppercase tracking-wide text-fg-muted">Run now</span>
        <textarea
          aria-label="Packet"
          value={packet}
          onChange={(event) => setPacket(event.target.value)}
          rows={3}
          className="w-full rounded-[6px] border border-subtle bg-base p-2 font-mono text-[12px] text-fg"
        />
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" disabled={run.isPending || dirty} onClick={() => run.mutate()}>
            <Play size={12} aria-hidden />
            {run.isPending ? "Running…" : "Run"}
          </Button>
          {dirty && <span className="text-[11px] text-fg-muted">Save first — a run uses the saved body.</span>}
          {run.isError && <span className="text-[11px] text-status-danger">{errorMessage(run.error)}</span>}
        </div>
        {run.data && <RunOutcomeView outcome={run.data} />}
      </div>
    </div>
  );
}

function RunOutcomeView({ outcome }: { outcome: ScriptRunOutcome }) {
  return (
    <div data-run-outcome={outcome.ok ? "ok" : "failed"} className="flex flex-col gap-1 text-[11px]">
      <div className="flex items-center gap-2">
        <span className={`rounded px-1.5 py-px text-[10px] uppercase tracking-wide ${outcome.ok ? "bg-emerald-500/15 text-emerald-300" : "bg-status-danger/15 text-status-danger"}`}>
          {outcome.ok ? "ok" : "failed"}
        </span>
        <span className="text-fg-muted">{outcome.duration_ms} ms</span>
        {outcome.error && <span className="text-status-danger">{outcome.error}</span>}
      </div>
      {outcome.ok && (
        <pre className="max-h-40 overflow-auto rounded border border-subtle bg-base p-2 text-fg">{JSON.stringify(outcome.result, null, 2)}</pre>
      )}
      {outcome.stderr && (
        <pre className="max-h-40 overflow-auto rounded border border-subtle bg-base p-2 text-fg-secondary">{outcome.stderr}</pre>
      )}
      {outcome.stdout && (
        <pre className="max-h-40 overflow-auto rounded border border-subtle bg-base p-2 text-fg-faint">{outcome.stdout}</pre>
      )}
    </div>
  );
}
