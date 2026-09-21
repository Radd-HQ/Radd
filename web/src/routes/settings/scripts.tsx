/**
 * Settings → Scripts (RADD-1269, reshaped by RADD-1272): the managed
 * interpreter and its packages — what is instance-wide. The scripts
 * themselves live on their automation nodes.
 */
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Package, Play, Plus, RotateCcw, Terminal, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import { scriptInterpreterQuery, scriptKeys, scriptPackagesQuery } from "../../lib/queries";
import type { ScriptInterpreter, ScriptInterpreterSettings, ScriptPackage } from "../../lib/types";
import { Button, ButtonVariant } from "../../components/Button";
import { Callout, CalloutKind } from "../../components/Callout";
import { SelectField } from "../../components/SelectField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { TextField } from "../../components/TextField";

export function ScriptsSettingsPage() {
  return (
    <SettingsPage
      history={{ entities: ["script_package", "script_interpreter"] }}
      title="Scripts"
      description="The interpreter that automation script nodes run in: a managed Python of its own, out of process, with the Radd SDK client and the packages you install here. The scripts themselves live on their automation nodes."
    >
      <div className="flex flex-col gap-6">
        <InterpreterSection />
        <IndexSection />
        <PackagesSection />
        <ContractSection />
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

// --- where packages come from (RADD-1277) ------------------------------------

function IndexSection() {
  const queryClient = useQueryClient();
  const interpreter = useQuery(scriptInterpreterQuery);
  const data = interpreter.data;
  const [indexUrl, setIndexUrl] = useState("");
  const [offline, setOffline] = useState(false);
  const [touched, setTouched] = useState(false);
  // The form mirrors the row until the admin edits it; a masked password
  // round-trips unchanged only if nobody touched the field.
  useEffect(() => {
    if (data && !touched) {
      setIndexUrl(data.index_url);
      setOffline(data.offline);
    }
  }, [data, touched]);
  const save = useMutation({
    mutationFn: (body: ScriptInterpreterSettings) => api.put<ScriptInterpreter>(`${ApiPath.scripts}/interpreter`, body),
    onSuccess: async () => {
      setTouched(false);
      await queryClient.invalidateQueries({ queryKey: scriptKeys.interpreter });
    },
  });
  return (
    <section data-scripts-index className="flex flex-col gap-3 rounded-[10px] border border-subtle bg-surface p-4">
      <div className="flex items-center gap-2">
        <Globe size={15} className="text-accent-text" aria-hidden />
        <h2 className="text-sm font-medium text-heading">Package index</h2>
        {data?.offline && (
          <span data-index-mode="offline" className="rounded bg-elevated px-1.5 py-px text-[10px] uppercase tracking-wide text-fg-secondary">
            offline
          </span>
        )}
      </div>
      <p className="text-xs text-fg-secondary">
        Packages resolve from the wheelhouses first, then from this index (empty means PyPI). A site with no route
        out names its own mirror here, or goes offline and drops wheels into{" "}
        <code className="text-fg">{data?.operator_wheelhouse ?? "…"}</code>, which is always searched.
        {data && data.wheelhouses.length > 0 && (
          <>
            {" "}
            Wheelhouses found: {data.wheelhouses.map((path) => (
              <code key={path} className="mr-1 text-fg">
                {path}
              </code>
            ))}
          </>
        )}
      </p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          save.mutate({ index_url: indexUrl.trim(), offline });
        }}
      >
        <TextField
          label="Index URL"
          value={indexUrl}
          placeholder="https://pypi.example.com/simple"
          onChange={(event) => {
            setTouched(true);
            setIndexUrl(event.target.value);
          }}
          className="min-w-72"
        />
        <label className="flex items-center gap-2 pb-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={offline}
            onChange={(event) => {
              setTouched(true);
              setOffline(event.target.checked);
            }}
            className="accent-accent"
          />
          Offline — wheelhouses only
        </label>
        <Button type="submit" disabled={save.isPending || !touched}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </form>
      {save.isError && <p className="text-xs text-status-danger">{errorMessage(save.error)}</p>}
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

// --- the contract -------------------------------------------------------------

/** Where the script itself lives is the automation node (RADD-1272). This
 * page owns what is instance-wide; the contract is repeated here so an admin
 * reads it where they set the interpreter up. */
function ContractSection() {
  return (
    <section data-scripts-contract className="flex flex-col gap-2 rounded-[10px] border border-subtle bg-surface p-4">
      <div className="flex items-center gap-2">
        <Play size={15} className="text-accent-text" aria-hidden />
        <h2 className="text-sm font-medium text-heading">Writing a script</h2>
      </div>
      <p className="text-xs text-fg-secondary">
        Drop a <strong className="font-medium text-fg">Run a script</strong> or{" "}
        <strong className="font-medium text-fg">Decide with a script</strong> node on an automation; the
        Python lives on the node, and the automation&rsquo;s versions are its history. A new node arrives
        with this contract filled in:
      </p>
      <pre className="overflow-auto rounded-[8px] border border-subtle bg-base p-3 text-[12px] leading-5 text-fg">{CONTRACT}</pre>
      <p className="text-xs text-fg-secondary">
        A <em>Run a script</em> node publishes the dict <code className="text-fg">main</code> returns: each key
        you declare as an output becomes a <code className="text-fg">{"{{name.key}}"}</code> token downstream.
        A <em>Decide with a script</em> node takes the port <code className="text-fg">main</code> names; a
        failure, a timeout or an unknown name takes <em>unavailable</em>. Scripts run out of process, with a
        short-lived key for the automation&rsquo;s identity: whatever they do through{" "}
        <code className="text-fg">ctx.client</code> is what that identity could do by hand.
      </p>
    </section>
  );
}

const CONTRACT = `def main(ctx):
    ctx.event        # the event that fired (type, actor, payload) — None on a manual/scheduled run
    ctx.items        # the issues this node is acting on, as full read models (list of dicts)
    ctx.item         # the first of them, for the per-item case
    ctx.vars         # values upstream nodes produced: ctx.vars["triage"]["priority"]
    ctx.params       # this node's own params
    ctx.client       # a ready radd_sdk.RaddClient, acting as the automation's identity
    ctx.log("text")  # a line on the run's stderr, shown in the run report
    return {"count": len(ctx.items)}`
