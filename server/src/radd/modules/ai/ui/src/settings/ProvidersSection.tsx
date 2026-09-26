import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Activity, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { api, errorMessage, useConfirm, Button, EmptyState, ErrorText, QueryError, Table, TableSkeleton,
  TBody, Td, Th, THead } from "@radd/plugin-sdk";
import { ProviderModal, WIRE_SHAPE_LABELS } from "./ProviderModal";
import { useAiProviders, useInvalidateAi } from "./queries";
import { AiEntity, AiPath, AiProviderSource, AiWireShape, sectionHeadClasses, type AiProbeResult,
  type AiProviderRead } from "./types";

type Probe = AiProbeResult | "pending";

/**
 * Provider registry (spec 101): the servers Radd's AI features speak to. A provider is endpoint +
 * key + wire shape; what it's used FOR is the roles section below.
 */
export function ProvidersSection() {
  const providers = useAiProviders();
  const invalidate = useInvalidateAi();
  const [confirmDialog, confirm] = useConfirm();
  const [editing, setEditing] = useState<AiProviderRead | null>(null);
  const [adding, setAdding] = useState(false);
  // Per-row probe outcome; "pending" while the request is in flight.
  const [probes, setProbes] = useState<Record<string, Probe>>({});

  const test = useMutation({
    mutationFn: (providerId: string) => api.post<AiProbeResult>(AiPath.providerTest(providerId), {}),
    onMutate: (providerId) => setProbes((prev) => ({ ...prev, [providerId]: "pending" })),
    onSuccess: (result, providerId) => setProbes((prev) => ({ ...prev, [providerId]: result })),
    // The endpoint reports failures as data; an error here is Radd itself (403, network).
    onError: (error, providerId) =>
      setProbes((prev) => ({ ...prev, [providerId]: { ok: false, error: errorMessage(error), latency_ms: null } })),
  });

  // Deleting a provider clears the roles assigned to it, so both lists refresh.
  const remove = useMutation({
    mutationFn: (providerId: string) => api.delete<void>(AiPath.provider(providerId)),
    onSettled: () => invalidate(AiEntity.provider, AiEntity.role),
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
    <section data-ai-providers>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className={`${sectionHeadClasses} mb-0`}>Providers</h2>
        <Button onClick={() => setAdding(true)}>
          <Plus size={14} aria-hidden />
          New provider
        </Button>
      </div>
      <p className="mb-3 text-xs text-fg-muted">
        Servers the AI features talk to — OpenAI-compatible (OpenAI, vLLM, Ollama, LiteLLM) or Anthropic. API keys
        are stored server-side and never shown again.
      </p>
      {providers.isPending ? (
        <TableSkeleton rows={2} />
      ) : providers.isError ? (
        <QueryError label="AI providers" error={providers.error} />
      ) : list.length === 0 ? (
        <EmptyState icon={Sparkles}
          message="No providers yet — every AI feature stays off until one is added and given a role." />
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
                <ProviderRow key={provider.id} provider={provider} probe={probes[provider.id]}
                  onTest={() => test.mutate(provider.id)} onEdit={() => setEditing(provider)}
                  onDelete={() => void onDelete(provider)} />
              ))}
            </TBody>
          </Table>
        </div>
      )}
      {remove.isError && <ErrorText className="mt-2" error={remove.error} />}
      {(adding || editing) && (
        <ProviderModal existing={editing} onClose={() => {
          setAdding(false);
          setEditing(null);
        }} />
      )}
      {confirmDialog}
    </section>
  );
}

const faint = (text: string) => <span className="text-fg-faint">{text}</span>;

function ProviderRow({ provider, probe, onTest, onEdit, onDelete }: {
  provider: AiProviderRead;
  probe: Probe | undefined;
  onTest: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const paramCount = Object.keys(provider.request_params).length;
  return (
    <>
      <tr>
        <Td className="font-medium text-heading">
          <span className="inline-flex items-center gap-1.5">
            {provider.name}
            {provider.source === AiProviderSource.env && (
              <span className="rounded bg-elevated px-1.5 py-px text-[10px] font-normal text-fg-muted"
                title="Seeded from environment variables — editable like any other row">
                env
              </span>
            )}
          </span>
        </Td>
        <Td>{WIRE_SHAPE_LABELS[provider.wire_shape]}</Td>
        <Td>{provider.base_url || faint("default endpoint")}</Td>
        <Td>{provider.default_model || faint("—")}</Td>
        <Td>{provider.has_api_key ? "Set" : faint("—")}</Td>
        <Td>
          {provider.wire_shape === AiWireShape.local ? faint("—") : (
            <span className="inline-flex items-center gap-1.5">
              {provider.reasoning ? "Model default" : "Off"}
              {paramCount > 0 && (
                <span className="rounded bg-elevated px-1.5 py-px text-[10px] text-fg-muted"
                  title={JSON.stringify(provider.request_params)}>
                  +{paramCount} param{paramCount === 1 ? "" : "s"}
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
          <Button size="sm" variant="danger-ghost" onClick={onDelete} aria-label={`Delete ${provider.name}`}>
            <Trash2 size={13} aria-hidden />
          </Button>
        </Td>
      </tr>
      {probe && probe !== "pending" && (
        <tr>
          <Td colSpan={7} className="py-1.5">
            {probe.ok ? (
              <span className="text-xs text-status-success-ink" data-probe="ok">
                Reachable · {Math.round(probe.latency_ms ?? 0)} ms
              </span>
            ) : (
              <span className="text-xs text-status-danger-ink" data-probe="failed">{probe.error}</span>
            )}
          </Td>
        </tr>
      )}
    </>
  );
}
