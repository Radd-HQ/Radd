import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api, Card, QueryError, Spinner } from "@radd/plugin-sdk";
import { AiPath, type EmbeddingCoverage } from "./settings/types";

/** AI owns its monitoring data and presentation; no request survives withdrawal. */
export function EmbeddingHealthCard() {
  const coverage = useQuery({
    queryKey: ["ai", "monitoring-coverage"],
    queryFn: ({ signal }) => api.get<EmbeddingCoverage>(AiPath.coverage, { signal }),
    refetchInterval: 5000, retry: false, staleTime: 0, gcTime: 0,
  });
  if (coverage.isPending) return <Spinner />;
  if (coverage.isError) return <QueryError label="semantic index coverage" error={coverage.error} />;
  if (!coverage.data.enabled) return null;
  const data = coverage.data;
  return <Card title={<span className="flex items-center gap-1.5"><Sparkles size={13} aria-hidden />Semantic index</span>}>
    <div className="flex justify-between gap-4 py-1 text-[13px]">
      <span className="text-fg-secondary">Issues embedded</span>
      <span className="font-medium tabular-nums text-heading">{data.items_embedded.toLocaleString()} / {data.items_total.toLocaleString()}</span>
    </div>
    <div className="flex justify-between gap-4 py-1 text-[13px]">
      <span className="text-fg-secondary">Pages embedded</span>
      <span className="font-medium tabular-nums text-heading">{data.docs_embedded.toLocaleString()} / {data.docs_total.toLocaleString()}</span>
    </div>
    {(data.items_embedded < data.items_total || data.docs_embedded < data.docs_total) &&
      <p className="mt-2 text-xs text-fg-muted">Backfill in progress — the embedder works through the backlog in batches.</p>}
  </Card>;
}
