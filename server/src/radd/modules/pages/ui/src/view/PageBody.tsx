import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ExtensionError, MarkdownSourceContext, RichViewer, UnknownExtension, headingAnchorId, lookupPageExtension,
  parseExtensionParams, splitExtensionBlocks, type TaskToggle,
} from "@radd/plugin-sdk";
// The renderers load with the page's own chunk, so a page (and its print view) never waits on them.
import "./extensions";

/**
 * A page body: prose through the rich viewer, `radd:*` blocks as React (RADD-709). Heading ids are
 * assigned here over the RENDERED headings with the same duplicate rule `headingsOf` uses on the
 * source, so `radd:toc` links land. `onReady` fires once every prose run has rendered (print waits on it).
 * Prose renders EAGERLY: behind the viewport gate a `radd:toc` below the fold links to ids never
 * assigned, and printing emits placeholder text.
 */
export function PageBody({
  text,
  className = "",
  onReady,
  onToggleTask,
}: {
  text: string;
  /** RADD-1296: present when the reader may write the page — a tick in any
   *  segment is indexed across the WHOLE body (this container is the scope). */
  onToggleTask?: (toggle: TaskToggle) => Promise<unknown>;
  className?: string;
  /** Fires once every segment has rendered — the print route waits on it. */
  onReady?: () => void;
}) {
  const segments = useMemo(() => splitExtensionBlocks(text), [text]);
  const proseCount = segments.filter((segment) => segment.kind === "markdown").length;
  const containerRef = useRef<HTMLDivElement>(null);
  const [readyCount, setReadyCount] = useState(0);
  const onReadyStable = useRef(onReady);
  onReadyStable.current = onReady;

  // A new body restarts the count: the old viewers are gone.
  useEffect(() => setReadyCount(0), [text]);

  const markReady = useCallback(() => setReadyCount((count) => count + 1), []);
  const taskScope = useCallback(() => containerRef.current, []);

  // Re-walk on every readiness tick: each pass rebuilds the ids in document order, so it converges.
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const seen = new Map<string, number>();
    for (const heading of root.querySelectorAll("h1, h2, h3, h4, h5, h6")) {
      heading.id = headingAnchorId(heading.textContent ?? "", seen);
      // Anchor links land the heading under the sticky app header otherwise.
      (heading as HTMLElement).style.scrollMarginTop = "5rem";
    }
  }, [readyCount, text]);

  // `onReady` still means ALL of it — the print route may not fire until the
  // last segment has rendered.
  useEffect(() => {
    if (proseCount === 0 || readyCount >= proseCount) onReadyStable.current?.();
  }, [readyCount, proseCount, text]);

  if (!segments.length) return null;

  return (
    <MarkdownSourceContext.Provider value={text}>
      <div ref={containerRef} data-page-body data-task-scope className={className}>
        {segments.map((segment, index) =>
          segment.kind === "markdown" ? (
            <RichViewer
              key={`md-${index}`}
              text={segment.text}
              eager
              onReady={markReady}
              onToggleTask={onToggleTask}
              taskScope={taskScope}
            />
          ) : (
            <ExtensionBlock key={`ext-${index}`} name={segment.name} body={segment.body} />
          ),
        )}
      </div>
    </MarkdownSourceContext.Provider>
  );
}

/** One `radd:<name>` block. `data-extension` is a proof hook: it shows the block became an element. */
function ExtensionBlock({ name, body }: { name: string; body: string }) {
  const extension = lookupPageExtension(name);
  const parsed = parseExtensionParams(body);
  return (
    <div data-extension={name}>
      {!extension ? (
        <UnknownExtension name={name} />
      ) : !parsed.ok ? (
        <ExtensionError name={name} error={parsed.error} />
      ) : (
        extension.render(parsed.params)
      )}
    </div>
  );
}
