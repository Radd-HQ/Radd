import { useEffect, useRef, useState } from "react";
import { useNodeViewContext } from "@prosemirror-adapter/react";
import { ImagePlus, Link2 } from "lucide-react";
import { UploadCanceledError } from "../../lib/useAttachmentUploader";
import { Button } from "../Button";
import {
  MAX_WIDTH,
  MIN_WIDTH,
  bucketFor,
  isResizable,
  srcSetFor,
  widthOf,
  withWidth,
} from "./image-width";

/** Uploads a file and resolves to its URL — the surface's `onUploadImage`. */
export type ImageUploader = (file: File) => Promise<string>;

/** `ApiError` already carries the server's `detail` as its message. */
const errorText = (cause: unknown) =>
  cause instanceof Error && cause.message ? cause.message : "Upload failed. Try again.";

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
 *
 * It owns EVERY state the node has, including "no source yet" (RADD-760). That
 * state is not an edge case: it is what the toolbar's Image button produces, and
 * what an imported body containing `![](…)` already contains. Rendering it as a
 * bare `<img src="">` drew a 0x0 element, so the button read as broken and the
 * import read as empty — with no file picker anywhere in the document.
 */
export function ImageNodeView({ upload }: { upload?: ImageUploader }) {
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

  // No source yet: the node is real but there is nothing to draw, so draw the
  // way to fill it instead of an invisible 0x0 <img> (RADD-760).
  if (!src && editable) {
    return <ImageEmptyState upload={upload} onPick={(url) => setAttrs({ src: url })} />;
  }

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
            data-image-chrome
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
              data-image-chrome
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

/**
 * The "no source yet" card: pick a file, or paste a URL.
 *
 * Both routes are offered because they are genuinely different jobs — a
 * screenshot from disk, and an image already hosted somewhere. Crepe's uploader
 * offered both, and removing it removed both.
 *
 * `data-image-chrome` is what the node view's `stopEvent` looks for: without it
 * ProseMirror interprets every keystroke aimed at the URL field as a keystroke
 * on the document, and typing a URL edits the doc instead of the input.
 */
function ImageEmptyState({
  upload,
  onPick,
}: {
  upload?: ImageUploader;
  onPick: (url: string) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const choose = async (file: File | undefined) => {
    if (!file || !upload) return;
    setBusy(true);
    setError(null);
    try {
      onPick(await upload(file));
    } catch (cause) {
      // Dismissing the storage prompt is a decision, not a failure — the card
      // just stays as it was. Anything else reports WHAT went wrong: "Upload
      // failed" alone sends you to the network tab to find out.
      if (cause instanceof UploadCanceledError) return;
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span
      data-image-block
      data-image-empty
      data-image-chrome
      contentEditable={false}
      // A DEFINITE width, not `w-full`: the image node is inline, so its node
      // view root is a <span> and a percentage width resolves against an inline
      // formatting context — it shrink-to-fit at 192px and wrapped every
      // control onto its own line.
      className="my-1 flex w-[26rem] max-w-full flex-col gap-2 rounded-md border border-dashed border-strong bg-elevated p-3 align-baseline"
    >
      <span className="flex items-center gap-2">
        {upload && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              aria-label="Choose an image to upload"
              onChange={(event) => void choose(event.target.files?.[0])}
              className="hidden"
            />
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              // shrink-0: in a flex row the hint would otherwise squeeze the
              // button until its own label wrapped onto two lines.
              className="shrink-0 whitespace-nowrap"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => fileRef.current?.click()}
            >
              <ImagePlus size={14} aria-hidden />
              {busy ? "Uploading…" : "Choose image"}
            </Button>
          </>
        )}
        <span className="text-[11px] leading-tight text-fg-muted">
          {upload ? "or drop / paste an image" : "Paste an image URL"}
        </span>
      </span>
      <span className="flex items-center gap-2">
        <Link2 size={14} className="shrink-0 text-fg-faint" aria-hidden />
        <input
          type="url"
          value={url}
          placeholder="https://…"
          aria-label="Image URL"
          onChange={(event) => setUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || !url.trim()) return;
            event.preventDefault();
            onPick(url.trim());
          }}
          className="h-7 min-w-0 flex-1 rounded-md border border-subtle bg-surface px-2 text-[12px] text-heading placeholder:text-fg-faint focus:border-accent focus:outline-none"
        />
        <Button
          size="sm"
          variant="ghost"
          disabled={!url.trim()}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onPick(url.trim())}
        >
          Add
        </Button>
      </span>
      {error && <span className="text-[11px] text-red-400">{error}</span>}
    </span>
  );
}
