import { BookOpen, Sparkles } from "lucide-react";
import { api, paletteMode, type PaletteRow, type PaletteRows } from "@radd/plugin-sdk";
import { useAiStatus } from "../queries";
import { AiEndpoint } from "../transport";
import { AiFeature, type SemanticResponse } from "../types";

/** The palette's Ask: one semantic probe over issues and pages (GET /search/semantic, RBAC-scoped),
 *  answered as the palette's own rows. */

const percent = (score: number) => `${Math.round(score * 100)}%`;

/** A page's permalink: its stable public address, which resolves to the readable path (spec 124). */
const pagePermalink = (pageId: string) => `/pages?pageId=${encodeURIComponent(pageId)}`;

/** The semantic matches as rows — issues first, then pages, each with its score. The response's own
 *  `enabled` says whether meaning search is live here (it never errors for that). */
export async function semanticAnswer(query: string, { signal }: { signal: AbortSignal }): Promise<PaletteRows> {
  const found = await api.get<SemanticResponse>(AiEndpoint.searchSemantic, { signal, query: { q: query } });
  const rows: PaletteRow[] = [
    ...found.items.map((item) => ({
      id: `item:${item.item_id}`,
      badge: item.key,
      title: item.title,
      hint: percent(item.score),
      href: `/issues/${encodeURIComponent(item.key)}`,
    })),
    ...found.docs.map((doc) => ({
      id: `page:${doc.page_id}`,
      icon: BookOpen,
      title: doc.title,
      hint: percent(doc.score),
      href: pagePermalink(doc.page_id),
    })),
  ];
  return {
    heading: "Semantic matches",
    rows,
    empty: found.enabled ? "Nothing similar found." : "Semantic search isn't available.",
  };
}

/** Offered while the instance's semantic search feature is on (toggle AND embeddings role). */
function useSemanticSearch(): boolean {
  const status = useAiStatus();
  return Boolean(status.data?.enabled && status.data.features[AiFeature.semanticSearch]);
}

export const askPaletteMode = paletteMode({
  id: "ai.ask",
  label: "Ask",
  hint: "search by meaning",
  icon: Sparkles,
  placeholder: "Search by meaning…",
  prompt: "Type to search by meaning.",
  useAvailable: useSemanticSearch,
  answer: semanticAnswer,
});
