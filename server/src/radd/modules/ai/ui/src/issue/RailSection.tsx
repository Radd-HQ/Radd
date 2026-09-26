import { FileSearch, Sparkles } from "lucide-react";
import { Button } from "@radd/plugin-sdk";
import { useAiStatus } from "../queries";
import { useOpenAiResults } from "../results/open";

/** The issue rail's AI card (`issue.rail.top`): answers open in the reading pane, since the rail is
 *  too narrow. Nothing unless AI is enabled and the page has a pane. */
export function AiRailSection({ item }: { item: { id: string; title: string } }) {
  const status = useAiStatus();
  const openResults = useOpenAiResults();

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
