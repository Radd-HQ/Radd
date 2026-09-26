import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, errorMessage, Button, Modal, SelectField, TextArea, TextField } from "@radd/plugin-sdk";
import { useInvalidateAi } from "./queries";
import { AiEntity, AiPath, AiWireShape, type AiProviderPayload, type AiProviderRead, type AiWireShapeValue,
  type LocalEmbedInfo } from "./types";

export const WIRE_SHAPE_LABELS: Record<AiWireShapeValue, string> = {
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

/** Create or edit one provider. */
export function ProviderModal({ existing, onClose }: { existing: AiProviderRead | null; onClose: () => void }) {
  const invalidate = useInvalidateAi();
  const [name, setName] = useState(existing?.name ?? "");
  const [wireShape, setWireShape] = useState<AiWireShapeValue>(existing?.wire_shape ?? AiWireShape.openai);
  const local = wireShape === AiWireShape.local;
  const localEmbed = useQuery({
    queryKey: ["ai", "local-embed"],
    queryFn: ({ signal }) => api.get<LocalEmbedInfo>(AiPath.localEmbed, { signal }),
    enabled: local,
    staleTime: 60_000,
  });
  const [baseUrl, setBaseUrl] = useState(existing?.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [defaultModel, setDefaultModel] = useState(existing?.default_model ?? "");
  // RADD-1273: off for every new connection — Radd states its preference on each request instead
  // of relying on the server's chat template.
  const [reasoning, setReasoning] = useState(existing?.reasoning ?? false);
  const [requestParams, setRequestParams] = useState(
    existing && Object.keys(existing.request_params).length > 0 ? JSON.stringify(existing.request_params, null, 2) : "",
  );
  const [paramsError, setParamsError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: AiProviderPayload) =>
      existing ? api.patch<AiProviderRead>(AiPath.provider(existing.id), body) : api.post<AiProviderRead>(AiPath.providers, body),
    onSuccess: () => {
      invalidate(AiEntity.provider, AiEntity.role);
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

  const modelHint = !local
    ? "Used by roles that don't pin their own model, and by Test."
    : localEmbed.data?.available === false
      ? "The built-in backend isn't installed on this server (pip install 'radd[localembed]')."
      : "Leave empty for the default. Weights download on first use; Test runs one embedding.";

  return (
    <Modal title={existing ? "Edit provider" : "New provider"} onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <TextField label="Name" value={name} onChange={(event) => setName(event.target.value)}
          placeholder="Ollama on the farm" maxLength={200} required />
        <SelectField label="Wire shape" value={wireShape}
          onChange={(event) => setWireShape(event.target.value as AiWireShapeValue)}
          hint="The protocol the server speaks, not the vendor — vLLM, Ollama and LiteLLM all speak the OpenAI shape. Built-in runs a small embedding model on this server's CPU (embeddings role only).">
          {Object.values(AiWireShape).map((shape) => <option key={shape} value={shape}>{WIRE_SHAPE_LABELS[shape]}</option>)}
        </SelectField>
        {!local && (
          <>
            <TextField label="Base URL" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={DEFAULT_BASE_URLS[wireShape]} maxLength={500} hint="Leave empty for the shape's default endpoint." />
            <TextField label="API key" type="password" autoComplete="new-password" value={apiKey}
              onChange={(event) => setApiKey(event.target.value)} placeholder={existing?.has_api_key ? "••••••••" : ""}
              hint={existing ? "Leave empty to keep the stored key." : "Optional — self-hosted servers often need none."} />
          </>
        )}
        <TextField label="Default model" value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)}
          placeholder={local ? (localEmbed.data?.default_model ?? "BAAI/bge-small-en-v1.5") : "e.g. gpt-4o-mini or qwen3:14b"}
          maxLength={200} list={local ? "local-embed-models" : undefined} hint={modelHint} />
        {/* RADD-1101: the browser's datalist keeps the field free-typed while offering exactly the
            weights the built-in backend supports. */}
        {local && (
          <datalist id="local-embed-models">
            {(localEmbed.data?.models ?? []).map((model) => <option key={model} value={model} />)}
          </datalist>
        )}
        {!local && (
          <>
            <label className="flex items-start gap-2 text-xs text-fg">
              <input type="checkbox" className="mt-0.5" checked={reasoning}
                onChange={(event) => setReasoning(event.target.checked)} />
              <span>
                <span className="font-medium text-heading">Reasoning</span>
                <span className="mt-0.5 block text-fg-muted">
                  Off (the default) asks a thinking model not to think before it answers — every reply comes back in a
                  fraction of the time and none of the token budget goes to a hidden monologue. On leaves the model to
                  its own default. Sent as{" "}
                  <code className="rounded bg-elevated px-1">
                    {wireShape === AiWireShape.anthropic ? "thinking" : "chat_template_kwargs.enable_thinking"}
                  </code>
                  ; api.openai.com rejects that key, so an OpenAI-hosted provider keeps this on.
                </span>
              </span>
            </label>
            <TextArea label="Extra request parameters (JSON)" value={requestParams}
              onChange={(event) => setRequestParams(event.target.value)} rows={3} spellCheck={false}
              placeholder={'{ "temperature": 0.2 }'} className="font-mono" error={paramsError ?? undefined}
              hint="An object of top-level keys merged into every chat request after Radd's own — a value here overrides Radd's choice, including the reasoning switch. Not sent with embedding requests." />
          </>
        )}
        <div className="mt-1 flex items-center justify-end gap-2">
          {save.isError && <span className="mr-auto text-xs text-status-danger-ink">{errorMessage(save.error)}</span>}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={save.isPending || !name.trim()}>
            {save.isPending ? "Saving…" : existing ? "Save changes" : "Create provider"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
