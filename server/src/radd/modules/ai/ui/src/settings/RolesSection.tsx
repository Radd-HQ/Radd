import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ErrorText, QueryError, SelectField, Spinner, Table, TBody, Td, Th, THead } from "@radd/plugin-sdk";
import { useAiProviders, useAiRoles, useInvalidateAi } from "./queries";
import { AiEntity, AiPath, AiRole, AiWireShape, sectionHeadClasses, type AiProviderRead, type AiRoleRead,
  type AiRoleValue, type EmbeddingCoverage } from "./types";

/** The three fixed roles — features resolve a role, never a provider directly. */
const ROLE_ROWS: readonly { role: AiRoleValue; label: string; blurb: string }[] = [
  { role: AiRole.chat, label: "Chat", blurb: "Editor actions, summarize, NL→SLQ, similar rerank" },
  { role: AiRole.embeddings, label: "Embeddings", blurb: "Semantic search" },
  { role: AiRole.vision, label: "Vision", blurb: "Storage routing classification; issue and page summaries see attached images" },
];

const NOT_ASSIGNED = "";

/**
 * Role → provider assignments (spec 101). Each feature asks for a role; an unassigned role leaves
 * its features dormant regardless of the toggles below.
 */
export function RolesSection() {
  const providers = useAiProviders();
  const roles = useAiRoles();

  return (
    <section data-ai-roles>
      <h2 className={sectionHeadClasses}>Model roles</h2>
      <p className="mb-3 text-xs text-fg-muted">
        What each configured model is for. Features resolve a role — swap the provider or model here and every
        feature follows, no per-feature settings.
      </p>
      {providers.isPending || roles.isPending ? (
        <Spinner label="Loading roles…" />
      ) : providers.isError ? (
        <QueryError label="AI providers" error={providers.error} />
      ) : roles.isError ? (
        <QueryError label="AI roles" error={roles.error} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Role</Th>
                <Th className="w-56">Provider</Th>
                <Th className="w-56">Model</Th>
              </tr>
            </THead>
            <TBody>
              {ROLE_ROWS.map(({ role, label, blurb }) => (
                <RoleRow key={role} role={role} label={label} blurb={blurb} providers={providers.data}
                  assignment={roles.data.find((row) => row.role === role) ?? null} />
              ))}
            </TBody>
          </Table>
        </div>
      )}
      <EmbeddingCoverageLine assigned={Boolean(roles.data?.some((row) => row.role === AiRole.embeddings))} />
    </section>
  );
}

function RoleRow({ role, label, blurb, providers, assignment }: {
  role: AiRoleValue;
  label: string;
  blurb: string;
  providers: AiProviderRead[];
  assignment: AiRoleRead | null;
}) {
  const invalidate = useInvalidateAi();
  const [model, setModel] = useState(assignment?.model ?? "");

  // Re-seed the draft when the server row refreshes underneath us.
  useEffect(() => {
    setModel(assignment?.model ?? "");
  }, [assignment?.model]);

  const assign = useMutation({
    mutationFn: (body: { provider_id: string; model: string }) => api.put<AiRoleRead>(AiPath.role(role), body),
    onSuccess: () => invalidate(AiEntity.role),
  });
  const clear = useMutation({
    mutationFn: () => api.delete<void>(AiPath.role(role)),
    onSuccess: () => invalidate(AiEntity.role),
  });

  const selectedProvider = providers.find((p) => p.id === assignment?.provider_id);

  const onProviderChange = (providerId: string) => {
    if (providerId === NOT_ASSIGNED) {
      if (assignment) clear.mutate();
      return;
    }
    assign.mutate({ provider_id: providerId, model });
  };

  const saveModel = () => {
    if (!assignment || model === assignment.model) return;
    assign.mutate({ provider_id: assignment.provider_id, model });
  };

  const busy = assign.isPending || clear.isPending;
  const error = assign.error ?? clear.error;

  return (
    <tr data-ai-role={role}>
      <Td>
        <p className="font-medium text-heading">{label}</p>
        <p className="text-xs text-fg-muted">{blurb}</p>
        {error && <ErrorText className="mt-1" error={error} />}
      </Td>
      <Td>
        <SelectField label="" ariaLabel={`${label} provider`} value={assignment?.provider_id ?? NOT_ASSIGNED}
          onChange={(event) => onProviderChange(event.target.value)} disabled={busy}>
          <option value={NOT_ASSIGNED}>Not assigned</option>
          {providers.map((provider) => {
            // Spec-96 idiom: disable up front, with the reason on hover — the backend would 422
            // the same assignment.
            const noEmbeddings = role === AiRole.embeddings && provider.wire_shape === AiWireShape.anthropic;
            const localOnly = role !== AiRole.embeddings && provider.wire_shape === AiWireShape.local;
            return (
              <option key={provider.id} value={provider.id} disabled={noEmbeddings || localOnly}
                title={noEmbeddings ? "Anthropic has no embeddings API" : localOnly ? "The built-in backend only embeds" : undefined}>
                {provider.name}
              </option>
            );
          })}
        </SelectField>
      </Td>
      <Td>
        <input aria-label={`${label} model`} value={model} onChange={(event) => setModel(event.target.value)}
          onBlur={saveModel} onKeyDown={(event) => {
            if (event.key === "Enter") saveModel();
          }}
          placeholder={selectedProvider?.default_model || "provider default"} disabled={!assignment || busy}
          className="h-8 w-full rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-focus disabled:cursor-not-allowed disabled:opacity-50" />
      </Td>
    </tr>
  );
}

/** The backfill's progress line ("2,314 / 2,400 issues embedded"), admin-only. */
function EmbeddingCoverageLine({ assigned }: { assigned: boolean }) {
  const coverage = useQuery({
    queryKey: ["ai", "settings-coverage"],
    meta: { entities: [AiEntity.role] },
    queryFn: ({ signal }) => api.get<EmbeddingCoverage>(AiPath.coverage, { signal }),
    enabled: assigned,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data?.enabled) return false;
      const done = data.items_embedded >= data.items_total && data.docs_embedded >= data.docs_total;
      return done ? false : 5000; // live while the backfill grinds
    },
  });
  if (!assigned || !coverage.data?.enabled) return null;
  const { items_embedded, items_total, docs_embedded, docs_total } = coverage.data;
  return (
    <p className="mt-2 text-xs text-fg-muted" data-ai-coverage>
      Semantic index: {items_embedded.toLocaleString()} / {items_total.toLocaleString()} issues,{" "}
      {docs_embedded.toLocaleString()} / {docs_total.toLocaleString()} pages embedded.
    </p>
  );
}
