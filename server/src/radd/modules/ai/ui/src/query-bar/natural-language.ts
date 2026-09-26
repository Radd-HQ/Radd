import { useSyncExternalStore } from "react";
import { Sparkles } from "lucide-react";
import { api, ApiError, QueryDialect, queryInputMode, type QueryDialectValue, type QueryDraft } from "@radd/plugin-sdk";
import { useAiStatus } from "../queries";
import { AI_PROVIDER_UNAVAILABLE_MESSAGE, AiEndpoint, isAiGone } from "../transport";
import { AiFeature, type NlQueryRequest, type NlQueryResponse } from "../types";

/** The query bar's Ask: POST /slq/nl turns natural language into a compile-validated query in the
 *  bar's dialect, plus a sentence saying what it means. */

// A 404 means this plugin (or the feature) went dormant since the status gate last looked: the
// mode stops offering itself until the gate reads the status again.
let goneAt = 0;
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
function markGone() {
  goneAt = Date.now();
  for (const listener of listeners) listener();
}

/** Natural language → SLQ in `dialect`. A provider failure reads as one clean sentence. */
async function naturalLanguageQuery(
  question: string,
  { dialect, signal }: { dialect: QueryDialectValue; signal: AbortSignal },
): Promise<QueryDraft> {
  const body: NlQueryRequest = { question, dialect };
  try {
    const answer = await api.post<NlQueryResponse>(AiEndpoint.nlQuery, body, { signal });
    return { query: answer.slq, explanation: answer.explanation };
  } catch (error) {
    if (isAiGone(error)) markGone();
    if (error instanceof ApiError && error.status === 502) throw new Error(AI_PROVIDER_UNAVAILABLE_MESSAGE);
    throw error;
  }
}

/** Offered while AI is configured and natural-language queries are on — and not since refused. */
function useNaturalLanguage(): boolean {
  const status = useAiStatus();
  const gone = useSyncExternalStore(subscribe, () => goneAt);
  return Boolean(status.data?.enabled && status.data.features[AiFeature.nlSlq]) && gone <= status.dataUpdatedAt;
}

export const naturalLanguageMode = queryInputMode({
  id: "ai.natural-language",
  label: "Ask",
  hint: "Natural language in; the answer lands as an SLQ query",
  icon: Sparkles,
  placeholder: "Ask: open bugs assigned to me — the answer lands as an SLQ query",
  ariaLabel: "Ask AI for a query",
  busyLabel: "Asking…",
  dialects: [QueryDialect.items, QueryDialect.worklog],
  useAvailable: useNaturalLanguage,
  toQuery: naturalLanguageQuery,
});
