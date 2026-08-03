import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { ComponentProps } from "react";
import type { RichViewer } from "./RichViewer";

// Same heavy Milkdown/ProseMirror chunk as the editor — loaded on demand.
const RichViewerImpl = lazy(() =>
  import("./RichViewer").then((module) => ({ default: module.RichViewer })),
);

/** The raw markdown, plainly — shown until the real renderer mounts. Keeps long
 * comment threads cheap: it's also the pre-viewport placeholder. */
function PlainFallback({ text }: { text: string }) {
  return (
    <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-fg">{text}</div>
  );
}

/**
 * Drop-in for RichViewer that (a) code-splits the engine and (b) only mounts a
 * Crepe instance once the content nears the viewport — an issue can carry
 * hundreds of comments, and hundreds of eager ProseMirror instances would jank
 * the page. Until then the raw markdown holds the layout.
 */
export function LazyRichViewer({
  eager = false,
  ...props
}: ComponentProps<typeof RichViewer> & {
  /** Mount immediately, ignoring the viewport. For surfaces that READ the
   *  rendered output rather than just show it — printing (RADD-736) must not
   *  emit a page of raw markdown because a section was below the fold. */
  eager?: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(eager);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || eager) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "600px" }, // mount a screen ahead so scrolling feels seamless
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, [eager]);

  return (
    <div ref={hostRef}>
      {visible ? (
        <Suspense fallback={<PlainFallback text={props.text} />}>
          <RichViewerImpl {...props} />
        </Suspense>
      ) : (
        <PlainFallback text={props.text} />
      )}
    </div>
  );
}
