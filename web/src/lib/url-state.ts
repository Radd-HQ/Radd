/**
 * Page state that belongs in the URL (spec: "my filters shouldn't vanish on
 * refresh").
 *
 * The split: anything that changes WHICH ITEMS YOU SEE lives here, in the URL.
 * Pure display state (collapsed groups, card display, panel widths) stays in
 * localStorage. That line matters — persisting an ad-hoc query into a saved
 * view's own storage would make the view quietly stop meaning what its
 * definition says, whereas a URL is explicitly "this screen, right now": a
 * refresh keeps it, a link reproduces it, and a fresh navigation gives you the
 * clean view back.
 *
 * SHORTENING. Short state stays inline and readable (`?q=priority+%3D+high`) so
 * the URL is still something you can eyeball, edit and paste to someone. Past
 * `MAX_INLINE` characters it is stashed under a content hash and the URL
 * collapses to `?s=<hash>` — a client-side short link.
 *
 * The cost of that, stated plainly: a `?s=` link only resolves in the browser
 * that made it. Opening one elsewhere finds no entry and falls back to the
 * view's defaults rather than erroring. Inline links (the common case — most
 * SLQ queries are well under the threshold) travel fine. A server-side
 * shortener would fix the portability, at the price of a table, an endpoint and
 * a garbage-collection story; this buys the short URL for none of that.
 *
 * Writes use replaceState, not pushState: toggling a filter chip should not
 * stack up history entries you have to press Back through.
 */

const SHORT_PARAM = "s";
const SHORT_PREFIX = "radd.url.";
/** Beyond this many encoded chars, swap the params for a stashed short id. */
const MAX_INLINE = 180;
/** Params this module owns; everything else in the query string is left alone.
 *  Keys are short because they ride in the URL, and shared across pages —
 *  `q`/`f` are the SLQ bar + quick-filter chips, `pf` the user's PERSONAL
 *  saved-filter chips, the rest are the timesheet's period/date/grouping and
 *  its project/team/person filters. */
const OWNED = ["q", "f", "pf", "p", "d", "g", "pr", "tm", "u", "pg"] as const;

export type UrlState = Partial<Record<(typeof OWNED)[number], string>>;

function hash(input: string): string {
  // FNV-1a — short, stable, and collision-tolerable: a miss falls back to
  // defaults, it does not corrupt anything.
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

/** Current URL state, resolving a `?s=` short id when present. */
export function readUrlState(): UrlState {
  if (typeof window === "undefined") return {};
  const params = new URLSearchParams(window.location.search);
  const short = params.get(SHORT_PARAM);
  if (short) {
    try {
      const raw = window.localStorage.getItem(SHORT_PREFIX + short);
      return raw ? (JSON.parse(raw) as UrlState) : {};
    } catch {
      return {}; // unknown id (another browser) — fall back to the view's defaults
    }
  }
  const out: UrlState = {};
  for (const key of OWNED) {
    const value = params.get(key);
    if (value) out[key] = value;
  }
  return out;
}

/**
 * Merge `patch` into the URL state. A null/empty value drops the key; when
 * every owned key is gone the query string is left clean rather than carrying
 * empty params.
 */
type UrlPatch = Partial<Record<(typeof OWNED)[number], string | null>>;

export function writeUrlState(patch: UrlPatch): void {
  if (typeof window === "undefined") return;
  const next: UrlState = { ...readUrlState() };
  for (const [key, value] of Object.entries(patch)) {
    if (value === null || value === undefined || value === "") delete next[key as keyof UrlState];
    else next[key as keyof UrlState] = value;
  }

  const params = new URLSearchParams(window.location.search);
  for (const key of OWNED) params.delete(key);
  params.delete(SHORT_PARAM);

  const inline = new URLSearchParams();
  for (const key of OWNED) if (next[key]) inline.set(key, next[key]!);
  const encoded = inline.toString();

  if (encoded.length > MAX_INLINE) {
    const serialized = JSON.stringify(next);
    const id = hash(serialized);
    try {
      window.localStorage.setItem(SHORT_PREFIX + id, serialized);
    } catch {
      // Storage full/blocked — fall through and use the long URL rather than
      // silently losing the state.
    }
    params.set(SHORT_PARAM, id);
  } else {
    for (const [key, value] of inline) params.set(key, value);
  }

  const search = params.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`,
  );
}

/** Drop every owned param (and any short id) from the URL. */
export function clearUrlState(): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  const short = params.get(SHORT_PARAM);
  if (short) {
    try {
      window.localStorage.removeItem(SHORT_PREFIX + short);
    } catch {
      /* best effort */
    }
  }
  for (const key of OWNED) params.delete(key);
  params.delete(SHORT_PARAM);
  const search = params.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`,
  );
}

/** True when the URL currently carries any state this module owns. */
export function hasUrlState(): boolean {
  const state = readUrlState();
  return OWNED.some((key) => Boolean(state[key]));
}

/**
 * Forget every per-surface display preference for a view: collapsed groups,
 * card display, panel widths/collapse, tray filter, roadmap gutter. Paired
 * with `clearUrlState` by the "Reset view" control — the URL half restores
 * WHAT you see, this half restores HOW it looks.
 */
export function clearViewDisplayState(viewId: string): void {
  if (typeof window === "undefined") return;
  const doomed: string[] = [];
  for (let i = 0; i < window.localStorage.length; i += 1) {
    const key = window.localStorage.key(i);
    if (!key) continue;
    const perView = key.includes(viewId);
    const shared = key.startsWith("radd.panel.") || key === "radd.peek.width";
    if (perView || shared) doomed.push(key);
  }
  for (const key of doomed) window.localStorage.removeItem(key);
}
