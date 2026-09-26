import { useMemo } from "react";
import { useSlot, type SlotIdValue } from "./slots";

/**
 * Which contributed PAGE answers a path (RADD-1401). A page contribution's `match` is either the
 * literal path it owns (`/settings/email`) or a PATTERN in which a `$name` segment captures exactly
 * one non-empty path segment (`/public/invites/$token`). The host hands the captures to the page as
 * `params`, decoded.
 */

/** What the host passes a contributed page (`route.page`, `settings.page`, `public.page`). */
export interface ContributedPageProps {
  /** The path the page answers (the pathname, or the segment for a project settings page). */
  path: string;
  /** The captures of a pattern `match`, by name; empty for a literal one. */
  params: Readonly<Record<string, string>>;
}

/** The captures when `path` fits `pattern`, else null. A literal pattern fits only itself; a
 *  `$name` segment fits one non-empty segment, so `/notes/$noteId` fits `/notes/abc` but not
 *  `/notes/` or `/notes/abc/more`. */
export function matchPagePath(pattern: string, path: string): Record<string, string> | null {
  if (pattern === path) return {};
  if (!pattern.includes("/$")) return null;
  const want = pattern.split("/");
  const got = path.split("/");
  if (want.length !== got.length) return null;
  const params: Record<string, string> = {};
  for (let index = 0; index < want.length; index += 1) {
    const segment = want[index];
    const actual = got[index];
    if (segment.startsWith("$") && segment.length > 1) {
      if (!actual) return null;
      try {
        params[segment.slice(1)] = decodeURIComponent(actual);
      } catch {
        return null; // a malformed escape is not a path any page answers
      }
    } else if (segment !== actual) {
      return null;
    }
  }
  return params;
}

/** The page contribution answering `path` on `slot`, with its captures: a literal `match` wins
 *  over a pattern, and among patterns the first in the slot's order. */
export function usePageMatch(
  slot: SlotIdValue,
  path: string,
): { plugin: string; match: string; params: Record<string, string> } | undefined {
  const entries = useSlot(slot);
  return useMemo(() => {
    const exact = entries.find((entry) => entry.contribution.match === path);
    if (exact) return { plugin: exact.plugin, match: path, params: {} };
    for (const entry of entries) {
      const pattern = entry.contribution.match;
      if (typeof pattern !== "string") continue;
      const params = matchPagePath(pattern, path);
      if (params) return { plugin: entry.plugin, match: pattern, params };
    }
    return undefined;
  }, [entries, path]);
}
