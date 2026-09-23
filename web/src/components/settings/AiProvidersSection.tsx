import { useId, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiAiProviderPath, apiAiProviderTestPath } from "../../lib/constants";
import { aiProvidersQuery, queryKeys } from "../../lib/queries";
import {
  AiProviderSource,
  AiWireShape,
  type AiProbeResult,
  type AiProviderPayload,
  type AiProviderRead,
  type AiWireShapeValue,
} from "../../lib/types";
import { Button } from "../Button";
import { useConfirm } from "../ConfirmDialog";
import { EmptyState } from "../EmptyState";
import { Modal } from "../Modal";
import { QueryError } from "../QueryError";
import { SelectField } from "../SelectField";
import { Table, TBody, Td, Th, THead } from "../Table";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";
import { ErrorText } from "../ErrorText";

const WIRE_SHAPE_LABELS: Record<AiWireShapeValue, string> = {
  [AiWireShape.openai]: "OpenAI-compatible",
  [AiWireShape.anthropic]: "Anthropic",
  [AiWireShape.local]: "Built-in (CPU embeddings)",
};

/** Mirror of the backend's DEFAULT_BASE_URLS — placeholder only, "" round-trips. */
const DEFAULT_BASE_URLS: Record<AiWireShapeValue, string> = {
  [AiWireShape.openai]: "https://api.openai.com/v1",
  [AiWireShape.anthropic]: "https://api.anthropic.com",
  [AiWireShape.local]: "",
};

/** Keys the server refuses in request_params (mirror of RESERVED_REQUEST_PARAMS). */
const RESERVED_REQUEST_PARAMS = ["messages", "stream"];

/** The textarea's text as an object, or the message to show instead. "" = {}. */
function parseRequestParams(text: string): Record<string, unknown> | string {
  if (!text.trim()) return {};
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return `Not valid JSON: ${error instanceof Error ? error.message : String(error)}`;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return "Must be a JSON object of top-level request keys.";
  }
  const reserved = RESERVED_REQUEST_PARAMS.filter((key) => key in value);
  if (reserved.length > 0) return `Cannot set ${reserved.join(", ")} — those are the request itself.`;
  return value as Record<string, unknown>;
}

const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";

/** All AI admin surfaces hang off the same rows — refresh them together. */
function invalidateAiAdmin(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.aiProviders });
  void queryClient.invalidateQueries({ queryKey: queryKeys.aiRoles });
  void queryClient.invalidateQueries({ queryKey: queryKeys.aiStatus });
}

/**
 * Provider registry (spec 101): the servers Radd's AI features speak to.
 * A provider is endpoint + key + wire shape; what it's used FOR is the
 * roles section below.
 */
export function AiProvidersSection() {
  const providers = useQuery(aiProvidersQuery());
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [editing, setEditing] = useState<AiProviderRead | null>(null);
  const [adding, setAdding] = useState(false);
  // Per-row probe outcome; "pending" while the request is in flight.
  const [probes, setProbes] = useState<Record<string, AiProbeResult | "pending">>({});

  const test = useMutation({
    mutationFn: (providerId: string) =>
      api.post<AiProbeResult>(apiAiProviderTestPath(providerId), {}),
    onMutate: (providerId) => setProbes((prev) => ({ ...prev, [providerId]: "pending" })),
    onSuccess: (result, providerId) =>
      setProbes((prev) => ({ ...prev, [providerId]: result })),
    // The endpoint reports failures as data; an error here is Radd itself (403, network).
    onError: (error, providerId) =>
      setProbes((prev) => ({
        ...prev,
        [providerId]: { ok: false, error: errorMessage(error), latency_ms: null },
      })),
  });

  const remove = useMutation({
    mutationFn: (providerId: string) => api.delete<void>(apiAiProviderPath(providerId)),
    onSettled: () => invalidateAiAdmin(queryClient),
  });

  const onDelete = async (provider: AiProviderRead) => {
    const ok = await confirm({
      title: "Delete provider",
      message: `Delete "${provider.name}"? Any role assigned to it is cleared, and the features using that role go dormant.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(provider.id);
  };

  const list = providers.data ?? [];

  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className={`${sectionHeadClasses} mb-0`}>Providers</h2>
        <Button onClick={() => setAdding(true)}>
          <Plus size={14} aria-hidden />
          New provider
        </Button>
      </div>
      <p className="mb-3 text-xs text-fg-muted">
        Servers the AI features talk to — OpenAI-compatible (OpenAI, vLLM, Ollama, LiteLLM) or
        Anthropic. API keys are stored server-side and never shown again.
      </p>
      {providers.isPending ? (
        <TableSkeleton rows={2} />
      ) : providers.isError ? (
        <QueryError label="AI providers" error={providers.error} />
      ) : list.length === 0 ? (
        <EmptyState
          icon={Sparkles}
          message="No providers yet — every AI feature stays off until one is added and given a role."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                <Th>Wire shape</Th>
                <Th>Endpoint</Th>
                <Th>Default model</Th>
                <Th>Key</Th>
                <Th>Reasoning</Th>
                <Th className="w-40" />
              </tr>
            </THead>
            <TBody>
              {list.map((provider) => (
                <ProviderRow
                  key={provider.id}
                  provider={provider}
                  probe={probes[provider.id]}
                  onTest={() => test.mutate(provider.id)}
                  onEdit={() => setEditing(provider)}
                  onDelete={() => void onDelete(provider)}
                />
              ))}
            </TBody>
          </Table>
        </div>
      )}
      {remove.isError && (
        <ErrorText className="mt-2" error={remove.error} />
      )}
      {(adding || editing) && (
        <ProviderModal
          existing={editing}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
        />
      )}
      {confirmDialog}
    </section>
  );
}

function ProviderRow({
  provider,
  probe,
  onTest,
  onEdit,
  onDelete,
}: {
  provider: AiProviderRead;
  probe: AiProbeResult | "pending" | undefined;
  onTest: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <>
      <tr>
        <Td className="font-medium text-heading">
          <span className="inline-flex items-center gap-1.5">
            {provider.name}
            {provider.source === AiProviderSource.env && (
              <span
                className="rounded bg-elevated px-1.5 py-px text-[10px] font-normal text-fg-muted"
                title="Seeded from environment variables — editable like any other row"
              >
                env
              </span>
            )}
          </span>
        </Td>
        <Td>{WIRE_SHAPE_LABELS[provider.wire_shape]}</Td>
        <Td>
          {provider.base_url || (
            <span className="text-fg-faint">default endpoint</span>
          )}
        </Td>
        <Td>{provider.default_model || <span className="text-fg-faint">—</span>}</Td>
        <Td>{provider.has_api_key ? "Set" : <span className="text-fg-faint">—</span>}</Td>
        <Td>
          {provider.wire_shape === AiWireShape.local ? (
            <span className="text-fg-faint">—</span>
          ) : (
            <span className="inline-flex items-center gap-1.5">
              {provider.reasoning ? "Model default" : "Off"}
              {Object.keys(provider.request_params).length > 0 && (
                <span
                  className="rounded bg-elevated px-1.5 py-px text-[10px] text-fg-muted"
                  title={JSON.stringify(provider.request_params)}
                >
                  +{Object.keys(provider.request_params).length} param
                  {Object.keys(provider.request_params).length === 1 ? "" : "s"}
                </span>
              )}
            </span>
          )}
        </Td>
        <Td className="whitespace-nowrap text-right">
          <Button size="sm" variant="ghost" onClick={onTest} disabled={probe === "pending"}>
            <Activity size={13} aria-hidden />
            {probe === "pending" ? "Testing…" : "Test"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onEdit} aria-label={`Edit ${provider.name}`}>
            <Pencil size={13} aria-hidden />
          </Button>
          <Button
            size="sm"
            variant="danger-ghost"
            onClick={onDelete}
            aria-label={`Delete ${provider.name}`}
          >
            <Trash2 size={13} aria-hidden />
          </Button>
        </Td>
      </tr>
      {probe && probe !== "pending" && (
        <tr>
          <Td colSpan={7} className="py-1.5">
            {probe.ok ? (
              <span className="text-xs text-emerald-400">
                Reachable · {Math.round(probe.latency_ms ?? 0)} ms
              </span>
            ) : (
              <span className="text-xs text-red-400">{probe.error}</span>
            )}
          </Td>
        </tr>
      )}
    </>
  );
}

function ProviderModal({
  existing,
  onClose,
}: {
  existing: AiProviderRead | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const requestParamsId = useId();
  const [name, setName] = useState(existing?.name ?? "");
  const [wireShape, setWireShape] = useState<AiWireShapeValue>(
    existing?.wire_shape ?? AiWireShape.openai,
  );
  const localEmbed = useQuery({
    queryKey: ["ai", "local-embed"],
    queryFn: ({ signal }) =>
      api.get<{ available: boolean; default_model: string; models: string[] }>(
        ApiPath.aiLocalEmbed, { signal },
      ),
    enabled: wireShape === AiWireShape.local,
    staleTime: 60_000,
  });
  const [baseUrl, setBaseUrl] = useState(existing?.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [defaultModel, setDefaultModel] = useState(existing?.default_model ?? "");
  // RADD-1273: off for every new connection — Radd states its preference on
  // each request instead of relying on the server's chat template.
  const [reasoning, setReasoning] = useState(existing?.reasoning ?? false);
  const [requestParams, setRequestParams] = useState(
    existing && Object.keys(existing.request_params).length > 0
      ? JSON.stringify(existing.request_params, null, 2)
      : "",
  );
  const [paramsError, setParamsError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: AiProviderPayload) =>
      existing
        ? api.patch<AiProviderRead>(apiAiProviderPath(existing.id), body)
        : api.post<AiProviderRead>(ApiPath.aiProviders, body),
    onSuccess: () => {
      invalidateAiAdmin(queryClient);
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    const parsed = parseRequestParams(requestParams);
    if (typeof parsed === "string") {
      setParamsError(parsed);
      return;
    }
    setParamsError(null);
    save.mutate({
      name: name.trim(),
      wire_shape: wireShape,
      base_url: baseUrl.trim(),
      // "" on update = keep the stored key (reads are redacted).
      api_key: apiKey,
      default_model: defaultModel.trim(),
      reasoning,
      request_params: parsed,
    });
  };

  return (
    <Modal title={existing ? "Edit provider" : "New provider"} onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Ollama on the farm"
          maxLength={200}
          required
        />
        <SelectField
          label="Wire shape"
          value={wireShape}
          onChange={(event) => setWireShape(event.target.value as AiWireShapeValue)}
          hint="The protocol the server speaks, not the vendor — vLLM, Ollama and LiteLLM all speak the OpenAI shape. Built-in runs a small embedding model on this server's CPU (embeddings role only)."
        >
          <option value={AiWireShape.openai}>{WIRE_SHAPE_LABELS[AiWireShape.openai]}</option>
          <option value={AiWireShape.anthropic}>{WIRE_SHAPE_LABELS[AiWireShape.anthropic]}</option>
          <option value={AiWireShape.local}>{WIRE_SHAPE_LABELS[AiWireShape.local]}</option>
        </SelectField>
        {wireShape !== AiWireShape.local && (
          <>
            <TextField
              label="Base URL"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={DEFAULT_BASE_URLS[wireShape]}
              maxLength={500}
              hint="Leave empty for the shape's default endpoint."
            />
            <TextField
              label="API key"
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={existing?.has_api_key ? "••••••••" : ""}
              hint={
                existing
                  ? "Leave empty to keep the stored key."
                  : "Optional — self-hosted servers often need none."
              }
            />
          </>
        )}
        <TextField
          label="Default model"
          value={defaultModel}
          onChange={(event) => setDefaultModel(event.target.value)}
          placeholder={
            wireShape === AiWireShape.local
              ? (localEmbed.data?.default_model ?? "BAAI/bge-small-en-v1.5")
              : "e.g. gpt-4o-mini or qwen3:14b"
          }
          maxLength={200}
          list={wireShape === AiWireShape.local ? "local-embed-models" : undefined}
          hint={
            wireShape === AiWireShape.local
              ? localEmbed.data?.available === false
                ? "The built-in backend isn't installed on this server (pip install 'radd[localembed]')."
                : "Leave empty for the default. Weights download on first use; Test runs one embedding."
              : "Used by roles that don't pin their own model, and by Test."
          }
        />
        {/* RADD-1101: the catalog GET /ai/local-embed always served, surfaced at
            last — the browser's datalist keeps the field free-typed while
            offering exactly the supported weights. */}
        {wireShape === AiWireShape.local && (
          <datalist id="local-embed-models">
            {(localEmbed.data?.models ?? []).map((model) => (
              <option key={model} value={model} />
            ))}
          </datalist>
        )}
        {wireShape !== AiWireShape.local && (
          <>
            <label className="flex items-start gap-2 text-xs text-fg">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={reasoning}
                onChange={(event) => setReasoning(event.target.checked)}
              />
              <span>
                <span className="font-medium text-heading">Reasoning</span>
                <span className="mt-0.5 block text-fg-muted">
                  Off (the default) asks a thinking model not to think before it answers —
                  every reply comes back in a fraction of the time and none of the token
                  budget goes to a hidden monologue. On leaves the model to its own default.
                  Sent as{" "}
                  <code className="rounded bg-elevated px-1">
                    {wireShape === AiWireShape.anthropic
                      ? "thinking"
                      : "chat_template_kwargs.enable_thinking"}
                  </code>
                  ; api.openai.com rejects that key, so an OpenAI-hosted provider keeps this on.
                </span>
              </span>
            </label>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={requestParamsId} className="text-xs font-medium text-fg-secondary">
                Extra request parameters (JSON)
              </label>
              <textarea
                id={requestParamsId}
                value={requestParams}
                onChange={(event) => setRequestParams(event.target.value)}
                rows={3}
                spellCheck={false}
                placeholder={'{ "temperature": 0.2 }'}
                aria-invalid={paramsError ? true : undefined}
                className="rounded-md border border-strong bg-surface px-2.5 py-2 font-mono text-[12px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
              />
              <p className="text-[11px] text-fg-muted">
                An object of top-level keys merged into every chat request after Radd's own
                — a value here overrides Radd's choice, including the reasoning switch. Not
                sent with embedding requests.
              </p>
              {paramsError && <p className="text-xs text-red-400">{paramsError}</p>}
            </div>
          </>
        )}
        <div className="mt-1 flex items-center justify-end gap-2">
          {save.isError && (
            <span className="mr-auto text-xs text-red-400">{errorMessage(save.error)}</span>
          )}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending || !name.trim()}>
            {save.isPending ? "Saving…" : existing ? "Save changes" : "Create provider"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
