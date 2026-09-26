import { Suspense, lazy, useCallback, useState, type ReactNode } from "react";
import { AiResultsContext, type AiResultRequest } from "./ai-results";

// The panel (and the markdown renderer it streams into) loads with the first answer.
const AiResultsPanel = lazy(() => import("./AiResultsPanel").then((module) => ({ default: module.AiResultsPanel })));

/**
 * The AI results pane beside a reading surface (RADD-772), for surfaces that are not the issue
 * page — the wiki page renders it through the SDK (RADD-1392). Providing the context IS the
 * switch: `AiReadMenu` answers here instead of in its popover. Beside the content at @4xl, stacked
 * above it below that; the caller supplies the `@container/page` ancestor the variants query.
 * `runId` bumps per request so re-running the same summarize re-fires the stream.
 *
 * The pane itself is NOT lazy, and must not be: `children` is the page, and a lazy wrapper renders
 * it as its Suspense fallback first and then again inside the loaded pane — a remount that threw
 * away an open edit session when the chunk arrived after Edit was pressed.
 */
export function AiResultsPane({ children }: { children: ReactNode }) {
  const [results, setResults] = useState<{ request: AiResultRequest; runId: number } | null>(null);
  const open = useCallback((request: AiResultRequest) => {
    setResults((current) => ({ request, runId: (current?.runId ?? 0) + 1 }));
  }, []);
  return (
    <AiResultsContext.Provider value={open}>
      <div className="flex flex-col items-start gap-3 @4xl:flex-row @4xl:justify-center">
        {results && (
          <Suspense fallback={null}>
            <AiResultsPanel
              request={results.request}
              runId={results.runId}
              onClose={() => setResults(null)}
              className="order-first m-6 mb-0 w-[calc(100%-3rem)] @4xl:sticky @4xl:top-0 @4xl:order-2 @4xl:ml-0 @4xl:max-h-[calc(100vh-8rem)] @4xl:w-96 @4xl:shrink-0"
            />
          </Suspense>
        )}
        <div className="w-full min-w-0 flex-1 @4xl:w-auto">{children}</div>
      </div>
    </AiResultsContext.Provider>
  );
}
