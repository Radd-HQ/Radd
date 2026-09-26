import { FileSearch, Sparkles } from "lucide-react";
import { Button } from "@radd/plugin-sdk";
import { useAiStatus } from "../queries";
import { useOpenAiResults } from "../results/open";

/**
 * "AI" card at the top of the issue rail (spec 46) — this plugin's `issue.rail.top` (RADD-1395):
 * on-demand summarize + find-similar. The ANSWERS open in the reading pane beside the reading
 * column — the rail is far too narrow to read a digest in. Renders nothing unless GET /ai/status
 * says enabled (no dead buttons), and nothing where the page has no reading pane.
 */
export function AiRailSection({ item }: { item: { id: string; title: string } }) {
  const status = useAiStatus();
  const openResults = useOpenAiResults();

  // Status error/pending/disabled all mean "render nothing" (spec 46 gate).
  if (!status.data?.enabled || !openResults) return null;

  return (
    <section className="rounded-xl border border-subtle bg-surface p-3 shadow-lift" data-ai-rail>
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <Sparkles size={12} aria-hidden />
        AI
      </h3>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => openResults({ kind: "item-summary", itemId: item.id })}>
          <Sparkles size={12} aria-hidden />
          Summarize
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => openResults({ kind: "similar", seed: { itemId: item.id }, text: item.title })}
        >
          <FileSearch size={12} aria-hidden />
          Find similar
        </Button>
      </div>
    </section>
  );
}
