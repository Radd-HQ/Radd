import { useEffect, useRef, useState } from "react";
import { useNodeViewContext } from "@prosemirror-adapter/react";
import {
  MAX_WIDTH,
  MIN_WIDTH,
  bucketFor,
  isResizable,
  srcSetFor,
  widthOf,
  withWidth,
} from "./image-width";

/**
 * An image you can resize, in pages and in comments (RADD-751).
 *
 * The size lives in the URL (`?w=640`), so the body stays markdown and the
 * attachment endpoint can serve fewer bytes rather than the browser scaling a
 * 4 MB screenshot down. See `image-width.ts` for why that beats the other two
 * options.
 *
 * One node view for both surfaces on purpose: a comment and a page body run the
 * same editor, and an image that resizes in one and not the other would be a
 * difference nobody could explain.
 */
export function ImageNodeView() {
  const { node, view, getPos, setAttrs, selected } = useNodeViewContext();
  const src = String(node.attrs.src ?? "");
  const alt = String(node.attrs.alt ?? "");
  const title = String(node.attrs.title ?? "");
  const stored = widthOf(src);
  const imgRef = useRef<HTMLImageElement>(null);
  // The width being dragged. Null while at rest, so the committed value in the
  // URL stays the source of truth.
  const [dragging, setDragging] = useState<number | null>(null);
  const [natural, setNatural] = useState(0);
  const editable = view.editable;
  const resizable = editable && isResizable(src);
  const width = dragging ?? stored;

  useEffect(() => {
    const image = imgRef.current;
    if (image?.complete && image.naturalWidth) setNatural(image.naturalWidth);
  }, [src]);

  const startDrag = (event: React.PointerEvent) => {
    event.preventDefault();
    event.stopPropagation();
    const image = imgRef.current;
    if (!image) return;
    const startX = event.clientX;
    const startWidth = image.getBoundingClientRect().width;
    const target = event.currentTarget as HTMLElement;
    target.setPointerCapture(event.pointerId);

    const move = (moveEvent: PointerEvent) => {
      const next = Math.round(startWidth + (moveEvent.clientX - startX));
      setDragging(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, next)));
    };
    const finish = (upEvent: PointerEvent) => {
      target.releasePointerCapture(upEvent.pointerId);
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", finish);
      const next = Math.round(startWidth + (upEvent.clientX - startX));
      const clamped = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, next));
      setDragging(null);
      commit(clamped);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", finish);
  };

  /** Write the width into the URL — one attribute change, one undo step. */
  const commit = (next: number) => {
    // A width at or past the natural size means "no width": the image is
    // already as big as it gets, and storing a number that does nothing is a
    // thing someone later has to explain.
    const full = natural > 0 && next >= natural;
    setAttrs({ src: withWidth(src, full ? null : bucketFor(next)) });
    void getPos;
  };

  const reset = () => setAttrs({ src: withWidth(src, null) });

  return (
    <span
      data-image-block
      data-width={width ?? ""}
      className={
        "radd-image group relative inline-block max-w-full align-baseline " +
        (selected ? "outline-2 outline-offset-2 outline-focus" : "")
      }
    >
      <img
        ref={imgRef}
        src={src}
        srcSet={width ? srcSetFor(src, width) : undefined}
        alt={alt}
        title={title || undefined}
        onLoad={(event) => setNatural(event.currentTarget.naturalWidth)}
        style={width ? { width: `${width}px` } : undefined}
        className="max-w-full rounded-md"
      />
      {resizable && (
        <>
          {/* The handle. A pointer capture, not a drag event: an <img> is
              natively draggable and a `dragstart` would run away with it. */}
          <span
            role="slider"
            tabIndex={0}
            aria-label="Resize image"
            aria-valuenow={width ?? natural}
            aria-valuemin={MIN_WIDTH}
            aria-valuemax={MAX_WIDTH}
            data-image-handle
            onPointerDown={startDrag}
            onKeyDown={(event) => {
              // Keyboard is not a nicety here: a pointer-only resize is
              // unreachable for anyone who does not use one.
              const current = width ?? imgRef.current?.getBoundingClientRect().width ?? 0;
              if (event.key === "ArrowRight") commit(Math.round(current) + 40);
              else if (event.key === "ArrowLeft") commit(Math.round(current) - 40);
              else return;
              event.preventDefault();
            }}
            className="absolute top-1/2 right-0 h-10 w-2.5 -translate-y-1/2 cursor-ew-resize rounded-l bg-accent opacity-0 transition-opacity group-hover:opacity-90 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-focus"
          />
          <span className="pointer-events-none absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] tabular-nums text-white opacity-0 transition-opacity group-hover:opacity-100">
            {width ? `${width}px` : "full size"}
          </span>
          {width && (
            <button
              type="button"
              onClick={reset}
              title="Reset to full size"
              aria-label="Reset image to full size"
              className="absolute top-1 right-1 cursor-pointer rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-white opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
            >
              Reset
            </button>
          )}
        </>
      )}
    </span>
  );
}
