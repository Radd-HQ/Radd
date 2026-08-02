import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LazyRichViewer as RichViewer } from "../editor/LazyRichViewer";
import { MarkdownSourceCtx } from "../../lib/markdown";
import { headingAnchorId } from "../../lib/markdown-outline";
import "./extensions"; // side-effect: registers the first-party extensions
import {
  ExtensionError,
  UnknownExtension,
  lookupPageExtension,
  parseExtensionParams,
  splitExtensionBlocks,
} from "../../lib/page-extensions";

/**
 * A page body: prose rendered by Crepe, extension blocks rendered as React
 * (RADD-709).
 *
 * Two jobs beyond stitching the segments together:
 *
 *  - **Heading anchors.** `radd:toc` links to `#<slug-of-heading>`, and Crepe
 *    emits headings with no ids at all, so the links would go nowhere. Ids are
 *    assigned here, over the RENDERED headings, using the same duplicate rule
 *    `headingsOf` uses on the source — both walk the document in order, so the
 *    two agree without sharing state.
 *  - **Readiness.** Crepe creates asynchronously. Anchors can only be assigned
 *    once every prose run has rendered, which is what `onReady` counts.
 */
export function PageBody({
  text,
  className = "",
  onReady,
  // A page body is ONE document with a handful of prose runs, not an issue's
  // hundred-comment thread — which is what LazyRichViewer's viewport gate was
  // built for. Deferring here buys nothing and costs correctness: anything
  // below the fold shows raw markdown, `radd:toc` links to heading ids that
  // were never assigned, and printing emits placeholder text.
  eager = true,
}: {
  text: string;
  className?: string;
  /** Fires once every segment has rendered — the print route waits on it. */
  onReady?: () => void;
  /** Defaults to true, and should almost always stay that way — see below. */
  eager?: boolean;
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

  // Re-walk on EVERY readiness tick, not once all segments are ready. Prose runs
  // mount lazily as they near the viewport, so on a long page the tail may not
  // mount for minutes — gating the anchor pass on the total meant a `radd:toc`
  // on a long page linked to ids that were never assigned. Each pass rebuilds
  // the whole map in document order, so it is idempotent and converges.
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
    <MarkdownSourceCtx.Provider value={text}>
      <div ref={containerRef} data-page-body className={className}>
        {segments.map((segment, index) =>
          segment.kind === "markdown" ? (
            <RichViewer
              key={`md-${index}`}
              text={segment.text}
              eager={eager}
              onReady={markReady}
            />
          ) : (
            <ExtensionBlock key={`ext-${index}`} name={segment.name} body={segment.body} />
          ),
        )}
      </div>
    </MarkdownSourceCtx.Provider>
  );
}

/** One `radd:<name>` block, and the two ways it can fail to be one.
 *
 *  `data-extension` is load-bearing for the render proof, not decoration: it is
 *  what lets a headless check assert a block became an ELEMENT rather than
 *  staying source. */
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
