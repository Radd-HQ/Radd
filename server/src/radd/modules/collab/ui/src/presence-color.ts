/**
 * The remote-cursor colour (spec 122), decided in ONE place.
 *
 * A person's chosen avatar colour if they have one; otherwise a deterministic
 * pick from the house palette. The palette entries are token REFERENCES, not
 * resolved values: the string travels through awareness to every other client
 * and is resolved there, in that viewer's theme — which is what makes one
 * choice contrast on both. Each token is defined on `html` and `html.light`
 * (index.css), so the reference is never dangling.
 */
const PALETTE = [
  "var(--accent-fill)",
  "var(--chart-todo)",
  "var(--chart-progress)",
  "var(--chart-triage)",
  "var(--status-danger)",
  "var(--priority-high)",
] as const;

const FALLBACK = PALETTE[0];

/** djb2 over the user id — the same stable hash Avatar's fallback hue uses. */
function hash(id: string): number {
  let value = 5381;
  for (const char of id) value = (value * 33 + char.charCodeAt(0)) >>> 0;
  return value;
}

export function presenceColor(user: { id: string; avatar_color?: string | null }): string {
  if (user.avatar_color) return user.avatar_color;
  return PALETTE[hash(user.id) % PALETTE.length];
}

/** A colour value shape we are willing to put into a style attribute. The
 *  value came from another client's awareness state, so it is data. */
const SAFE_COLOR =
  /^(#[0-9a-f]{3,8}|var\(--[\w-]+\)|(hsl|hsla|rgb|rgba|oklch)\([^;{}()]*\)|[a-z]{3,20})$/i;

/** The colour a REMOTE state carried, or the fallback when it is not one. */
export function safeCursorColor(value: unknown): string {
  return typeof value === "string" && SAFE_COLOR.test(value) ? value : FALLBACK;
}
