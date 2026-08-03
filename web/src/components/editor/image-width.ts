/**
 * The image-width convention (RADD-751).
 *
 * Markdown cannot express an image size — `![alt](url)` has nowhere to put one.
 * Of the three ways out, this is the one that keeps the body pure markdown AND
 * fixes the bandwidth problem: `?w=640` is a URL, so FTS, the embedder, the
 * export, MCP and the public surface all keep reading exactly what they read
 * before, and the attachment endpoint serves fewer bytes rather than the browser
 * scaling a 4 MB screenshot down to 600px.
 *
 * The alternatives, recorded so they are not re-argued: raw `<img width>` HTML
 * makes the body stop being markdown; a `radd:image` fence is the heaviest
 * possible answer for something as ordinary as a picture.
 */

/** Widths the server will actually serve. Mirrors `thumbnails.WIDTH_BUCKETS`. */
export const WIDTH_BUCKETS = [160, 320, 480, 640, 800, 1024, 1280, 1600, 1920];

/** Below this, an image is a decoration nobody can see; above it, unbounded. */
export const MIN_WIDTH = 80;
export const MAX_WIDTH = 1920;

/**
 * Only OUR attachments carry a width.
 *
 * A `?w=` appended to someone else's URL is at best ignored and at worst breaks
 * it — a presigned or otherwise signed link has a signature over its query.
 * External images therefore render at their natural size and offer no handle,
 * which is honest: there is nowhere to put the number.
 */
export const isResizable = (src: string): boolean =>
  /^\/api\/v1\/attachments\/[0-9a-f-]{36}(\?|$)/i.test(src) ||
  /^https?:\/\/[^/]+\/api\/v1\/attachments\/[0-9a-f-]{36}(\?|$)/i.test(src);

/** The width a src asks for, or null. */
export function widthOf(src: string): number | null {
  const match = /[?&]w=(\d+)/.exec(src);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** `src` with `?w=` set, replaced, or removed when `width` is null. */
export function withWidth(src: string, width: number | null): string {
  const [base, query = ""] = src.split("?", 2);
  const params = new URLSearchParams(query);
  if (width === null) params.delete("w");
  else params.set("w", String(width));
  const rest = params.toString();
  return rest ? `${base}?${rest}` : base;
}

/** The smallest bucket that can serve `width` — what the server will pick. */
export const bucketFor = (width: number): number =>
  WIDTH_BUCKETS.find((bucket) => width <= bucket) ?? MAX_WIDTH;

/**
 * A `srcset` for the same image at 1× and 2×.
 *
 * The markdown holds ONE width; the node view is free to ask for a denser
 * variant at render time, which is what keeps a resized screenshot from looking
 * soft on a retina display. Nothing about the stored body changes — this exists
 * only in the rendered DOM.
 */
export function srcSetFor(src: string, width: number): string | undefined {
  if (!isResizable(src)) return undefined;
  const one = bucketFor(width);
  const two = bucketFor(width * 2);
  if (two === one) return undefined;
  return `${withWidth(src, one)} 1x, ${withWidth(src, two)} 2x`;
}
