import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { ApiPath, apiAiRolePath } from "../../lib/constants";
import type { EmbeddingCoverage } from "../../lib/types";
import { aiProvidersQuery, aiRolesQuery, queryKeys } from "../../lib/queries";
import {
  AiRole,
  AiWireShape,
  type AiProviderRead,
  type AiRoleRead,
  type AiRoleValue,
} from "../../lib/types";
import { Select, type SelectOption } from "../Select";
import { Spinner } from "../Spinner";
import { QueryError } from "../QueryError";
import { Table, TBody, Td, Th, THead } from "../Table";
import { ErrorText } from "../ErrorText";

const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";

/** The three fixed roles — features resolve a role, never a provider directly. */
const ROLE_ROWS: readonly { role: AiRoleValue; label: string; blurb: string }[] = [
  {
    role: AiRole.chat,
    label: "Chat",
    blurb: "Editor actions, summarize, NL→SLQ, similar rerank",
  },
  { role: AiRole.embeddings, label: "Embeddings", blurb: "Semantic search" },
  { role: AiRole.vision, label: "Vision", blurb: "Storage routing classification" },
];

const NOT_ASSIGNED = "";

/**
 * Role → provider assignments (spec 101). Each feature asks for a role; an
 * unassigned role leaves its features dormant regardless of the toggles below.
 */
export function AiRolesSection() {
  const providers = useQuery(aiProvidersQuery());
  const roles = useQuery(aiRolesQuery());

  return (
    <section>
      <h2 className={sectionHeadClasses}>Model roles</h2>
      <p className="mb-3 text-xs text-fg-muted">
        What each configured model is for. Features resolve a role — swap the provider or model
        here and every feature follows, no per-feature settings.
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
                <RoleRow
                  key={role}
                  role={role}
                  label={label}
                  blurb={blurb}
                  providers={providers.data}
                  assignment={roles.data.find((row) => row.role === role) ?? null}
                />
              ))}
            </TBody>
          </Table>
        </div>
      )}
      <EmbeddingCoverageLine
        assigned={Boolean(roles.data?.some((row) => row.role === AiRole.embeddings))}
      />
    </section>
  );
}

function RoleRow({
  role,
  label,
  blurb,
  providers,
  assignment,
}: {
  role: AiRoleValue;
  label: string;
  blurb: string;
  providers: AiProviderRead[];
  assignment: AiRoleRead | null;
}) {
  const queryClient = useQueryClient();
  const [model, setModel] = useState(assignment?.model ?? "");

  // Re-seed the draft when the server row refreshes underneath us.
  useEffect(() => {
    setModel(assignment?.model ?? "");
  }, [assignment?.model]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.aiRoles });
    void queryClient.invalidateQueries({ queryKey: queryKeys.aiStatus });
  };
  const assign = useMutation({
    mutationFn: (body: { provider_id: string; model: string }) =>
      api.put<AiRoleRead>(apiAiRolePath(role), body),
    onSuccess: invalidate,
  });
  const clear = useMutation({
    mutationFn: () => api.delete<void>(apiAiRolePath(role)),
    onSuccess: invalidate,
  });

  const selectedProvider = providers.find((p) => p.id === assignment?.provider_id);

  const options: SelectOption[] = [
    { value: NOT_ASSIGNED, label: "Not assigned" },
    ...providers.map((provider) => {
      // Spec-96 idiom: disable up front, with the reason on hover — the backend
      // would 422 the same assignment.
      const noEmbeddings =
        role === AiRole.embeddings && provider.wire_shape === AiWireShape.anthropic;
      const localOnly =
        role !== AiRole.embeddings && provider.wire_shape === AiWireShape.local;
      return {
        value: provider.id,
        label: provider.name,
        disabled: noEmbeddings || localOnly || undefined,
        title: noEmbeddings
          ? "Anthropic has no embeddings API"
          : localOnly
            ? "The built-in backend only embeds"
            : undefined,
      };
    }),
  ];

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
    <tr>
      <Td>
        <p className="font-medium text-heading">{label}</p>
        <p className="text-xs text-fg-muted">{blurb}</p>
        {error && <ErrorText className="mt-1" error={error} />}
      </Td>
      <Td>
        <Select
          size="sm"
          aria-label={`${label} provider`}
          value={assignment?.provider_id ?? NOT_ASSIGNED}
          onChange={onProviderChange}
          options={options}
          disabled={busy}
        />
      </Td>
      <Td>
        <input
          aria-label={`${label} model`}
          value={model}
          onChange={(event) => setModel(event.target.value)}
          onBlur={saveModel}
          onKeyDown={(event) => {
            if (event.key === "Enter") saveModel();
          }}
          placeholder={selectedProvider?.default_model || "provider default"}
          disabled={!assignment || busy}
          className="h-7 w-full rounded-md border border-strong bg-surface px-2 text-xs text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-focus disabled:cursor-not-allowed disabled:opacity-50"
        />
      </Td>
    </tr>
  );
}

/** The backfill's progress line ("2,314 / 2,400 items embedded"), admin-only. */
function EmbeddingCoverageLine({ assigned }: { assigned: boolean }) {
  const coverage = useQuery({
    queryKey: queryKeys.aiEmbeddingCoverage,
    queryFn: () => api.get<EmbeddingCoverage>(ApiPath.aiEmbeddingCoverage),
    enabled: assigned,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data?.enabled) return false;
      const done =
        data.items_embedded >= data.items_total && data.docs_embedded >= data.docs_total;
      return done ? false : 5000; // live while the backfill grinds
    },
  });
  if (!assigned || !coverage.data?.enabled) return null;
  const { items_embedded, items_total, docs_embedded, docs_total } = coverage.data;
  return (
    <p className="mt-2 text-xs text-fg-muted">
      Semantic index: {items_embedded.toLocaleString()} / {items_total.toLocaleString()} items,{" "}
      {docs_embedded.toLocaleString()} / {docs_total.toLocaleString()} pages pages embedded.
    </p>
  );
}
